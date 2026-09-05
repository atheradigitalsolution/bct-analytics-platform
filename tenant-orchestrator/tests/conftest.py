"""Fixtures for the orchestrator tests.

Nothing here touches Postgres or Odoo. ``Registry`` and ``OdooClient`` are the
service's only two outbound edges, and both are replaced with recorders before
``create_app`` runs, so a test asserts on what the handler DECIDED rather than
on what a database happened to be holding. Everything else -- the HMAC
middleware, the routing, the JSON shapes -- is the real thing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

#: A slug the fake registry does not know, so a handler's not-found branch can
#: be reached without inventing a second fixture.
MISSING_SLUG = "no_such_tenant"

#: Long enough and unremarkable enough to satisfy settings_from_env, which
#: refuses to start on a short or placeholder secret.
# The `example-` prefix is not decoration: scripts/scan-secrets.py exempts values
# carrying it precisely so a test can hold a wrong-on-purpose secret without
# tripping the gate. The length stays above the 32 the config demands, because
# the point of this value is to satisfy that check, not to dodge it.
SECRET = "example-orchestrator-unit-test-secret-0123456789"

#: What the environment says a tenant gets when the caller names no modules.
DEFAULT_MODULES = ("custom_core", "custom_athera_branding")


class FakeRegistry:
    """Records every write instead of making one."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.log_calls: list[tuple[tuple, dict]] = []
        self.states: list[tuple[str, str]] = []
        self.created: list[dict] = []
        self.extended: list[tuple[str, int]] = []
        #: Lets a test say "this tenant is suspended" without a database.
        self.state_for: dict[str, str] = {}
        self.create_error: Exception | None = None

    # --- reads ---
    def ping(self) -> bool:
        return True

    def get_tenant(self, slug: str) -> dict:
        return {"id": 1, "slug": slug, "state": "provisioning"}

    def entitlement(self, slug: str) -> dict:
        return {"active": False, "products": []}

    def list_tenants(self, state=None) -> list:
        return []

    # --- writes ---
    def create_tenant(self, payload: dict) -> dict:
        if self.create_error is not None:
            raise self.create_error
        self.created.append(dict(payload))
        return {"id": 1, "slug": payload["slug"], "state": "provisioning"}

    def set_state(self, slug: str, state: str, stamp=None) -> dict:
        self.states.append((slug, state))
        return {"id": 1, "slug": slug, "state": state}

    def extend_validity(self, slug: str, days: int) -> dict:
        if slug == MISSING_SLUG:
            # THE REAL CLASS, not a look-alike. The handler catches
            # app.registry.TenantNotFound by identity; a same-named exception
            # declared here would sail straight past that except clause and the
            # test would prove the opposite of what it claims. Imported inside
            # the method so collection still does not touch app.registry.
            from app.registry import TenantNotFound as _RealTenantNotFound

            raise _RealTenantNotFound(slug)
        self.extended.append((slug, days))
        # The real query returns the row AFTER the update; the state is echoed
        # unchanged on purpose, because a manual extension must not resume a
        # suspended tenant and the test asserts exactly that.
        return {"id": 1, "slug": slug, "state": self.state_for.get(slug, "active"),
                "valid_until": "2026-12-31T00:00:00+00:00"}

    def log_action(self, *args, **kwargs) -> None:
        self.log_calls.append((args, kwargs))

    # --- assertions helper ---
    def audit_text(self) -> str:
        """Everything that would have been written to the action log, as text.

        Serialised the same way registry.log_action serialises `detail` -- via
        json.dumps -- plus the positional and keyword arguments around it, so a
        secret smuggled in through ANY argument shows up in this string. A test
        that scanned only `detail` would miss a password passed as `error`.
        """
        return json.dumps(self.log_calls, default=str)


class FakeOdoo:
    """Records the RPC arguments and returns whatever the test asked for."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict] = []
        self.job: dict | Exception = {"slug": "unset", "job_uuid": "job-0001"}

    def enqueue_provision(self, slug, modules, admin_password) -> dict:
        self.calls.append(
            {"slug": slug, "modules": list(modules), "admin_password": admin_password}
        )
        if isinstance(self.job, Exception):
            raise self.job
        return dict(self.job)

    def ping(self) -> bool:
        return True


@pytest.fixture
def wiring(monkeypatch):
    """A live app whose two outbound edges are recorders.

    Returns (client, registry, odoo). Import of app.main is deferred until the
    environment is set, because settings_from_env runs at create_app time and
    refuses a missing DSN or a weak secret.
    """
    monkeypatch.setenv("ORCHESTRATOR_SHARED_SECRET", SECRET)
    monkeypatch.setenv("ORCHESTRATOR_REGISTRY_DSN", "postgresql://unused/unused")
    monkeypatch.setenv("ORCHESTRATOR_PROVISION_MODULES", ",".join(DEFAULT_MODULES))

    from app import main as main_module

    registry = FakeRegistry("postgresql://unused/unused")
    odoo = FakeOdoo()
    monkeypatch.setattr(main_module, "Registry", lambda dsn: registry)
    monkeypatch.setattr(main_module, "OdooClient", lambda *a, **k: odoo)

    with TestClient(main_module.create_app()) as client:
        yield client, registry, odoo


def signed_post(client, path: str, body: dict | None = None):
    """POST with the signature custom_super_admin actually sends.

    t=<unix>,v1=<hex hmac_sha256(secret, b"<t>." + body)>. Built here rather
    than mocked away so the middleware stays in the path being tested.
    """
    raw = b"" if body is None else json.dumps(body).encode()
    return signed_post_raw(client, path, raw)


def signed_post_raw(client, path: str, raw: bytes):
    """Same signature, arbitrary bytes.

    Exists so a test can send a body that is NOT valid JSON. Going through
    `signed_post` would serialise it first, which is precisely the case that
    cannot be reached that way -- and the case where the old hand-rolled parser
    silently produced an empty dict.
    """
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return client.post(
        path,
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Custom-Signature": "t=%s,v1=%s" % (ts, mac),
            "X-Custom-Actor": "tester",
        },
    )


def signed_get(client, path: str):
    ts = str(int(time.time()))
    mac = hmac.new(SECRET.encode(), ts.encode() + b".", hashlib.sha256).hexdigest()
    return client.get(
        path, headers={"X-Custom-Signature": "t=%s,v1=%s" % (ts, mac)}
    )
