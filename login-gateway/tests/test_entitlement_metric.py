"""`bct_gateway_entitlement_enforcement_enabled` says whether the gate is armed.

WHY THIS METRIC EXISTS. When `LOGIN_GATEWAY_REGISTRY_DSN` is empty, `registry.lookup()` answers
"active, every product" for every tenant -- subscription enforcement is off, platform-wide. That is
a deliberate fail-open (a new deployment must be able to boot before its control plane exists), and
the decision to keep it is the operator's. What was missing was any way to SEE it: the only trace
was a single WARNING at boot, which is a line nobody reads on the day it matters.

WHY BOTH DIRECTIONS ARE ASSERTED. A test that only checks the configured case passes on a gateway
whose enforcement is off, because the series is present either way -- only its value differs. The
zero case is the one worth having, so it is the one written first.

The zero case is built with an explicit `Settings(registry_dsn="")`, never by editing an
environment file: this suite must not be able to disarm a running deployment in order to test it.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.config import settings_from_env
from app.main import create_app


def _settings(**overrides):
    """A Settings that differs from the deployed one only where a test says so."""
    # A complete environment, spelled out. `settings_from_env` reads ONLY the mapping it is
    # given, so anything omitted lands as an empty string -- and two empty `kid`s look like a
    # duplicate key ring, which fails for a reason that has nothing to do with what is under test.
    base = settings_from_env(
        {
            "LOGIN_GATEWAY_JWT_KID": "test-active",
            "LOGIN_GATEWAY_JWT_NEXT_KID": "test-standby",
            "LOGIN_GATEWAY_JWT_PRIVATE_KEY_PATH": "secrets/jwt-private.pem",
            "LOGIN_GATEWAY_JWT_NEXT_PRIVATE_KEY_PATH": "secrets/jwt-next-private.pem",
        }
    )
    return dataclasses.replace(base, **overrides)


def _sample(app_settings) -> float:
    """Build an app and read the gauge back out of the registry it publishes."""
    from prometheus_client import REGISTRY

    create_app(app_settings)
    value = REGISTRY.get_sample_value("bct_gateway_entitlement_enforcement_enabled")
    assert value is not None, "the series is absent; /metrics would not carry it at all"
    return value


def test_zero_when_no_control_plane_is_configured():
    """The case worth having. An empty DSN means every tenant is treated as paid up."""
    assert _sample(_settings(registry_dsn="")) == 0.0


def test_one_when_a_control_plane_is_configured():
    """The DSN is never dialled at construction, so an unreachable host still reports armed --
    which is right: this gauge answers "is enforcement configured", not "is the database up"."""
    assert _sample(_settings(registry_dsn="host=127.0.0.1 port=1 dbname=x user=x")) == 1.0


def test_the_series_is_named_exactly_as_the_alert_expects():
    """A rule over a misspelled series can never fire, and `make check-alerting` exists to catch
    that. Pinning the name here means the rename is caught before the gate has to."""
    from prometheus_client import REGISTRY

    create_app(_settings(registry_dsn=""))
    names = {m.name for m in REGISTRY.collect()}
    assert "bct_gateway_entitlement_enforcement_enabled" in names


@pytest.mark.parametrize("dsn,expected", [("", 0.0), ("host=x dbname=y user=z", 1.0)])
def test_value_follows_the_dsn(dsn, expected):
    assert _sample(_settings(registry_dsn=dsn)) == expected
