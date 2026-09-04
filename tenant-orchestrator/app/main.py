"""tenant-orchestrator — the REST surface custom_super_admin already calls.

Every route below exists because an installed Odoo module calls it. The paths,
the verbs and the bodies come from
``addons/control_plane/custom_super_admin/models/orchestrator_client.py``; they
were not designed here. That module has been calling
``http://tenant-orchestrator:8080`` since it was imported, into nothing.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import string

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from .config import settings_from_env
from .odoo_rpc import OdooClient, OdooError
from .registry import Registry, TenantNotFound
from .security import HMACMiddleware

logger = logging.getLogger("orchestrator")

#: Identical to custom_athera_provisioner.SLUG_RE and to the CHECK on
#: tenant_registry.tenants.slug. A slug becomes a database name AND a
#: replication slot name; slot names forbid dashes, so every layer enforces the
#: tightest constraint rather than its own.
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

#: Slugs the platform has already spent on itself. Each one is the first label
#: of a hostname the edge routes by name, so a tenant holding one would answer
#: on a URL the platform already owns -- it hijacks a platform route. That is
#: the entire reason. It is NOT about database names: a colliding database is a
#: different failure and is already refused by athera.provisioner, which checks
#: for an existing database before it enqueues anything.
#:
#: The SAME set is enforced in two other layers, and the three must stay
#: identical: the Odoo provisioning wizard (custom_super_admin), so an operator
#: is told before a call is made, and the CHECK on tenant_registry.tenants.slug,
#: so a direct INSERT cannot walk past both.
RESERVED_SLUGS = frozenset({"admin", "app", "auth", "insight", "mail", "odoo", "www"})

#: Alphabet for a generated admin password: letters and digits only. The value
#: crosses JSON-RPC, then a child process's environment inside Odoo, then an
#: operator's clipboard and a login form. Characters a shell, an argv parser or
#: a URL encoder could reinterpret are left out rather than escaped correctly in
#: each of those places -- entropy is bought with length instead.
_PASSWORD_ALPHABET = string.ascii_letters + string.digits
#: 32 characters of a 62-symbol alphabet is ~190 bits of entropy.
_PASSWORD_LENGTH = 32

#: The only keys of Odoo's job handle that are copied into the audit log. A
#: whitelist, not a blacklist: the detail column exists so a registry row can be
#: correlated with a job, and whatever else the far side chose to put in that
#: dict has not been reviewed for secrets. See the credential note in
#: `provision` below.
JOB_LOG_KEYS = ("slug", "job_uuid")

ACTIONS = Counter(
    "athera_orchestrator_actions_total",
    "Control-plane actions, by action and outcome.",
    ["action", "outcome"],
)


def _bad_request(detail: str) -> JSONResponse:
    return JSONResponse({"error": "invalid_request", "detail": detail}, status_code=400)


def _generate_admin_password() -> str:
    """A fresh administrator password for a tenant that did not bring one.

    Callers do not send one. The previous code passed "" straight through to
    ``athera.provisioner``, whose ``if admin_password:`` then skipped setting
    anything -- so the new tenant's administrator kept the password `odoo -i`
    gives it, which is the same well-known default in every database it builds.
    Generating one is not a convenience: there is no safe value for "absent" on
    this argument.
    """
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


def _redact(text: str, secret: str | None) -> str:
    """Remove one known credential from text that is about to be persisted.

    The 502 path below writes Odoo's fault string into the append-only action
    log. That string is composed on the far side, and the far side was just
    handed the credential -- a fault that quotes its own arguments back would
    publish it to every super-admin, in a table nothing deletes from.

    Deliberately not a general-purpose scrubber: at this point exactly one
    secret is known, so exactly that one is removed. It is also not a substitute
    for Odoo not quoting credentials into errors; it is the half of that problem
    this side can fix alone.
    """
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def _job_detail(job) -> dict:
    """Audit detail for a provisioning job -- correlation identifiers only.

    The credential MUST NOT pass through here. Odoo returns this dict over RPC;
    copying it whole into the action log would make any field the far side ever
    adds -- a credential echoed back, say -- permanently readable by every
    super-admin.
    """
    if not isinstance(job, dict):
        return {"job": None}
    return {"job": {key: job[key] for key in JOB_LOG_KEYS if key in job}}


def _not_found(slug: str) -> JSONResponse:
    return JSONResponse(
        {"error": "not_found", "detail": "No tenant %r." % slug}, status_code=404
    )


async def _body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def create_app() -> FastAPI:
    settings = settings_from_env()
    registry = Registry(settings.registry_dsn)
    odoo = OdooClient(
        settings.odoo_url, settings.odoo_db, settings.odoo_login, settings.odoo_password
    )

    app = FastAPI(title="ATHERA tenant-orchestrator", docs_url=None, redoc_url=None)
    app.add_middleware(
        HMACMiddleware,
        secret=settings.shared_secret,
        window_seconds=settings.hmac_window_seconds,
    )
    router = APIRouter()

    # --- unsigned -----------------------------------------------------
    @router.get("/healthz")
    @router.get("/health")
    def health():
        # Reports what it can actually reach. A health check that only proves
        # the process is running is the kind that stays green through an outage.
        reg_ok = registry.ping()
        return JSONResponse(
            {"status": "ok" if reg_ok else "degraded", "registry": reg_ok},
            status_code=200 if reg_ok else 503,
        )

    @router.get("/metrics")
    def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    # --- tenants ------------------------------------------------------
    @router.get("/v1/tenants")
    def list_tenants(state: str | None = None):
        return registry.list_tenants(state)

    @router.get("/v1/tenants/{slug}")
    def get_tenant(slug: str):
        try:
            tenant = registry.get_tenant(slug)
        except TenantNotFound:
            return _not_found(slug)
        tenant["entitlement"] = registry.entitlement(slug)
        return tenant

    @router.post("/v1/tenants", status_code=202)
    async def provision(request: Request):
        """Register the tenant, then ask Odoo to build its database.

        202, not 201: the row exists when this returns and the database does
        not. Answering 201 would tell the console the tenant is ready while a
        job is still installing three hundred modules.
        """
        body = await _body(request)
        actor = getattr(request.state, "actor", "unknown")
        slug = (body.get("slug") or "").strip()

        if not SLUG_RE.match(slug):
            ACTIONS.labels("provision", "rejected").inc()
            return _bad_request(
                "Invalid slug %r. Must match %s -- lowercase, starts with a letter, "
                "no dashes (Postgres replication slot names forbid them)." % (slug, SLUG_RE.pattern)
            )

        if slug in RESERVED_SLUGS:
            ACTIONS.labels("provision", "rejected").inc()
            return _bad_request(
                "Slug %r is reserved. %s are subdomain labels this platform "
                "already routes to its own services, so a tenant named after one "
                "would take over that route. This is not about database names -- "
                "a colliding database is refused separately, by "
                "athera.provisioner." % (slug, ", ".join(sorted(RESERVED_SLUGS)))
            )

        payload = {
            "slug": slug,
            "display_name": body.get("display_name") or slug,
            "db_name": body.get("db_name") or slug,
            "plan_code": body.get("plan_code"),
            "valid_until": body.get("valid_until"),
            "insight_source_kind": body.get("insight_source_kind") or "odoo",
            "contact_email": body.get("contact_email"),
            "contact_phone": body.get("contact_phone"),
            "notes": body.get("notes"),
        }

        try:
            tenant = registry.create_tenant(payload)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            ACTIONS.labels("provision", "failure").inc()
            registry.log_action(slug, "provision", actor, "failure", error=str(exc)[:500])
            return _bad_request("Could not register %r: %s" % (slug, str(exc)[:300]))

        # An Insight-only client brings its own application; there is no Odoo
        # database to build, so the row is the whole job.
        if payload["insight_source_kind"] != "odoo":
            registry.log_action(slug, "provision", actor, "success",
                                {"insight_source_kind": payload["insight_source_kind"]})
            ACTIONS.labels("provision", "success").inc()
            # Same response shape as the Odoo path, so the caller reads one
            # contract. There is no Odoo administrator to give a password to,
            # and null says that rather than inventing a credential nobody holds.
            return {"tenant": tenant, "job": None, "admin_password": None}

        # The body key stays `modules`; there is deliberately no
        # `install_modules` alias. One name means a caller that sends the wrong
        # one gets the default module set and a visible surprise, instead of an
        # alias quietly absorbing the mistake.
        modules = body.get("modules") or list(settings.provision_modules)

        # CREDENTIAL BOUNDARY. From here to the return statement, the password
        # exists in exactly three places: this local, the RPC argument, and the
        # response body. It MUST NOT reach registry.log_action (the audit detail
        # goes through _job_detail, which whitelists), any logger call, or any
        # metric label -- the action log is readable by every super-admin and
        # /metrics is served unsigned.
        supplied = body.get("admin_password")
        admin_password = (
            supplied if isinstance(supplied, str) and supplied
            else _generate_admin_password()
        )
        try:
            job = odoo.enqueue_provision(slug, modules, admin_password)
        except OdooError as exc:
            # The row stays, in state `provisioning`, and the failure is on the
            # audit log. Rolling it back would lose the only record that anyone
            # tried, and `provisioning` is already the state that means "not
            # usable yet" -- tenant_registry.is_active() answers false for it.
            # Redacted BEFORE truncation: slicing first could leave half a
            # credential in the log, which is still a credential with a hint.
            reason = _redact(str(exc), admin_password)
            registry.set_state(slug, "failed")
            registry.log_action(slug, "provision", actor, "failure", error=reason[:500])
            ACTIONS.labels("provision", "failure").inc()
            return JSONResponse(
                {"error": "provision_failed", "detail": reason[:300]}, status_code=502
            )

        registry.log_action(slug, "provision", actor, "success", _job_detail(job))
        ACTIONS.labels("provision", "success").inc()
        # Handed back ONCE, here, because this is the only moment anyone can
        # still read it: nothing on this side stores it. No GET route repeats
        # it, and none can -- there is nothing left to repeat.
        return {"tenant": tenant, "job": job, "admin_password": admin_password}

    def _transition(slug, state, stamp, action, actor, detail=None):
        try:
            tenant = registry.set_state(slug, state, stamp)
        except TenantNotFound:
            ACTIONS.labels(action, "not_found").inc()
            return _not_found(slug)
        registry.log_action(slug, action, actor, "success", detail)
        ACTIONS.labels(action, "success").inc()
        return tenant

    @router.post("/v1/tenants/{slug}/suspend")
    async def suspend(slug: str, request: Request):
        body = await _body(request)
        return _transition(
            slug, "suspended", "suspended_at", "suspend",
            getattr(request.state, "actor", "unknown"),
            {"reason": body.get("reason")},
        )

    @router.post("/v1/tenants/{slug}/resume")
    async def resume(slug: str, request: Request):
        return _transition(
            slug, "active", "activated_at", "resume",
            getattr(request.state, "actor", "unknown"),
        )

    @router.delete("/v1/tenants/{slug}")
    async def archive(slug: str, request: Request):
        body = await _body(request)
        return _transition(
            slug, "archived", "archived_at", "archive",
            getattr(request.state, "actor", "unknown"),
            {"retention_days": body.get("retention_days", 30)},
        )

    # --- backups ------------------------------------------------------
    @router.get("/v1/tenants/{slug}/backups")
    def list_backups(slug: str, limit: int = 100):
        return registry.list_backups(slug, limit)

    @router.get("/v1/backups/{backup_id}")
    def get_backup(backup_id: int):
        try:
            return registry.get_backup(backup_id)
        except TenantNotFound:
            return JSONResponse(
                {"error": "not_found", "detail": "No backup %d." % backup_id},
                status_code=404,
            )

    @router.post("/v1/tenants/{slug}/backups", status_code=501)
    async def run_backup(slug: str, request: Request):
        """NOT IMPLEMENTED, and answering 501 rather than pretending.

        A backup means pg_dump plus the filestore, and this container has
        neither the binary nor a path to the filestore volume -- both on
        purpose. `scripts/tenant-backup.sh` does it correctly today, including
        the manifest and the SHA256SUMS, and it runs on the host.

        Wiring it means the same choice provisioning faced: a job inside Odoo,
        which is where the filestore already is. Until then this route says so
        instead of returning a 200 the console would believe.
        """
        ACTIONS.labels("backup", "unimplemented").inc()
        return JSONResponse(
            {
                "error": "not_implemented",
                "detail": (
                    "Backups run from scripts/tenant-backup.sh on the host. This "
                    "service has neither pg_dump nor the filestore, deliberately. "
                    "Run: make tenant-backup TENANT=%s" % slug
                ),
            },
            status_code=501,
        )

    app.include_router(router)
    logger.info(
        "orchestrator ready: registry=%s odoo=%s db=%s",
        bool(settings.registry_dsn), settings.odoo_url, settings.odoo_db,
    )
    return app
