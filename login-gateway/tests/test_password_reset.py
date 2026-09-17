"""Reset password — the properties that must not quietly stop holding.

WHAT IS WORTH TESTING HERE. Not that the form renders; that a wrong answer is indistinguishable
from a right one. Every refusal in this flow is shaped so an unauthenticated visitor cannot learn
whether a tenant exists or whether an address has an account, and that shape is exactly the kind
of thing a later "helpful error message" undoes without anyone noticing.

NOTHING HERE TALKS TO ODOO OR TO A MAIL RELAY. `OdooClient.call_route` and `mailer.send_reset_mail`
are replaced, so what is under test is the gateway's own branching. The Odoo half is tested where
it lives, against a real database.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import mailer
from app.config import settings_from_env
from app.main import create_app
from app.odoo import OdooError


def _settings(**overrides):
    base = settings_from_env(
        {
            "LOGIN_GATEWAY_JWT_KID": "test-active",
            "LOGIN_GATEWAY_JWT_NEXT_KID": "test-standby",
            "LOGIN_GATEWAY_JWT_PRIVATE_KEY_PATH": "secrets/jwt-private.pem",
            "LOGIN_GATEWAY_JWT_NEXT_PRIVATE_KEY_PATH": "secrets/jwt-next-private.pem",
            "LOGIN_GATEWAY_ALLOWED_DATABASES": "bct,acme",
            "LOGIN_GATEWAY_RESET_SECRET": "s" * 32,
            "LOGIN_GATEWAY_SMTP_HOST": "relay.invalid",
            "LOGIN_GATEWAY_MAIL_FROM": "noreply@athera-digital.com",
            "LOGIN_GATEWAY_COOKIE_SECURE": "0",
        }
    )
    return dataclasses.replace(base, **overrides)


class _Recorder:
    """Stands in for the two outbound calls, and remembers what it was asked to do."""

    def __init__(self, token_result=None, complete_result=None, raises=None):
        self.token_result = token_result if token_result is not None else {"token": None}
        self.complete_result = complete_result or {"ok": True}
        self.raises = raises
        self.calls = []
        self.mails = []

    def call_route(self, db, path, params, headers=None):
        self.calls.append((db, path, params, headers))
        if self.raises:
            raise self.raises
        return self.token_result if path.endswith("/token") else self.complete_result

    def send_reset_mail(self, settings, to_address, reset_url, display_name=""):
        self.mails.append((to_address, reset_url, display_name))


@pytest.fixture
def client_and_recorder(monkeypatch):
    def _build(**overrides):
        rec = _Recorder(**{k: v for k, v in overrides.items()
                           if k in ("token_result", "complete_result", "raises")})
        settings = _settings(**{k: v for k, v in overrides.items()
                                if k not in ("token_result", "complete_result", "raises")})
        app = create_app(settings)
        monkeypatch.setattr("app.odoo.OdooClient.call_route", rec.call_route, raising=True)
        monkeypatch.setattr(mailer, "send_reset_mail", rec.send_reset_mail, raising=True)
        return TestClient(app), rec
    return _build


def _csrf(client):
    """Fetch the form and return the CSRF value the server just set, as a browser would."""
    page = client.get("/auth/reset")
    assert page.status_code == 200
    return client.cookies.get("athera_login_csrf")


def _submit(client, **fields):
    token = _csrf(client)
    body = {"csrf": token}
    body.update(fields)
    return client.post("/auth/reset/form", data=body, follow_redirects=False)


# ---------------------------------------------------------------------------------------
# The uniform answer
# ---------------------------------------------------------------------------------------

def test_known_account_and_unknown_account_are_byte_identical(client_and_recorder):
    """The property the whole flow is shaped around.

    An account that exists produces a mail; one that does not produces nothing. The page must
    not say which happened, and `==` on the body is the only assertion that keeps it that way.
    """
    # Built and submitted one at a time, deliberately. The fixture patches module-level
    # functions, so building the second client BEFORE submitting to the first would silently
    # redirect the first client's mail into the second recorder — and the test would then pass
    # for the wrong reason, with both requests taking the no-account path.
    known, rec_known = client_and_recorder(
        token_result={"token": "t0k", "email": "ada@contoh.test", "name": "Ada"}
    )
    a = _submit(known, db="bct", login="ada@contoh.test")

    unknown, rec_unknown = client_and_recorder(token_result={"token": None})
    b = _submit(unknown, db="bct", login="tidak-ada@contoh.test")

    assert a.status_code == b.status_code == 200
    assert a.text == b.text, "the page distinguishes an existing account from a missing one"
    assert len(rec_known.mails) == 1, "the existing account should have been mailed"
    assert rec_unknown.mails == [], "the missing account must not produce mail"


def test_unknown_tenant_answers_the_same_and_never_reaches_odoo(client_and_recorder):
    """A tenant code outside the allow-list is refused before the call, and silently.

    Both halves matter: answering differently would enumerate tenants, and calling Odoo anyway
    would turn this form into a way to probe which hostnames resolve on our internal network.
    """
    client, rec = client_and_recorder(
        token_result={"token": "t0k", "email": "a@b.test", "name": "A"}
    )
    good = _submit(client, db="bct", login="ada@contoh.test")
    bad = _submit(client, db="tidakada", login="ada@contoh.test")

    assert bad.status_code == 200
    assert bad.text == good.text
    assert all(call[0] != "tidakada" for call in rec.calls), "unknown tenant reached Odoo"


def test_mail_failure_is_invisible_to_the_visitor(client_and_recorder, monkeypatch):
    """A dead relay must not become a signal that the address was valid."""
    client, rec = client_and_recorder(
        token_result={"token": "t0k", "email": "ada@contoh.test", "name": "Ada"}
    )

    def _boom(*_a, **_kw):
        raise mailer.MailNotSent("SMTPConnectError")

    monkeypatch.setattr(mailer, "send_reset_mail", _boom, raising=True)
    failed = _submit(client, db="bct", login="ada@contoh.test")

    ok_client, _ = client_and_recorder(token_result={"token": None})
    ok = _submit(ok_client, db="bct", login="siapa@contoh.test")
    assert failed.status_code == 200
    assert failed.text == ok.text


def test_odoo_unreachable_is_invisible_to_the_visitor(client_and_recorder):
    client, _ = client_and_recorder(raises=OdooError("Odoo is unreachable: TimeoutError"))
    down = _submit(client, db="bct", login="ada@contoh.test")
    assert down.status_code == 200
    assert "Periksa email Anda" in down.text


def test_odoo_refusing_the_shared_secret_is_invisible_to_the_visitor(client_and_recorder):
    """A misconfigured tenant secret is an operator problem, loud in the log and silent here."""
    client, _ = client_and_recorder(token_result={"error": "unauthorised"})
    refused = _submit(client, db="bct", login="ada@contoh.test")
    assert refused.status_code == 200
    assert "Periksa email Anda" in refused.text


# ---------------------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------------------

def test_csrf_is_required(client_and_recorder):
    """Without it a third-party page can spend someone's reset quota, and with a guessed tenant
    code, aim our relay at an address of its choosing."""
    client, rec = client_and_recorder()
    client.get("/auth/reset")
    response = client.post(
        "/auth/reset/form", data={"csrf": "wrong", "db": "bct", "login": "a@b.test"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert rec.calls == [], "a CSRF-rejected request still called Odoo"


def test_the_shared_secret_travels_in_a_header_not_the_body(client_and_recorder):
    client, rec = client_and_recorder(
        token_result={"token": "t0k", "email": "a@b.test", "name": "A"}
    )
    _submit(client, db="bct", login="a@b.test")
    db, path, params, headers = rec.calls[0]
    assert path == "/athera/sso/reset/token"
    assert headers["X-Athera-Reset-Secret"] == "s" * 32
    assert "secret" not in str(params).lower()


def test_disabled_when_unconfigured_rather_than_silently_broken(client_and_recorder):
    """No SMTP host means no mail can ever arrive. Saying so beats a cheerful "check your email"
    that will never be true."""
    client, rec = client_and_recorder(smtp_host="")
    response = _submit(client, db="bct", login="a@b.test")
    assert response.status_code == 400
    assert "belum tersedia" in response.text
    assert rec.calls == []


def test_repeated_requests_are_rate_limited(client_and_recorder):
    client, _ = client_and_recorder(token_result={"token": None})
    seen_limited = False
    for _ in range(12):
        response = _submit(client, db="bct", login="ada@contoh.test")
        if "Terlalu banyak" in response.text:
            seen_limited = True
            break
    assert seen_limited, "the reset form never rate-limited a repeated request"


# ---------------------------------------------------------------------------------------
# Choosing the new password
# ---------------------------------------------------------------------------------------

def _submit_new(client, **fields):
    page = client.get("/auth/reset/new", params={"db": "bct", "token": "t0k"})
    assert page.status_code == 200
    body = {"csrf": client.cookies.get("athera_login_csrf"), "db": "bct", "token": "t0k"}
    body.update(fields)
    return client.post("/auth/reset/new", data=body, follow_redirects=False)


def test_the_link_page_does_not_spend_the_token(client_and_recorder):
    """Opening the link must not call Odoo. Mail scanners follow links, and a token spent by a
    preview is a token the person never gets to use."""
    client, rec = client_and_recorder()
    client.get("/auth/reset/new", params={"db": "bct", "token": "t0k"})
    assert rec.calls == []


def test_a_good_password_redirects_to_login_without_a_session(client_and_recorder):
    """No session is issued. A reset that logs you in makes possession of an inbox equal to
    possession of the account."""
    client, rec = client_and_recorder(complete_result={"ok": True})
    response = _submit_new(client, password="dummy-rahasia-baru", confirm="dummy-rahasia-baru")
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?db=bct"
    assert "bct_refresh" not in response.cookies
    assert rec.calls[-1][1] == "/athera/sso/reset/complete"


def test_mismatched_confirmation_never_reaches_odoo(client_and_recorder):
    client, rec = client_and_recorder()
    response = _submit_new(client, password="dummy-rahasia-baru", confirm="dummy-rahasia-lain")
    assert response.status_code == 400
    assert "tidak sama" in response.text
    assert rec.calls == []


def test_short_password_never_reaches_odoo(client_and_recorder):
    client, rec = client_and_recorder()
    response = _submit_new(client, password="pendek", confirm="pendek")
    assert response.status_code == 400
    assert "8 karakter" in response.text
    assert rec.calls == []


def test_a_refused_token_says_so_without_saying_why(client_and_recorder):
    """Expired, already spent and forged all render the same sentence."""
    client, _ = client_and_recorder(complete_result={"ok": False, "error": "invalid_or_expired"})
    response = _submit_new(client, password="dummy-rahasia-baru", confirm="dummy-rahasia-baru")
    assert response.status_code == 400
    assert "sudah dipakai atau kedaluwarsa" in response.text


def test_password_is_not_echoed_into_the_page_on_failure(client_and_recorder):
    """The re-rendered form must not carry the rejected password back to the browser."""
    client, _ = client_and_recorder(complete_result={"ok": False, "error": "invalid_or_expired"})
    response = _submit_new(client, password="dummy-rahasia-ditolak", confirm="dummy-rahasia-ditolak")
    assert "dummy-rahasia-ditolak" not in response.text
