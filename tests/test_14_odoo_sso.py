"""Brief 08 fase 2 — the SSO door into Odoo.

Every case here is about a ticket being refused, a route being refused, or a session being created
for exactly one database. The one success case exists so the refusals cannot pass by refusing
everything.

Tickets are minted locally with the gateway's own signing key rather than obtained by logging in.
That is not a shortcut around authentication: the step this file cannot perform (a real portal
login) is the step the gateway already covers, and minting is what lets each case vary exactly one
field -- an expired ticket, a ticket for another database, a forged route cookie.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse

import urllib.request

import jwt
import pytest

from helpers import env as envh
from helpers import tokens, web

pytestmark = [pytest.mark.live]

TICKET_AUDIENCE = "athera-odoo-sso"
ROUTE_AUDIENCE = "athera-odoo-route"

ODOO = "http://127.0.0.1:38069"
DEMO_UID = 5


def _iss():
    return envh.env("LOGIN_GATEWAY_JWT_ISSUER", "https://login-gateway.local/")


def _host(db):
    """The Host header Odoo picks its database from: `<db>.<domain>`, dbfilter is ^%d$.

    Read from the environment the containers were started with rather than spelled out, like every
    other host in this suite. Spelling it out passes on the machine it was written on and fails on
    any deployment with a different ATHERA_DOMAIN -- and it puts a deployment's real domain and
    tenant database name into a file that is meant to be portable.
    """
    return "%s.%s" % (db, envh.env("ATHERA_DOMAIN", "athera.localhost"))


def _mint(audience, db, uid, ttl=60, **overrides):
    now = int(time.time())
    payload = {
        "iss": _iss(),
        "aud": audience,
        "sub": "odoo:%s:%d" % (db, uid),
        "db": db,
        "odoo_uid": uid,
        "sa": False,
        "jti": "t-%d-%s" % (now, overrides.pop("nonce", db)),
        "iat": now,
        "exp": now + ttl,
    }
    payload.update(overrides)
    key = tokens.private_key_pem()
    if not key:
        pytest.skip("gateway signing key not readable from the host; NOT RUN")
    return jwt.encode(payload, key, algorithm="RS256")


def _exchange(ticket):
    return web.request(
        web.gateway_url("/auth/sso/exchange"), method="POST", payload={"ticket": ticket}
    )


def _route(cookie=None, forwarded_uri=None):
    headers = {}
    if cookie:
        headers["Cookie"] = "athera_route=%s" % cookie
    if forwarded_uri:
        headers["X-Forwarded-Uri"] = forwarded_uri
    return web.request(web.gateway_url("/auth/sso/route"), headers=headers)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The handoff IS a redirect, so following it hides the thing under test.

    `helpers.web.request` follows redirects like a browser, which is right for every other test in
    this suite and wrong here: it turned a 303 carrying two Set-Cookie headers into a 200 carrying
    a rendered page, and the assertion failed on code that was working.
    """

    def redirect_request(self, *_args, **_kwargs):
        return None


def _raw_get(url, headers):
    """Returns (status, headers, set_cookies, body).

    `set_cookies` is a LIST. `dict(response.headers)` keeps one value per name, and a login sets
    two cookies — so collapsing them to a dict silently drops `session_id` and makes a working
    handoff look like a broken one.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=30) as resp:
            return (resp.status, dict(resp.headers),
                    resp.headers.get_all("Set-Cookie") or [], resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return (exc.code, dict(exc.headers),
                exc.headers.get_all("Set-Cookie") or [], exc.read().decode("utf-8", "replace"))


def _odoo_sso(ticket, host=None, next_path="/odoo"):
    host = host or _host("bct")
    url = "%s/athera/sso?ticket=%s&next=%s" % (
        ODOO, urllib.parse.quote(ticket), urllib.parse.quote(next_path, safe="")
    )
    return web.request(url, headers={"Host": host, "X-Forwarded-Host": host})


# ---------------------------------------------------------------------------------------------
# The gateway side
# ---------------------------------------------------------------------------------------------


def test_a_valid_ticket_exchanges_once(evidence):
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="once")
    first = _exchange(ticket)
    evidence.add("first exchange", "%s %s" % (first.status, first.body[:160]))
    assert first.status == 200, first.body
    body = first.json()
    assert body["db"] == "bct" and body["odoo_uid"] == DEMO_UID
    assert body["route_token"]

    second = _exchange(ticket)
    evidence.add("replay of the same ticket", "%s %s" % (second.status, second.body))
    assert second.status == 401, second.body
    assert second.json()["error"] == "ticket_spent"


def test_an_expired_ticket_is_refused(evidence):
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, ttl=-30, nonce="expired")
    response = _exchange(ticket)
    evidence.add("expired ticket", "%s %s" % (response.status, response.body))
    assert response.status == 401, response.body


def test_an_access_token_cannot_be_replayed_as_a_ticket(evidence):
    """`aud` is checked exactly, so the portal's own token is not a key to this door."""
    response = _exchange(tokens.valid(tokens.claims(tenant="bct")))
    evidence.add("access token as ticket", "%s %s" % (response.status, response.body))
    assert response.status == 401, response.body


def test_route_refuses_a_forged_cookie(evidence):
    forged = jwt.encode(
        {"iss": _iss(), "aud": ROUTE_AUDIENCE, "db": "athera_admin", "sa": True,
         "exp": int(time.time()) + 600},
        "not-the-signing-key", algorithm="HS256",
    )
    response = _route(cookie=forged)
    evidence.add("forged route cookie", "%s %s" % (response.status, response.body))
    assert response.status == 401, response.body


def test_route_answers_with_the_database(evidence):
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="route")
    body = _exchange(ticket).json()
    response = _route(cookie=body["route_token"])
    evidence.add("route with a real token", "%s %s" % (response.status, response.headers))
    assert response.status == 204, response.body
    assert response.headers.get("x-athera-db") == "bct"


def test_route_reads_the_ticket_on_the_first_hop(evidence):
    """No route cookie exists yet on the handoff request, so the database comes from the ticket."""
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="firsthop")
    response = _route(forwarded_uri="/athera/sso?ticket=%s&next=%%2Fodoo" % ticket)
    evidence.add("first hop", "%s %s" % (response.status, response.headers))
    assert response.status == 204, response.body
    assert response.headers.get("x-athera-db") == "bct"


def test_route_without_anything_is_refused(evidence):
    response = _route()
    evidence.add("no cookie, no ticket", "%s %s" % (response.status, response.body))
    assert response.status == 401, response.body


# ---------------------------------------------------------------------------------------------
# The Odoo side
# ---------------------------------------------------------------------------------------------


def test_odoo_creates_a_session_from_a_ticket(evidence):
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="session")
    host = _host("bct")
    url = "%s/athera/sso?ticket=%s&next=%%2Fodoo" % (ODOO, urllib.parse.quote(ticket))
    status, headers, set_cookies, _body = _raw_get(url, {"Host": host, "X-Forwarded-Host": host})
    cookies = " | ".join(c.split(";")[0] for c in set_cookies)
    evidence.add("handoff into odoo", "%s -> %s | %s" % (status, headers.get("Location"), cookies[:200]))
    assert status in (302, 303), status
    assert (headers.get("Location") or "").endswith("/odoo")
    assert "session_id" in cookies, cookies
    assert "athera_route" in cookies, cookies


def test_a_ticket_for_another_database_is_refused(evidence):
    """The ticket names one database; the Host names another. That is a replay, not a preference."""
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="wrongdb")
    response = _odoo_sso(ticket, host=_host("athera_admin"))
    evidence.add("bct ticket on athera_admin", "%s %s" % (response.status, response.body[:200]))
    assert response.status == 403, response.body[:300]


def test_odoo_refuses_a_spent_ticket(evidence):
    ticket = _mint(TICKET_AUDIENCE, "bct", DEMO_UID, nonce="spent")
    assert _exchange(ticket).status == 200
    response = _odoo_sso(ticket)
    evidence.add("spent ticket at the odoo door", "%s" % response.status)
    assert response.status == 401, response.body[:300]


def test_a_tenant_without_the_odoo_product_is_refused_402(evidence):
    """`athera_admin` has no row in `tenant_registry.tenants`, so `is_active()` is false for it.

    That makes it the honest fixture for this case: no plan, no products, and a refusal that must
    be 402 rather than 403 — the ticket is genuine and the person is authenticated; what is missing
    is the entitlement.
    """
    ticket = _mint(TICKET_AUDIENCE, "athera_admin", 2, nonce="notentitled")
    response = _exchange(ticket)
    evidence.add("unentitled tenant", "%s %s" % (response.status, response.body))
    assert response.status == 402, response.body
    assert response.json()["error"] in ("subscription_inactive", "product_not_entitled")


def test_the_super_admin_bypass_opens_the_console(evidence):
    """Without this bypass the console database locks its own administrator out.

    `athera_admin` will never be active in the tenant registry — it is the control plane, not a
    customer. `hub-portal` already gates on `is_super_admin` for the same reason.
    """
    ticket = _mint(TICKET_AUDIENCE, "athera_admin", 2, sa=True, nonce="superadmin")
    response = _exchange(ticket)
    evidence.add("super admin on athera_admin", "%s %s" % (response.status, response.body[:160]))
    assert response.status == 200, response.body
    assert response.json()["db"] == "athera_admin"
