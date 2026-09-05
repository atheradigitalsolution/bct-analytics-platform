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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


# ---------------------------------------------------------------------------
# Request bodies
#
# THESE REPLACE A HAND-WRITTEN PARSER THAT COULD NOT FAIL. It read the raw body,
# and on malformed JSON -- or on JSON that was a list, or a string, or a number
# -- returned `{}`. A corrupt request was therefore indistinguishable from an
# empty one, and `POST /v1/tenants` with a body of `not json at all` reached the
# slug check as an absent slug: a 400 that named the wrong problem. FastAPI
# validates these models before the handler runs, so the same request is now a
# 422 that names the actual one.
#
# `extra="forbid"` IS THE POINT OF THE EXERCISE, not tidiness. The provisioning
# wizard sends nine keys; this service used to read four and drop the rest
# without a word -- `csm_user_id`, `features` and `backup_schedule_cron` all have
# real columns on `tenant_registry.tenants` and were being thrown away on the way
# in. Forbidding unknown keys converts every future version of that mistake from
# silent data loss into an immediate, named refusal. It is the same reasoning
# already written down for `modules`: one name, and a caller that sends the wrong
# one gets a visible surprise rather than a quiet default.


class ProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    display_name: str | None = None
    db_name: str | None = None
    plan_code: str | None = None
    valid_until: str | None = None
    insight_source_kind: str = "odoo"
    contact_email: str | None = None
    contact_phone: str | None = None
    csm_user_id: int | None = None
    features: dict | None = None
    backup_schedule_cron: str | None = None
    notes: str | None = None
    #: The body key stays `modules`; there is deliberately no `install_modules`
    #: alias. One name means a caller that sends the wrong one gets the default
    #: module set and a visible surprise, instead of an alias quietly absorbing
    #: the mistake.
    modules: list[str] | None = None
    #: Never logged, never echoed into the audit detail. See the credential
    #: boundary in `provision` below.
    admin_password: str | None = None

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, value: str) -> str:
        value = (value or "").strip()
        if not SLUG_RE.match(value):
            raise ValueError(
                "Invalid slug %r. Must match %s -- lowercase, starts with a "
                "letter, no dashes (Postgres replication slot names forbid "
                "them)." % (value, SLUG_RE.pattern)
            )
        if value in RESERVED_SLUGS:
            raise ValueError(
                "Slug %r is reserved. %s are subdomain labels this platform "
                "already routes to its own services, so a tenant named after one "
                "would take over that route. This is not about database names -- "
                "a colliding database is refused separately, by "
                "athera.provisioner." % (value, ", ".join(sorted(RESERVED_SLUGS)))
            )
        return value


class SuspendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(default=30, ge=0, le=3650)


#: Ceiling on a single manual extension. A grant is typed by a human into a form,
#: and a slipped keystroke on a field measured in days is the difference between
#: a month and a decade. 400 days clears any annual contract with room to spare
#: and still refuses the decade.
MAX_EXTEND_DAYS = 400


class ExtendRequest(BaseModel):
    """A manual grant of access time, outside the invoice cycle.

    `reason` IS REQUIRED, and that is the whole design. Extending access without
    payment is legitimate -- a pilot, a goodwill gesture, an invoice under
    dispute -- but it is exactly the action a reader of the audit log will want
    explained six months later, and the only person who can explain it is the one
    clicking the button now.
    """

    model_config = ConfigDict(extra="forbid")

    days: int = Field(ge=1, le=MAX_EXTEND_DAYS)
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_is_a_sentence(cls, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 8:
            raise ValueError(
                "say why in a sentence someone can read later; 'ok' and 'x' are "
                "not reasons and this field exists to be read months from now"
            )
        return value


def create_app() -> FastAPI:
    settings = settings_from_env()
    registry = Registry(settings.registry_dsn)
    odoo = OdooClient(
        settings.odoo_url, settings.odoo_db, settings.odoo_login, settings.odoo_password
    )

    app = FastAPI(title="ATHERA tenant-orchestrator", docs_url=None, redoc_url=None)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        """One error shape for the whole service, whoever raised it.

        FastAPI answers a validation failure with 422 and a `detail` that is a
        LIST of dicts. Every other refusal here is 400 with a `detail` that is a
        sentence, and the only consumer -- `orchestrator_client._request` -- logs
        `resp.text[:300]` for a human to read. Two shapes would mean the most
        common failure is the one that reads worst.

        The field name is kept in front of the message. "body.slug: Invalid slug"
        says where to look; the sentence alone does not.
        """
        parts = []
        for err in exc.errors():
            msg = err.get("msg", "")
            # Pydantic prefixes its own text onto a ValueError raised in a
            # validator; the sentence underneath is the one worth reading.
            msg = msg.removeprefix("Value error, ")
            # A decode failure has no field to point at -- its `loc` is
            # ("body", 0), and rendering that gave "0: JSON decode error",
            # which names a character offset as though it were a field name.
            if err.get("type") == "json_invalid":
                parts.append("request body is not valid JSON")
                continue
            where = ".".join(str(x) for x in err.get("loc", ()) if x != "body")
            parts.append("%s: %s" % (where, msg) if where else msg)
        return JSONResponse(
            {"error": "invalid_request", "detail": " | ".join(parts) or "malformed request body"},
            status_code=400,
        )

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
    async def provision(body: ProvisionRequest, request: Request):
        """Register the tenant, then ask Odoo to build its database.

        202, not 201: the row exists when this returns and the database does
        not. Answering 201 would tell the console the tenant is ready while a
        job is still installing three hundred modules.

        The slug and the reserved-name check now live on `ProvisionRequest`, so
        a malformed request is refused before this function is entered and the
        refusal carries the field name with it.
        """
        actor = getattr(request.state, "actor", "unknown")
        slug = body.slug

        payload = {
            "slug": slug,
            "display_name": body.display_name or slug,
            "db_name": body.db_name or slug,
            "plan_code": body.plan_code,
            "valid_until": body.valid_until,
            "insight_source_kind": body.insight_source_kind or "odoo",
            "contact_email": body.contact_email,
            "contact_phone": body.contact_phone,
            # THESE THREE WERE ARRIVING AND BEING DROPPED. Each has a column on
            # `tenant_registry.tenants`; the wizard has been sending all three
            # since it was written, and this service read four keys and discarded
            # the rest without a word. A tenant provisioned from the console
            # therefore had no CSM, no backup schedule and no feature flags, and
            # nothing anywhere said so.
            "csm_user_id": body.csm_user_id,
            "features": json.dumps(body.features) if body.features is not None else None,
            "backup_schedule_cron": body.backup_schedule_cron,
            "notes": body.notes,
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

        modules = body.modules or list(settings.provision_modules)

        # CREDENTIAL BOUNDARY. From here to the return statement, the password
        # exists in exactly three places: this local, the RPC argument, and the
        # response body. It MUST NOT reach registry.log_action (the audit detail
        # goes through _job_detail, which whitelists), any logger call, or any
        # metric label -- the action log is readable by every super-admin and
        # /metrics is served unsigned.
        admin_password = body.admin_password or _generate_admin_password()
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
    async def suspend(slug: str, request: Request, body: SuspendRequest | None = None):
        return _transition(
            slug, "suspended", "suspended_at", "suspend",
            getattr(request.state, "actor", "unknown"),
            {"reason": body.reason if body else None},
        )

    @router.post("/v1/tenants/{slug}/resume")
    async def resume(slug: str, request: Request):
        return _transition(
            slug, "active", "activated_at", "resume",
            getattr(request.state, "actor", "unknown"),
        )

    @router.post("/v1/tenants/{slug}/extend")
    async def extend(slug: str, body: ExtendRequest, request: Request):
        """Grant access time outside the invoice cycle.

        WHY THIS EXISTS AT ALL. Until now `valid_until` moved in exactly one
        way: an invoice was paid and `custom_athera_billing._grant_access_until`
        pushed it forward. An operator who had to give a client access without a
        payment -- a pilot, a goodwill week, an invoice under dispute -- had no
        button, and the only thing left within reach was to record a payment that
        never happened. The missing button did not prevent that action; it drove
        it into the ledger, where the damage is far more expensive than a row in
        the audit log.

        This is a control-plane action, not an accounting one, which is why it
        sits beside suspend/resume/archive rather than in the billing module. It
        moves one column, writes one audit row, and issues nothing.
        """
        actor = getattr(request.state, "actor", "unknown")
        try:
            tenant = registry.extend_validity(slug, body.days)
        except TenantNotFound:
            ACTIONS.labels("extend", "not_found").inc()
            return _not_found(slug)
        registry.log_action(
            slug, "extend", actor, "success",
            {"days": body.days, "reason": body.reason,
             "valid_until_after": str(tenant.get("valid_until"))},
        )
        ACTIONS.labels("extend", "success").inc()
        return tenant

    @router.delete("/v1/tenants/{slug}")
    async def archive(slug: str, request: Request, body: ArchiveRequest | None = None):
        return _transition(
            slug, "archived", "archived_at", "archive",
            getattr(request.state, "actor", "unknown"),
            {"retention_days": body.retention_days if body else 30},
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

    # -----------------------------------------------------------------
    # WRITING backups is not implemented here, and will not be.
    #
    # A backup is pg_dump plus the filestore. This container has neither the
    # binary nor a path to the filestore volume, both on purpose: a service that
    # could dump any tenant's database on request is not a convenience, it is a
    # target. `scripts/tenant-backup.sh` does the job correctly on the host today
    # -- database AND filestore, manifest, SHA256SUMS, retention pruning.
    #
    # WHY 501 AND NOT SIMPLY NO ROUTE. Three of the four write paths below had no
    # route at all, so `custom_super_admin` -- which has been calling them since
    # it was imported -- got a 404. A 404 tells the caller it typed the URL
    # wrong; it sends whoever reads the log hunting for a routing bug. 501 with
    # a body that names the real path answers the question instead. The reply
    # shape is identical across all four so one caller can read one contract.
    def _backup_not_implemented(action: str, detail: str) -> JSONResponse:
        ACTIONS.labels(action, "unimplemented").inc()
        return JSONResponse(
            {
                "error": "not_implemented",
                "detail": detail,
                "implemented_by": "scripts/tenant-backup.sh (host)",
            },
            status_code=501,
        )

    @router.post("/v1/tenants/{slug}/backups", status_code=501)
    async def run_backup(slug: str):
        return _backup_not_implemented(
            "backup",
            "Backups run from scripts/tenant-backup.sh on the host. This service "
            "has neither pg_dump nor the filestore, deliberately. "
            "Run: make tenant-backup TENANT=%s" % slug,
        )

    @router.post("/v1/tenants/{slug}/backups/restore", status_code=501)
    async def restore_backup(slug: str):
        return _backup_not_implemented(
            "restore",
            "Restore runs from scripts/tenant-restore.sh on the host, where the "
            "dump, the filestore and the SHA256SUMS all are. Restoring is also "
            "destructive in a way no unattended HTTP call should be: it replaces "
            "a live database. Run it deliberately, on the host, for tenant %r." % slug,
        )

    @router.post("/v1/backups/{backup_id}/replicate", status_code=501)
    async def replicate_backup(backup_id: int):
        return _backup_not_implemented(
            "replicate",
            "Replicating backup %d into another tenant is a restore into a "
            "different database, so it inherits restore's refusal for the same "
            "reason. Run it on the host, where the dump and the filestore "
            "are." % backup_id,
        )

    @router.post("/v1/backups/enforce-retention", status_code=501)
    async def enforce_retention():
        return _backup_not_implemented(
            "retention",
            "Retention is enforced by scripts/tenant-backup.sh --keep-days on the "
            "host, which is the only place that can see the backup files. This "
            "service can read the registry rows but cannot delete what they "
            "describe, and pruning rows for files that still exist would be worse "
            "than pruning nothing.",
        )

    app.include_router(router)
    logger.info(
        "orchestrator ready: registry=%s odoo=%s db=%s",
        bool(settings.registry_dsn), settings.odoo_url, settings.odoo_db,
    )
    return app
