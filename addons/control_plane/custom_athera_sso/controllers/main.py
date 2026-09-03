"""Brief 08 — the Odoo end of the ATHERA SSO handoff.

WHAT THIS DOES NOT DO. It does not authenticate anybody. The gateway did that, against Odoo's own
credentials, before the ticket existed. This controller's whole job is to prove the ticket is
genuine, unspent and meant for THIS database, and then to turn that into an ordinary Odoo session.

WHY `session.finalize()` AND NOT `session.uid = uid`. Setting the uid by hand produces a session
that works and cannot be revoked: Odoo compares `session_token` against the user's password hash on
every request, so a session without one survives a password change. `finalize()` computes it the
same way a normal login does, and rotates the session id. A session created any other way is a
credential nobody can take back.

MFA IS NOT BYPASSED. `auth_totp` is installed on these databases. If the user has a second factor,
this controller stops at the pre-session — exactly where Odoo's own `authenticate()` stops — and
hands over to Odoo's MFA flow. An SSO door that skipped it would quietly delete a control the user
deliberately turned on.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from odoo import SUPERUSER_ID, http
from odoo.http import request

_logger = logging.getLogger(__name__)

#: Where the gateway lives from inside the compose network. A service name, never the public
#: hostname: this call must not leave the host, and it must not depend on the edge being healthy.
DEFAULT_GATEWAY = "http://login-gateway:8080"

EXCHANGE_TIMEOUT = 5


def _gateway_url():
    return (
        request.env["ir.config_parameter"]
        .sudo()
        .get_param("athera.sso.gateway_url", DEFAULT_GATEWAY)
        .rstrip("/")
    )


def _exchange(ticket):
    """Spend the ticket at the gateway. Returns the payload, or raises."""
    body = json.dumps({"ticket": ticket}).encode("utf-8")
    req = urllib.request.Request(
        _gateway_url() + "/auth/sso/exchange",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=EXCHANGE_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _refuse(message, status=403):
    return request.make_response(
        "<!doctype html><meta charset=utf-8><title>Akses ditolak</title>"
        "<p style='font:14px system-ui;margin:3rem'>%s</p>" % message,
        headers=[("Content-Type", "text/html; charset=utf-8")],
        status=status,
    )


class AtheraSso(http.Controller):

    @http.route("/athera/sso", type="http", auth="none", methods=["GET"], csrf=False, sitemap=False)
    def sso(self, ticket=None, next="/odoo", **_kw):
        if not ticket:
            return _refuse("Tiket SSO tidak ada.", 400)

        # `next` is a path on this host and never an absolute URL. A redirector that accepts one is
        # an open redirect wearing an SSO costume; the gateway already refuses it on its side, and
        # this side refuses it again because neither side should be the only one checking.
        if not next.startswith("/") or next.startswith("//"):
            next = "/odoo"

        try:
            payload = _exchange(ticket)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            _logger.info("athera sso: exchange refused (%s)", exc.code)
            if exc.code == 402:
                return _refuse(
                    "Langganan atau paket Anda tidak mencakup Odoo. "
                    "Hubungi tim ATHERA.", 402
                )
            return _refuse("Tiket SSO tidak berlaku atau sudah dipakai.", 401)
        except Exception:  # noqa: BLE001 - upstream trouble is not the visitor's fault
            _logger.exception("athera sso: exchange failed")
            return _refuse("Layanan masuk sedang tidak tersedia.", 503)

        db = payload.get("db")
        uid = int(payload.get("odoo_uid") or 0)

        # THE TICKET AND THE HOST MUST AGREE. Odoo picked this database from the Host header; the
        # ticket names the database it was minted for. A mismatch is not something to normalise
        # into whichever one looks more convenient -- it is a ticket being replayed against another
        # tenant, and it is refused.
        if db != request.db:
            _logger.warning("athera sso: ticket for %r presented on %r", db, request.db)
            return _refuse("Tiket ini bukan untuk basis data ini.", 403)

        env = request.env(user=SUPERUSER_ID)
        user = env["res.users"].browse(uid).exists()
        if not user or not user.active:
            return _refuse("Pengguna tidak ditemukan pada basis data ini.", 403)

        request.session.uid = None
        request.session["pre_login"] = user.login
        request.session["pre_uid"] = user.id

        if user._mfa_url():
            # Stop at the pre-session and let Odoo run its own second-factor flow, exactly as
            # `Session.authenticate` does. Finalising here would delete the user's 2FA.
            _logger.info("athera sso: handing over to MFA for uid=%s db=%s", uid, db)
            return request.redirect(user._mfa_url())

        request.session.finalize(env)
        _logger.info("athera sso: session established uid=%s db=%s", uid, db)

        response = request.redirect(next)
        route_token = payload.get("route_token")
        if route_token:
            # Host-scoped, httpOnly, and it carries a database name rather than an identity. The
            # edge verifies its signature on every request; a visitor editing it gets a signature
            # failure, not a different tenant.
            response.set_cookie(
                payload.get("route_cookie_name") or "athera_route",
                route_token,
                httponly=True,
                secure=True,
                samesite="Lax",
                max_age=43200,
                path="/",
            )
        return response
