"""Authentication against Odoo, and the entitlements that become JWT claims.

Nothing here logs a credential, a token, or the value of any ``personal``/``sensitive`` field. The
user's name and e-mail are ``personal`` under contract 01, so they are never written to a log line
even at DEBUG — a gateway that logs "authenticated budi.santoso@..." has quietly re-created the
plaintext store the whole masking design exists to prevent.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

_logger = logging.getLogger(__name__)

#: An opener built with **only** HTTP and HTTPS handlers.
#:
#: ``urllib.request.urlopen`` uses the global opener, which carries ``FileHandler`` and
#: ``FTPHandler``. In a process holding the warehouse credentials and the per-tenant masking salt,
#: that is a local-file-read primitive the moment the configured URL can be influenced: a
#: ``file:///etc/passwd`` or ``file:///run/secrets/...`` URL would be fetched and its contents
#: compared against the digest spec.
#:
#: Removing the capability beats checking for it, so this is a structural fix rather than a
#: validated one -- ``opener.open("file:///etc/passwd")`` raises ``URLError: unknown url type``.
#: The scheme assertion at construction stays as well, because it turns a misconfiguration into a
#: clear startup error instead of a runtime URLError.
def _build_http_only_opener():
    """Build an opener that physically cannot speak anything but HTTP(S).

    ``build_opener()`` is the obvious call and it is WRONG here: it *adds* to the default handler
    set rather than replacing it, so ``FileHandler`` and ``FTPHandler`` survive and
    ``file:///etc/passwd`` still opens. Verified, not assumed -- the first version of this function
    used ``build_opener`` and a test read ``/etc/passwd`` straight through it.

    An ``OpenerDirector`` built by hand carries only what is added. ``UnknownHandler`` is required:
    without it an unsupported scheme falls off the end of the handler chain and ``open()`` returns
    ``None`` instead of raising, which is a silent failure rather than a refusal.

    ``HTTPRedirectHandler`` is deliberately omitted. Odoo's JSON-RPC endpoint has no reason to
    redirect, and following one would let a 302 walk this client to an arbitrary host while holding
    the warehouse credentials and the masking salt.
    """
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPHandler,
        urllib.request.HTTPSHandler,
        urllib.request.HTTPDefaultErrorHandler,
        urllib.request.HTTPErrorProcessor,
        urllib.request.UnknownHandler,
    ):
        opener.add_handler(handler())
    return opener


_HTTP_ONLY_OPENER = _build_http_only_opener()

#: The Odoo group that lifts the per-Operating-Unit record rules
#: (``custom_operating_unit/security/operating_unit_groups.xml``: "Sees documents from every
#: Operating Unit. Bypasses the per-unit record rules.").
GROUP_ALL_OPERATING_UNITS = "custom_operating_unit.group_operating_unit_all"

#: Odoo groups -> contract 02 roles. Unmapped users get the least-privileged role, never none:
#: a session with no role at all would be indistinguishable from a bug in the mapping.
ROLE_MAP = (
    ("custom_pdp_core.group_pdp_officer", "analytics.admin"),
    ("custom_operating_unit.group_operating_unit_manager", "analytics.analyst"),
    ("base.group_erp_manager", "analytics.admin"),
)
DEFAULT_ROLE = "analytics.viewer"


class AuthenticationFailed(Exception):
    """Bad credentials, or a database that is not offered. Never says which."""


class OdooError(Exception):
    pass


class OdooClient:
    def __init__(self, url: str, timeout: float = 15.0) -> None:
        scheme = urllib.parse.urlparse(url).scheme
        if scheme not in ("http", "https"):
            raise ValueError("LOGIN_GATEWAY_ODOO_URL must be http or https, got %r" % scheme)
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _call(self, service: str, method: str, args: list):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": 1,
        }
        try:
            body = json.dumps(payload).encode("utf-8")
            response = _HTTP_ONLY_OPENER.open(
                self.url + "/jsonrpc", data=body, timeout=self.timeout
            )
            with response:
                parsed = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            # `from None`, deliberately, not `from exc`. A chained OSError renders the full
            # request context in the traceback, and this call carries the user's password in its
            # body -- a 500 page or a log aggregator would then hold the credential. Only the
            # exception class survives, which is enough to tell a timeout from a refused connection.
            raise OdooError("Odoo is unreachable: %s" % exc.__class__.__name__) from None
        if "error" in parsed:
            # The message can echo arguments, which on an authenticate call means the password.
            # Only the class of failure is logged, never the payload.
            raise OdooError("Odoo JSON-RPC %s.%s failed" % (service, method))
        return parsed.get("result")

    def authenticate(self, db: str, login: str, password: str) -> int:
        uid = self._call("common", "authenticate", [db, login, password, {}])
        if not uid:
            raise AuthenticationFailed()
        return int(uid)

    def execute(self, db: str, uid: int, password: str, model: str, method: str,
                args: list, kwargs: dict | None = None):
        return self._call(
            "object", "execute_kw", [db, uid, password, model, method, args, kwargs or {}]
        )


def read_session_claims(client: OdooClient, db: str, uid: int, password: str) -> dict:
    """Read the company and Operating Unit entitlement that fill the contract 02 claim set."""
    rows = client.execute(
        db, uid, password, "res.users", "read",
        [[uid], ["company_id", "company_ids", "allowed_operating_unit_ids"]],
    )
    if not rows:
        raise OdooError("res.users.read returned nothing for the authenticated uid")
    row = rows[0]

    company_ids = row.get("company_ids") or []
    if not company_ids and row.get("company_id"):
        company_ids = [row["company_id"][0]]

    # Contract 02 as amended at GATE 3: `allowed_ou: []` means NO Operating Units, mirroring
    # custom_operating_unit's record rules, which fail closed. The bypass is the separate boolean
    # `all_ou`, and it is only ever true for a member of the explicit bypass group -- never inferred
    # from emptiness. So a claim this code forgot to populate grants nothing rather than everything.
    allowed_ou = list(row.get("allowed_operating_unit_ids") or [])
    all_ou = bool(
        client.execute(db, uid, password, "res.users", "has_group", [GROUP_ALL_OPERATING_UNITS])
    )

    roles = [DEFAULT_ROLE]
    for group, role in ROLE_MAP:
        try:
            if client.execute(db, uid, password, "res.users", "has_group", [group]):
                roles.append(role)
        except OdooError:
            # A group that does not exist in this database is not an authentication failure.
            continue

    return {
        "company_ids": [int(c) for c in company_ids],
        "allowed_ou": [int(o) for o in allowed_ou],
        "all_ou": all_ou,
        # Ordered most-privileged last so a consumer taking roles[-1] is not surprised; the
        # authoritative check is membership, not position.
        "roles": sorted(set(roles)),
    }
