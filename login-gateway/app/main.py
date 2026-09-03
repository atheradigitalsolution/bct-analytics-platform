"""The login gateway — Odoo credential in, contract 02 session out.

Responsibilities, and nothing beyond them:

* authenticate against Odoo over JSON-RPC (``common.authenticate``);
* read the user's company and Operating Unit entitlement;
* mint the RS256 access token of frozen contract 02;
* publish the **public** halves of two signing keys at ``/.well-known/jwks.json`` (finding T-4);
* hand out and rotate an opaque refresh token in an httpOnly cookie.

It never queries the warehouse, never sees a metric, and never holds a database credential for
anything but Odoo's JSON-RPC. The signing keys live here and nowhere else: verifiers hold public
material only, which is the property that makes a key rotation a config change instead of a
redeployment of every consumer.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import urllib.parse
import threading
import time

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest
from pydantic import BaseModel, Field

from .config import settings_from_env
from .keys import load_key_ring
from . import sso as sso_mod
from . import webui
from .odoo import AuthenticationFailed, OdooClient, OdooError, read_session_claims
from .ratelimit import RateLimiter
from .registry import Registry
from .tokens import mint_access_token, mint_refresh_token

_logger = logging.getLogger("login_gateway")

AUTH_TOTAL = Counter(
    "bct_gateway_auth_total", "Authentication attempts by outcome.", ["result"]
)
TOKENS_ISSUED = Counter(
    "bct_gateway_token_issued_total", "Access tokens issued.", ["tenant"]
)
JWKS_KEYS = Gauge(
    "bct_gateway_jwks_keys",
    "Number of keys published in JWKS. Two is the floor: a single-key JWKS cannot be rotated "
    "without a flag-day outage (security finding T-4).",
)


class LoginRequest(BaseModel):
    db: str = Field(min_length=1, max_length=63)
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class TicketExchange(BaseModel):
    """Body of the ticket exchange.

    Defined at module level and not inside `create_app` on purpose: this module uses
    `from __future__ import annotations`, so FastAPI resolves the annotation by name against the
    MODULE namespace. A model nested in a function is invisible there, and FastAPI quietly falls
    back to reading `payload` as a query parameter — the exchange then answers 422 for every
    correct request. Measured, not guessed.
    """

    ticket: str = Field(min_length=16, max_length=4096)


class RefreshStore:
    """Server-side refresh state, so that logout actually revokes.

    In-process for the same reason the rate limiter is: one replica, one port. Replicating the
    gateway means moving this to shared storage, and that is written down here rather than
    discovered when the second replica starts handing out 401s.
    """

    def __init__(self) -> None:
        self._tokens = {}
        self._lock = threading.Lock()

    def issue(self, tenant: str, uid: int, ttl: int) -> str:
        token = mint_refresh_token()
        with self._lock:
            self._tokens[token] = {
                "tenant": tenant,
                "uid": uid,
                "expires": time.time() + ttl,
            }
        return token

    def consume(self, token: str):
        """Single-use: a refresh token is invalidated as it is redeemed.

        Rotation on every refresh means a stolen-and-replayed token collides with the legitimate
        client's next refresh, so the theft surfaces as a failed session rather than as a quiet
        parallel session that lasts forever.
        """
        with self._lock:
            record = self._tokens.pop(token, None)
        if record is None or record["expires"] < time.time():
            return None
        return record

    def revoke(self, token: str) -> None:
        with self._lock:
            self._tokens.pop(token, None)

    def purge(self) -> None:
        now = time.time()
        with self._lock:
            for token in [t for t, r in self._tokens.items() if r["expires"] < now]:
                del self._tokens[token]


def create_app(settings=None) -> FastAPI:
    settings = settings or settings_from_env()
    ring = load_key_ring(settings)
    JWKS_KEYS.set(len(ring.keys))

    odoo = OdooClient(settings.odoo_url)
    limiter = RateLimiter(
        settings.rate_limit_max_attempts,
        settings.rate_limit_window_seconds,
        settings.rate_limit_lockout_seconds,
    )
    store = RefreshStore()
    # One instance, created at app build time so the WARNING about a missing
    # control plane is emitted once at boot rather than on every login.
    registry = Registry(settings.registry_dsn, settings.registry_cache_ttl)
    spent_tickets = sso_mod.SpentTickets()
    # Credentials are held only for the lifetime of a refresh chain, never logged and never
    # returned. They are needed because Odoo's execute_kw authenticates every call.
    sessions = {}
    sessions_lock = threading.Lock()

    app = FastAPI(title="ATHERA login gateway", docs_url=None, redoc_url=None, openapi_url=None)
    router = APIRouter()

    def _audit(event: str, **fields) -> None:
        """Structured audit line. Never carries a credential, a token, or a personal value."""
        _logger.info(
            "audit %s %s",
            event,
            " ".join("%s=%s" % (k, v) for k, v in sorted(fields.items())),
        )

    @router.get("/healthz")
    def healthz():
        return {"status": "ok", "keys": len(ring.keys), "active_kid": ring.active_kid}

    @router.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @router.get("/.well-known/jwks.json")
    def jwks():
        """Public keys only. Two of them, always (finding T-4)."""
        return JSONResponse(
            ring.jwks(),
            headers={"Cache-Control": "public, max-age=300"},
        )

    def _set_refresh_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            settings.refresh_cookie_name,
            token,
            max_age=settings.refresh_token_ttl,
            httponly=True,        # unreadable from JavaScript, so XSS cannot exfiltrate it
            secure=settings.cookie_secure,
            samesite="strict",    # not sent on cross-site requests, so CSRF cannot spend it
            path="/auth",         # narrowest path that still covers refresh and logout
        )

    def _issue(response: Response, tenant: str, uid: int, claims: dict, password: str) -> dict:
        # The control-plane lookup happens on EVERY issue, which means on every
        # refresh as well as on login. That is deliberate: a subscription that
        # lapses mid-session must stop the next refresh, not merely the next
        # login, or a client with a long-lived refresh chain never notices.
        ent = registry.lookup(tenant)
        claims = dict(claims)
        claims["subscription_active"] = ent.active
        claims["products"] = ent.products
        token, expires = mint_access_token(settings, ring, tenant, uid, claims)
        refresh = store.issue(tenant, uid, settings.refresh_token_ttl)
        with sessions_lock:
            sessions[refresh] = password
        _set_refresh_cookie(response, refresh)
        TOKENS_ISSUED.labels(tenant=tenant).inc()
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": settings.access_token_ttl,
            "expires_at": dt.datetime.fromtimestamp(expires, dt.timezone.utc).isoformat(),
            "kid": ring.active_kid,
            "tenant_id": tenant,
            "roles": claims["roles"],
            "allowed_ou": claims["allowed_ou"],
            "all_ou": claims["all_ou"],
            # Mirrored into the response body as well as the token so the
            # portal can branch before it has decoded anything.
            "is_super_admin": bool(claims.get("is_super_admin", False)),
            "subscription_active": ent.active,
            "products": list(ent.products),
        }

    #: Longest form body worth reading on an unauthenticated endpoint. Three short fields and a
    #: token; anything larger is not a login attempt, and reading it would be work an anonymous
    #: caller gets to ask for.
    MAX_FORM_BYTES = 8192
    CSRF_COOKIE = "athera_login_csrf"

    def _safe_path(value: str, fallback: str) -> str:
        """A path on this site, never an absolute URL. `//host` is absolute to a browser even
        though it starts with a slash, which is the case a naive startswith('/') lets through."""
        return value if value.startswith("/") and not value.startswith("//") else fallback

    def _set_csrf_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            CSRF_COOKIE, token, max_age=600, httponly=True, secure=settings.cookie_secure,
            samesite="strict", path="/auth",
        )

    def _authenticate(db: str, login_name: str, password: str, client_ip: str):
        """The single login path. Returns (uid, claims, None) or (None, None, code).

        Both surfaces -- the JSON API and the browser form -- come through here, so the allow-list,
        the rate limiter, the audit record and the deliberate sameness of every refusal cannot
        drift apart between them. A second copy of this logic is how one surface quietly ends up
        without a lockout.
        """
        account_key = "account:%s:%s" % (db, login_name)
        source_key = "source:%s" % client_ip

        for key in (account_key, source_key):
            remaining = limiter.is_locked(key)
            if remaining:
                AUTH_TOTAL.labels(result="ratelimited").inc()
                _audit("login.ratelimited", db=db, source=client_ip)
                return None, None, ("rate_limited", int(remaining) + 1)

        if db not in settings.allowed_databases:
            # Same answer as bad credentials: whether a database exists is not something an
            # unauthenticated caller gets to enumerate.
            limiter.record_failure(source_key)
            AUTH_TOTAL.labels(result="invalid").inc()
            _audit("login.failed", db=db, source=client_ip, reason="database")
            return None, None, ("invalid", 0)

        try:
            uid = odoo.authenticate(db, login_name, password)
        except AuthenticationFailed:
            limiter.record_failure(account_key)
            limiter.record_failure(source_key)
            AUTH_TOTAL.labels(result="invalid").inc()
            _audit("login.failed", db=db, source=client_ip, reason="credentials")
            return None, None, ("invalid", 0)
        except OdooError as exc:
            AUTH_TOTAL.labels(result="upstream_error").inc()
            _logger.error("login upstream failure: %s", exc)
            return None, None, ("upstream", 0)

        try:
            claims = read_session_claims(odoo, db, uid, password)
        except OdooError as exc:
            AUTH_TOTAL.labels(result="upstream_error").inc()
            _logger.error("entitlement read failed: %s", exc)
            return None, None, ("upstream", 0)

        limiter.record_success(account_key)
        AUTH_TOTAL.labels(result="success").inc()
        _audit("login.success", db=db, uid=uid, source=client_ip,
               roles=",".join(claims["roles"]), all_ou=claims["all_ou"])
        return uid, claims, None

    @router.get("/auth/login")
    def login_form_page(next: str = "/auth/sso/odoo", db: str = ""):
        """The browser's way in. See app/webui.py for why the gateway has a page at all."""
        csrf = secrets.token_urlsafe(24)
        page = webui.login_page(_safe_path(next, "/auth/sso/odoo"), db[:64], csrf)
        response = HTMLResponse(page)
        _set_csrf_cookie(response, csrf)
        return response

    def _login_form_failed(next_path: str, db: str, message: str, status: int):
        """A refusal re-renders the form, and does it under the status code the failure deserves.

        401 and not 200: the fail2ban jail reads Caddy's access log for a failed login, and a
        refusal that reports itself as success is a refusal the jail cannot count.
        """
        csrf = secrets.token_urlsafe(24)
        response = HTMLResponse(
            webui.login_page(next_path, db, csrf, message), status_code=status
        )
        _set_csrf_cookie(response, csrf)
        return response

    @router.post("/auth/login/form")
    async def login_form(request: Request):
        length = int(request.headers.get("content-length") or 0)
        if length > MAX_FORM_BYTES:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        raw = await request.body()
        if len(raw) > MAX_FORM_BYTES:
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        fields = urllib.parse.parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        client_ip = request.client.host if request.client else "unknown"
        cookie_csrf = request.cookies.get(CSRF_COOKIE) or ""

        def one(name, limit=1024):
            return ((fields.get(name) or [""])[0])[:limit]

        # Authentication is blocking (XML-RPC to Odoo), and this handler is async so it can read
        # the body. Running it inline would block the event loop for every other request for the
        # length of an Odoo round trip.
        return await run_in_threadpool(
            _handle_login_form, one("db", 64), one("login", 320), one("password", 1024),
            one("next", 2048), one("csrf", 256), cookie_csrf, client_ip,
        )

    def _handle_login_form(db, login_name, password, next_value, form_csrf, cookie_csrf, client_ip):
        next_path = _safe_path(next_value, "/auth/sso/odoo")

        # Double submit. Without it, a third-party page can POST this form and land the visitor in
        # an ATTACKER'S session -- and this session is the one that opens the Odoo door, so a
        # login CSRF here is not a curiosity.
        if not cookie_csrf or not secrets.compare_digest(form_csrf, cookie_csrf):
            _audit("login.csrf_rejected", db=db, source=client_ip)
            return _login_form_failed(next_path, db, webui.EXPIRED, 400)

        if not db or not login_name or not password:
            return _login_form_failed(next_path, db, webui.INVALID, 401)

        uid, claims, error = _authenticate(db, login_name, password, client_ip)
        if error is not None:
            kind, retry = error
            if kind == "rate_limited":
                response = _login_form_failed(next_path, db, webui.RATE_LIMITED, 429)
                response.headers["Retry-After"] = str(retry)
                return response
            if kind == "upstream":
                return _login_form_failed(next_path, db, webui.UPSTREAM, 503)
            return _login_form_failed(next_path, db, webui.INVALID, 401)

        response = RedirectResponse(next_path, status_code=303)
        # _issue sets the refresh cookie on whatever response is actually returned, which is the
        # whole point of this surface: the cookie finally lands on the gateway's own host.
        _issue(response, db, uid, claims, password)
        response.delete_cookie(CSRF_COOKIE, path="/auth")
        return response

    @router.post("/auth/login")
    def login(payload: LoginRequest, request: Request, response: Response):
        """The JSON API. Identical policy to the browser form, because both call _authenticate."""
        client_ip = request.client.host if request.client else "unknown"
        uid, claims, error = _authenticate(payload.db, payload.login, payload.password, client_ip)
        if error is not None:
            kind, retry = error
            if kind == "rate_limited":
                return JSONResponse(
                    {"error": "rate_limited",
                     "detail": "Too many authentication attempts. Try again later."},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )
            if kind == "upstream":
                return JSONResponse(
                    {"error": "upstream_unavailable",
                     "detail": "Authentication backend unavailable."},
                    status_code=503,
                )
            return _invalid()
        return _issue(response, payload.db, uid, claims, payload.password)

    @router.post("/auth/refresh")
    def refresh(request: Request, response: Response):
        token = request.cookies.get(settings.refresh_cookie_name)
        if not token:
            return JSONResponse(
                {"error": "no_refresh_token", "detail": "No refresh cookie present."},
                status_code=401,
            )
        record = store.consume(token)
        with sessions_lock:
            password = sessions.pop(token, None)
        if record is None or password is None:
            _audit("refresh.rejected")
            return JSONResponse(
                {"error": "invalid_refresh_token", "detail": "Refresh token is not valid."},
                status_code=401,
            )
        try:
            # Re-read entitlements on every refresh rather than copying the old claims forward.
            # An access token lasts an hour; a session lasts two weeks. Copying claims would mean a
            # revoked Operating Unit or a removed role stayed effective for the whole session.
            claims = read_session_claims(odoo, record["tenant"], record["uid"], password)
        except OdooError:
            return JSONResponse(
                {"error": "upstream_unavailable", "detail": "Authentication backend unavailable."},
                status_code=503,
            )
        _audit("refresh.success", db=record["tenant"], uid=record["uid"])
        return _issue(response, record["tenant"], record["uid"], claims, password)

    @router.post("/auth/logout")
    def logout(request: Request, response: Response):
        token = request.cookies.get(settings.refresh_cookie_name)
        if token:
            store.revoke(token)
            with sessions_lock:
                sessions.pop(token, None)
        response.delete_cookie(
            settings.refresh_cookie_name, path="/auth",
            httponly=True, secure=settings.cookie_secure, samesite="strict",
        )
        _audit("logout")
        return {"status": "logged_out"}


    # ---------------------------------------------------------------------------------
    # Brief 08 — SSO into Odoo.
    #
    # These live under /auth/sso/ and not /sso/ for one concrete reason: the refresh cookie is set
    # with `path=/auth`, so a handler outside that path would never receive it and the handoff
    # could not identify anyone. `SameSite=Strict` is not a problem here — odoo.<domain> and
    # auth.<domain> are the same *site*, so a navigation between them still carries the cookie.
    # ---------------------------------------------------------------------------------

    ODOO_PRODUCT_REFUSAL = {
        "error": "product_not_entitled",
        "detail": "This tenant's plan does not include Odoo.",
    }
    SUBSCRIPTION_REFUSAL = {
        "error": "subscription_inactive",
        "detail": "This tenant's subscription is not active.",
    }

    def _wants_html(request: Request) -> bool:
        """A person, as opposed to the portal or a script. Only the presentation branches on this;
        every authorisation decision is the same either way."""
        return "text/html" in (request.headers.get("accept") or "")

    def _login_redirect(inner_next: str):
        """Send the browser to the gateway's own login page, remembering where it was going.

        The absolute base comes from configuration and not from the request: behind two proxies the
        Host that arrives here is the ODOO host, so building this from {host} would send people to
        a login page that does not exist there.
        """
        target = "%s/auth/login?next=%s" % (
            settings.public_base, urllib.parse.quote(inner_next, safe=""),
        )
        return RedirectResponse(target, status_code=303)

    def _sso_refusal(ent):
        """402 either way; the body says which of the two happened. Never 403: the person is
        authenticated and is who they say they are, exactly as contract 07 sets out."""
        body = SUBSCRIPTION_REFUSAL if not ent.active else ODOO_PRODUCT_REFUSAL
        return JSONResponse(body, status_code=402)

    @router.get("/auth/sso/odoo")
    def sso_odoo(request: Request, response: Response, next: str = "/odoo"):
        safe_next = _safe_path(next, "/odoo")
        token = request.cookies.get(settings.refresh_cookie_name)
        if not token:
            # No ATHERA session on this host yet. A person gets the login page; anything speaking
            # JSON keeps the status code it can act on.
            if _wants_html(request):
                return _login_redirect(
                    "/auth/sso/odoo?next=" + urllib.parse.quote(safe_next, safe="")
                )
            return JSONResponse(
                {"error": "no_refresh_token", "detail": "No refresh cookie present."},
                status_code=401,
            )
        record = store.consume(token)
        with sessions_lock:
            password = sessions.pop(token, None)
        if record is None or password is None:
            _audit("sso.rejected")
            return JSONResponse(
                {"error": "invalid_refresh_token", "detail": "Refresh token is not valid."},
                status_code=401,
            )
        try:
            claims = read_session_claims(odoo, record["tenant"], record["uid"], password)
        except OdooError:
            return JSONResponse(
                {"error": "upstream_unavailable", "detail": "Authentication backend unavailable."},
                status_code=503,
            )

        tenant, uid = record["tenant"], record["uid"]
        ent = registry.lookup(tenant)

        # The refresh chain is rotated whether or not the gate opens. Leaving the consumed token
        # unreplaced on a refusal would log the visitor out of the portal as a side effect of being
        # told their plan does not include Odoo.
        refresh = store.issue(tenant, uid, settings.refresh_token_ttl)
        with sessions_lock:
            sessions[refresh] = password

        # The cookie is set on the response that is actually returned. FastAPI only merges the
        # injected `response` when the handler returns a plain value; returning a Response object
        # discards it, and the visitor would be silently logged out of the portal by visiting the
        # Odoo door. Measured, not assumed.
        if not sso_mod.entitled_to_odoo(claims, ent):
            _audit("sso.refused", db=tenant, uid=uid, active=ent.active)
            refusal = _sso_refusal(ent)
            _set_refresh_cookie(refusal, refresh)
            return refusal

        ticket = sso_mod.mint_ticket(
            settings, ring, tenant, uid, bool(claims.get("is_super_admin", False))
        )
        # `next` was validated on the way in: a path on the Odoo host and never an absolute URL,
        # because a redirector that accepts one is an open redirect wearing an SSO costume.
        target = "%s/athera/sso?ticket=%s&next=%s" % (
            settings.odoo_sso_base, ticket, urllib.parse.quote(safe_next, safe=""),
        )
        _audit("sso.issued", db=tenant, uid=uid, super_admin=bool(claims.get("is_super_admin")))
        redirect = RedirectResponse(target, status_code=303)
        _set_refresh_cookie(redirect, refresh)
        return redirect

    @router.post("/auth/sso/exchange")
    def sso_exchange(payload: TicketExchange):
        """Server-to-server, called by the Odoo module. Single use is enforced HERE."""
        try:
            claims = sso_mod.verify_ticket(settings, ring, payload.ticket)
        except Exception as exc:  # noqa: BLE001 - reason is logged, never returned
            _audit("sso.ticket_invalid")
            _logger.info("sso ticket rejected: %s", exc)
            return JSONResponse(
                {"error": "invalid_ticket", "detail": "Ticket is not valid."}, status_code=401
            )
        if not spent_tickets.spend(claims["jti"], int(claims["exp"])):
            _audit("sso.ticket_replayed", db=claims.get("db"))
            return JSONResponse(
                {"error": "ticket_spent", "detail": "Ticket has already been used."},
                status_code=401,
            )

        db, uid = claims["db"], int(claims["odoo_uid"])
        ent = registry.lookup(db)
        # Re-checked at exchange as well as at issue. A ticket is short-lived but not
        # instantaneous, and the door it opens lasts a whole visit.
        is_super = bool(claims.get("sa", False))
        if not sso_mod.entitled_to_odoo({"is_super_admin": is_super}, ent):
            _audit("sso.exchange_refused", db=db, uid=uid)
            return _sso_refusal(ent)

        _audit("sso.exchanged", db=db, uid=uid)
        return {
            "db": db,
            "odoo_uid": uid,
            "route_token": sso_mod.mint_route_token(settings, ring, db, uid, is_super),
            "route_cookie_name": settings.route_cookie_name,
        }

    @router.get("/auth/sso/route")
    def sso_route(request: Request):
        """Caddy's `forward_auth` target. Answers ONE question: which database is this request for?

        Runs on every request to the Odoo host, which is what makes revocation nearly immediate:
        the entitlement is re-read here, behind the registry's own short cache, rather than being
        trusted for the lifetime of a session.
        """
        token = request.cookies.get(settings.route_cookie_name)
        if token:
            try:
                claims = sso_mod.verify_route_token(settings, ring, token)
            except Exception:  # noqa: BLE001
                # Expiry lands here too, and after ROUTE_TTL that is the ordinary case rather than
                # an attack. A person is sent back through the handoff; a forged token takes the
                # same path and gets no further, because the door is still the gateway.
                if _wants_html(request):
                    return _login_redirect(
                        "/auth/sso/odoo?next=" + urllib.parse.quote(
                            _safe_path(request.headers.get("x-forwarded-uri", "/odoo"), "/odoo"),
                            safe="",
                        )
                    )
                return JSONResponse(
                    {"error": "invalid_route", "detail": "Route token is not valid."},
                    status_code=401,
                )
            db, is_super = claims["db"], bool(claims.get("sa", False))
        else:
            # First hop of the handoff: no route cookie yet, the database is inside the ticket.
            # The ticket is only READ here, never spent — spending it is the exchange's job, and
            # doing it twice would make the handoff fail on its own first request.
            uri = request.headers.get("x-forwarded-uri", "")
            query = urllib.parse.urlparse(uri).query
            ticket = urllib.parse.parse_qs(query).get("ticket", [""])[0]
            if not ticket:
                # THE COLD ENTRY. Someone typed the Odoo hostname with no ATHERA session at all.
                # Before this existed the edge answered a bare JSON 401 and the door was unusable
                # by a human -- which is why the cutover waited for it.
                if _wants_html(request):
                    return _login_redirect(
                        "/auth/sso/odoo?next=" + urllib.parse.quote(
                            _safe_path(uri or "/odoo", "/odoo"), safe="",
                        )
                    )
                return JSONResponse(
                    {"error": "no_session", "detail": "No ATHERA session for the Odoo door."},
                    status_code=401,
                )
            try:
                claims = sso_mod.verify_ticket(settings, ring, ticket)
            except Exception:  # noqa: BLE001
                return JSONResponse(
                    {"error": "invalid_ticket", "detail": "Ticket is not valid."}, status_code=401
                )
            db, is_super = claims["db"], bool(claims.get("sa", False))

        ent = registry.lookup(db)
        if not sso_mod.entitled_to_odoo({"is_super_admin": is_super}, ent):
            return _sso_refusal(ent)
        return Response(status_code=204, headers={"X-Athera-Db": db})

    app.include_router(router)
    return app


def _invalid():
    """One response for every authentication failure.

    Deliberately identical whether the database is unknown, the login does not exist or the
    password is wrong. Distinguishing them turns the endpoint into an account and tenant
    enumeration oracle, which is the same reasoning as contract 02's 403 body not revealing
    whether the other tenant exists.
    """
    return JSONResponse(
        {"error": "invalid_credentials", "detail": "Authentication failed."},
        status_code=401,
    )


# Constant-time comparison helper kept adjacent to the auth path so it is found when needed.
compare_digest = secrets.compare_digest

app = None
