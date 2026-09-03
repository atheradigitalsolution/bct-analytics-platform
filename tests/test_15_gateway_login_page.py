"""Brief 08 — the gateway's own login page, and the redirects that make the Odoo door usable.

WHY THIS FILE EXISTS. test_14 proves the ticket machinery by minting tickets with the signing key.
It never asks the question a person asks: how do I GET to that door? The answer was "you cannot" --
the portals capture the gateway's refresh cookie and re-issue it under their own host, so a browser
had nothing to send to `auth.` and every human got a bare JSON 401. These cases hold that door open.

The refusals are the substance here. A login form is an unauthenticated, internet-facing surface on
the service that holds the JWT signing key, so what matters is that it refuses the same way the
JSON API already refuses, and that it cannot be driven from another site.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

from helpers import env as envh
from helpers import web

pytestmark = [pytest.mark.live]

CSRF_COOKIE = "athera_login_csrf"
#: The production Odoo hostname. These cases run against the real route on purpose: a test host
#: that mirrors it is a second door with the same power, and the one that gets forgotten when the
#: real one changes.
ODOO_EDGE_HOST = "odoo"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _raw(url, method="GET", headers=None, data=None):
    """(status, headers, set_cookies, body). Redirects are the assertion, so they are not followed."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            return (resp.status, dict(resp.headers),
                    resp.headers.get_all("Set-Cookie") or [],
                    resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return (exc.code, dict(exc.headers), exc.headers.get_all("Set-Cookie") or [],
                exc.read().decode("utf-8", "replace"))


def _open_form(next_path="/auth/sso/odoo"):
    """Fetch the page and return (csrf token, cookie header) as a browser would hold them."""
    url = web.gateway_url("/auth/login?next=" + urllib.parse.quote(next_path, safe=""))
    status, _h, cookies, body = _raw(url, headers={"Accept": "text/html"})
    assert status == 200, status
    token = re.search(r'name="csrf" value="([^"]+)"', body)
    assert token, "the form carries no CSRF token"
    jar = [c.split(";", 1)[0] for c in cookies if c.startswith(CSRF_COOKIE + "=")]
    assert jar, "the page set no CSRF cookie"
    return token.group(1), jar[0]


def _post(fields, cookie=None):
    body = urllib.parse.urlencode(fields).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"}
    if cookie:
        headers["Cookie"] = cookie
    return _raw(web.gateway_url("/auth/login/form"), method="POST", headers=headers, data=body)


def _skip_if_locked(status, body):
    """The limiter counts failures per source IP, and this file produces failures on purpose.

    Two runs inside the five-minute window can reach the threshold, and a locked-out suite that
    reports FAILED is reporting the wrong thing: the lockout is the feature working.
    """
    if status == 429:
        pytest.skip("the rate limiter has this source locked out from an earlier run. NOT RUN.")


# ---------------------------------------------------------------------------------------------
# The page itself
# ---------------------------------------------------------------------------------------------


def test_the_login_page_is_served_with_a_csrf_cookie(evidence):
    csrf, cookie = _open_form()
    evidence.add("form", "csrf field %d chars, cookie %s" % (len(csrf), cookie.split("=")[0]))
    assert len(csrf) >= 16


def test_the_page_carries_no_external_reference(evidence):
    """`default-src 'self'` is satisfied by construction rather than by a policy exception."""
    _s, _h, _c, body = _raw(web.gateway_url("/auth/login"), headers={"Accept": "text/html"})
    external = re.findall(r'(?:src|href)="(?!/)[^"]*"', body)
    evidence.add("external references", str(external))
    assert external == [], external


def test_the_login_page_is_not_indexable(evidence):
    _s, _h, _c, body = _raw(web.gateway_url("/auth/login"), headers={"Accept": "text/html"})
    evidence.add("robots meta", "noindex" in body)
    assert "noindex" in body


# ---------------------------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------------------------


def test_a_form_post_without_a_csrf_token_is_refused(evidence):
    status, _h, _c, _b = _post({"db": "bct", "login": "x@contoh.invalid",
                                "password": "salah", "next": "/auth/sso/odoo"})
    evidence.add("no csrf", status)
    assert status == 400, status


def test_a_mismatched_csrf_token_is_refused(evidence):
    _csrf, cookie = _open_form()
    status, _h, _c, _b = _post({"db": "bct", "login": "x@contoh.invalid", "password": "salah",
                                "next": "/auth/sso/odoo", "csrf": "not-the-one"}, cookie)
    evidence.add("wrong csrf", status)
    assert status == 400, status


def test_bad_credentials_answer_401_so_the_jail_can_count_them(evidence):
    """The fail2ban jail reads Caddy's log for a failed login. A refusal rendered as 200 is a
    refusal the jail never sees, and the bruteforce mitigation quietly stops covering this path."""
    csrf, cookie = _open_form()
    status, _h, _c, body = _post({"db": "bct", "login": "tidak-ada@contoh.invalid",
                                  "password": "salah", "next": "/auth/sso/odoo",
                                  "csrf": csrf}, cookie)
    _skip_if_locked(status, body)
    evidence.add("bad password", "%s | %s" % (status, "tidak cocok" in body))
    assert status == 401, status
    assert "tidak cocok" in body


def test_an_unknown_database_is_indistinguishable_from_a_bad_password(evidence):
    """Whether a tenant exists is not something an anonymous visitor gets to learn -- the same
    decision the JSON API has carried since it was written, and the reason tenants have no DNS."""
    csrf, cookie = _open_form()
    status, _h, _c, body = _post({"db": "tidak_ada_sama_sekali", "login": "tidak-ada@contoh.invalid",
                                  "password": "salah", "next": "/auth/sso/odoo",
                                  "csrf": csrf}, cookie)
    _skip_if_locked(status, body)
    evidence.add("unknown database", "%s | %s" % (status, "tidak cocok" in body))
    assert status == 401, status
    assert "tidak cocok" in body


def test_an_oversized_body_is_refused_before_it_is_parsed(evidence):
    csrf, cookie = _open_form()
    status, _h, _c, _b = _post({"db": "bct", "login": "x@contoh.invalid", "csrf": csrf,
                                "next": "/auth/sso/odoo", "password": "A" * 20000}, cookie)
    evidence.add("20 KB body", status)
    assert status == 413, status


def test_next_cannot_leave_this_site(evidence):
    """`//evil.example` starts with a slash and is absolute to a browser. That is the case a
    startswith('/') check lets through, so it is the case worth asserting."""
    _s, _h, _c, body = _raw(
        web.gateway_url("/auth/login?next=" + urllib.parse.quote("//evil.example/x", safe="")),
        headers={"Accept": "text/html"})
    hidden = re.search(r'name="next" value="([^"]*)"', body)
    evidence.add("next rewritten to", hidden.group(1) if hidden else None)
    assert hidden and hidden.group(1) == "/auth/sso/odoo"


# ---------------------------------------------------------------------------------------------
# The redirects that make the door reachable
# ---------------------------------------------------------------------------------------------


def _edge(path, accept):
    """Through Caddy, which is where forward_auth lives. curl carries SNI; urllib would send the
    literal 127.0.0.1 and Caddy would answer `tls: internal error` with no site matched."""
    import subprocess
    host = "%s.%s" % (ODOO_EDGE_HOST, envh.env("ATHERA_DOMAIN", "athera.localhost"))
    port = envh.env("CADDY_HTTPS_PORT", "38443")
    out = subprocess.run(
        ["curl", "-sk", "--resolve", "%s:%s:127.0.0.1" % (host, port),
         "-H", "Accept: " + accept, "-o", "/dev/null",
         "-w", "%{http_code} %{redirect_url}",
         "https://%s:%s%s" % (host, port, path)],
        capture_output=True, text=True, timeout=30)
    code, _, location = out.stdout.partition(" ")
    return int(code or 0), location


def test_a_browser_at_the_odoo_door_is_sent_to_the_login_page(evidence):
    status, location = _edge("/odoo/action-42", "text/html,application/xhtml+xml")
    evidence.add("cold entry (browser)", "%s -> %s" % (status, location))
    assert status == 303, status
    assert "/auth/login?next=" in location, location
    # The destination survives the round trip, or the door drops people on a landing page.
    assert "action-42" in urllib.parse.unquote(urllib.parse.unquote(location))


def test_a_json_client_at_the_odoo_door_still_gets_401(evidence):
    """Only the presentation branches on Accept. A redirect answered to an API caller would turn a
    refusal into something a script reads as success."""
    status, _location = _edge("/odoo", "application/json")
    evidence.add("cold entry (json)", status)
    assert status == 401, status


def test_an_unusable_route_cookie_sends_a_browser_back_through_the_handoff(evidence):
    import subprocess
    host = "%s.%s" % (ODOO_EDGE_HOST, envh.env("ATHERA_DOMAIN", "athera.localhost"))
    port = envh.env("CADDY_HTTPS_PORT", "38443")
    out = subprocess.run(
        ["curl", "-sk", "--resolve", "%s:%s:127.0.0.1" % (host, port),
         "-H", "Accept: text/html", "-H", "Cookie: athera_route=bukan.token.sah",
         "-o", "/dev/null", "-w", "%{http_code} %{redirect_url}",
         "https://%s:%s/odoo" % (host, port)],
        capture_output=True, text=True, timeout=30)
    code, _, location = out.stdout.partition(" ")
    evidence.add("expired route cookie", "%s -> %s" % (code, location))
    assert code == "303", out.stdout
    assert "/auth/login?next=" in location
