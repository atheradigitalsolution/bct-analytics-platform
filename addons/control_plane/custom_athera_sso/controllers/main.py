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
import secrets
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
            # LOUD, like the database-mismatch branch above it. This branch used to refuse in
            # complete silence, and that silence cost a day: the suite reported a 403 with no
            # trace anywhere on the Odoo side, so the failure looked like a broken SSO door when
            # the real cause was a ticket naming a uid that had been removed from this database.
            # A refusal nobody can explain from the logs is a refusal that gets debugged twice.
            #
            # NOTHING REUSABLE IS WRITTEN. The uid is an integer and the database name is already
            # in the sibling line; the ticket, the route token and the exchange payload are not
            # logged here and must not be - a credential in a log is the defect we are separately
            # tracking, not one to add to.
            _logger.warning(
                "athera sso: refusing handoff, uid=%s is %s on %r",
                uid, "inactive" if user else "absent", request.db,
            )
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


# ---------------------------------------------------------------------------
# Reset password — the two calls the gateway is allowed to make
#
# WHY THE GATEWAY CANNOT JUST DO THIS ITSELF. Setting a password means holding a credential with
# write access to `res.users` in every tenant database. The gateway deliberately holds none: it
# only ever calls `common.authenticate(db, login, password)` with the visitor's own password and
# then acts as that uid. Giving it a standing admin credential to support one feature would make
# it a single credential that can take over any account in any tenant — the same trade that was
# refused when the orchestrator was denied `pg_dump`.
#
# So the split is: the gateway knows WHO is asking and can send email; Odoo owns the token and
# owns the password write. Neither side can complete a reset alone.
#
# WHY ODOO DOES NOT SEND THE EMAIL. `_action_reset_password()` generates the token and mails it in
# one call, which would need an `ir_mail_server` inside every CLIENT database — and that row holds
# the ATHERA relay credential, readable by any client administrator, usable to send mail as us.
# These endpoints return the token instead and let the gateway, which is our own infrastructure,
# do the sending.
#
# THE TOKEN IS ODOO'S, NOT OURS. `_generate_signup_token()` is signed, stateless, expires on
# `auth_signup.reset_password.validity.hours` (4 by default) and is invalidated the moment the
# user logs in, because the last login date is part of the signed payload. Reimplementing any of
# that here would mean a second password-reset token format to get wrong.
#
# FAIL-CLOSED ON AN UNSET SECRET. `athera.sso.reset_secret` absent or empty disables both routes.
# A deployment that has not configured the secret does not get an open password-reset API; it gets
# no password-reset API.
# ---------------------------------------------------------------------------

RESET_SECRET_PARAM = "athera.sso.reset_secret"


def _reset_authorised():
    """True only when the caller presented the configured shared secret.

    Compared with `compare_digest`, not `==`: this runs on an unauthenticated route and a
    short-circuiting comparison leaks the secret one byte at a time to anyone willing to measure.
    """
    secret = (
        request.env["ir.config_parameter"].sudo().get_param(RESET_SECRET_PARAM, "") or ""
    )
    if not secret:
        _logger.warning(
            "athera reset: %s is not set; the reset endpoints are disabled", RESET_SECRET_PARAM
        )
        return False
    presented = request.httprequest.headers.get("X-Athera-Reset-Secret", "") or ""
    return secrets.compare_digest(presented, secret)


class AtheraSsoReset(http.Controller):

    @http.route(
        "/athera/sso/reset/token",
        type="jsonrpc",
        auth="none",
        methods=["POST"],
        csrf=False,
        sitemap=False,
    )
    def reset_token(self, login=None, **_kw):
        """Mint a reset token for `login`, or report that there is nothing to mint.

        `{"token": null}` is returned both for an unknown login and for an account with no email
        address, and the caller cannot tell those apart. It is not a secrecy control by itself —
        the gateway is trusted, it holds the shared secret — it is so that the gateway has exactly
        one branch to write and cannot accidentally render a different page for the two cases.
        """
        if not _reset_authorised():
            return {"error": "unauthorised"}

        login = (login or "").strip()
        if not login:
            return {"token": None}

        env = request.env(user=SUPERUSER_ID)
        user = env["res.users"].sudo().search(
            [("login", "=", login), ("active", "=", True)], limit=1
        )
        if not user or not user.email:
            # Logged without the address: an audit line that quotes the address a stranger typed
            # turns the log into the enumeration oracle the response refuses to be.
            _logger.info("athera reset: no resettable account for the requested login")
            return {"token": None}

        partner = user.partner_id.sudo()
        partner.signup_prepare(signup_type="reset")
        token = partner._generate_signup_token()
        _logger.info("athera reset: token issued for user <%s>", user.login)
        return {"token": token, "email": user.email, "name": user.name}

    @http.route(
        "/athera/sso/reset/complete",
        type="jsonrpc",
        auth="none",
        methods=["POST"],
        csrf=False,
        sitemap=False,
    )
    def reset_complete(self, token=None, password=None, **_kw):
        """Spend the token and set the new password. Odoo validates; we only relay.

        `signup()` is Odoo's own entry point: it re-verifies the signature and the expiry, clears
        `signup_type` so the token cannot be spent twice, and writes the password through the
        ordinary `res.users` path that hashes it. None of those steps is reimplemented here, and
        that is the point.
        """
        if not _reset_authorised():
            return {"ok": False, "error": "unauthorised"}

        token = (token or "").strip()
        password = password or ""
        if not token or not password:
            return {"ok": False, "error": "invalid_request"}
        if len(password) < 8:
            # A floor, not a policy. Odoo has no minimum of its own here, and a reset flow that
            # accepts "1" is a downgrade of whatever the account had before.
            return {"ok": False, "error": "password_too_short"}

        env = request.env(user=SUPERUSER_ID)
        try:
            env["res.users"].sudo().signup({"password": password}, token)
            env.cr.commit()
        except Exception:  # noqa: BLE001
            # The exception text distinguishes "expired" from "already used" from "forged", and
            # the caller is not told which. It is recorded here, without the token, because the
            # operator debugging a failed reset needs it and the visitor does not.
            _logger.warning("athera reset: token refused", exc_info=True)
            return {"ok": False, "error": "invalid_or_expired"}

        _logger.info("athera reset: password set from a valid reset token")
        return {"ok": True}
