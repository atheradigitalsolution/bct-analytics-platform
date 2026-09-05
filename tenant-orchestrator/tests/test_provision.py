"""POST /v1/tenants: reserved slugs, the admin credential, and where it must not go.

Three defects are pinned here, all of them silent in production:

* a reserved slug was accepted, and the tenant then answered on a hostname the
  platform routes to itself;
* `admin_password` was never sent, so the new tenant's administrator kept the
  password `odoo -i` hands every database it builds;
* the credential was never returned, so the wizard's `result.get("admin_password")`
  was always None and nobody could log in even when one had been set.

The last group of tests is the one that matters most: the credential is now
RETURNED, which means there is now something to leak. They assert it does not
reach the audit log, and the final test proves that assertion can fail.
"""

from __future__ import annotations

import json
import string

import pytest

from app.main import RESERVED_SLUGS, OdooError, _generate_admin_password
from tests.conftest import (
    DEFAULT_MODULES,
    MISSING_SLUG,
    signed_get,
    signed_post,
    signed_post_raw,
)

VALID_SLUG = "tenant_alpha"


# ---------------------------------------------------------------------------
# Reserved slugs
# ---------------------------------------------------------------------------

def test_reserved_set_is_exactly_the_agreed_seven():
    """Pinned, because all three layers must carry the identical set.

    The Odoo wizard and the CHECK on tenant_registry.tenants.slug enforce the
    same list. If someone adds a label here and nowhere else, the layers
    disagree and the tightest one wins in a place nobody is looking.
    """
    assert RESERVED_SLUGS == frozenset(
        {"admin", "app", "auth", "insight", "mail", "odoo", "www"}
    )


@pytest.mark.parametrize("slug", sorted(RESERVED_SLUGS))
def test_reserved_slug_is_rejected_with_the_reason(wiring, slug):
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": slug})

    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert slug in detail
    # The message has to say WHY, or the operator reads it as an arbitrary
    # denylist and files a ticket to add an exception.
    assert "reserved" in detail
    assert "subdomain" in detail
    assert "route" in detail
    # And it has to say what this is NOT about, because "reserved name" reads
    # as "database name collision" to anyone who has met one.
    assert "database names" in detail

    # Rejected before anything was written or enqueued.
    assert registry.created == []
    assert odoo.calls == []


def test_slug_that_merely_contains_a_reserved_label_is_accepted(wiring):
    """`admin_ops` is not `admin`. Membership, not prefix matching.

    A substring rule here would reject a real client whose name happens to
    start with one of these words, and the route it would hijack does not
    exist -- `admin_ops.<domain>` is nobody's hostname.
    """
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": "admin_ops"})

    assert resp.status_code == 202
    assert registry.created[0]["slug"] == "admin_ops"


def test_valid_slug_is_still_accepted(wiring):
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})

    assert resp.status_code == 202
    assert resp.json()["tenant"]["slug"] == VALID_SLUG
    assert odoo.calls[0]["slug"] == VALID_SLUG


def test_invalid_slug_still_fails_on_the_pattern_first(wiring):
    """A dashed slug is rejected by SLUG_RE, and the reason stays the old one."""
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": "not-a-valid-slug"})

    assert resp.status_code == 400
    assert "replication slot" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# The admin credential
# ---------------------------------------------------------------------------

def test_password_is_generated_when_the_caller_sends_none(wiring):
    """The defect verbatim: the RPC used to receive "" here."""
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})

    assert resp.status_code == 202
    sent = odoo.calls[0]["admin_password"]
    assert sent, "orchestrator sent an empty admin_password"
    assert len(sent) >= 24


def test_generated_password_is_strong_and_safe_to_carry(wiring):
    """Length, alphabet and non-repetition, checked on the generator itself."""
    passwords = {_generate_admin_password() for _ in range(200)}

    assert len(passwords) == 200, "generator repeated a password"
    allowed = set(string.ascii_letters + string.digits)
    for pw in passwords:
        assert len(pw) == 32
        assert set(pw) <= allowed, "password carries a character that needs escaping"


def test_supplied_password_is_used_verbatim(wiring):
    """A caller that brings its own is not overridden, and not mangled."""
    client, registry, odoo = wiring
    given = "Correct Horse Battery Staple 42"
    resp = signed_post(
        client, "/v1/tenants", {"slug": VALID_SLUG, "admin_password": given}
    )

    assert resp.status_code == 202
    assert odoo.calls[0]["admin_password"] == given
    assert resp.json()["admin_password"] == given


def test_response_carries_the_password_the_rpc_received(wiring):
    """The wizard reads result["admin_password"]. It has to be the same string.

    Returning a DIFFERENT generated value than the one Odoo was told to set is
    the same outage as returning None, only harder to diagnose.
    """
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})

    body = resp.json()
    assert "admin_password" in body
    assert body["admin_password"] == odoo.calls[0]["admin_password"]


def test_insight_only_tenant_reports_no_password(wiring):
    """No Odoo database, so no administrator, so null -- not a fabricated one."""
    client, registry, odoo = wiring
    resp = signed_post(
        client,
        "/v1/tenants",
        {"slug": VALID_SLUG, "insight_source_kind": "external_postgres"},
    )

    assert resp.status_code == 202
    assert resp.json() == {
        "tenant": {"id": 1, "slug": VALID_SLUG, "state": "provisioning"},
        "job": None,
        "admin_password": None,
    }
    assert odoo.calls == []


def test_get_tenant_never_republishes_a_password(wiring):
    """Returned once, at creation. A GET must not be a second chance at it."""
    client, registry, odoo = wiring
    created = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG}).json()

    fetched = signed_get(client, "/v1/tenants/%s" % VALID_SLUG)
    assert fetched.status_code == 200
    assert "admin_password" not in fetched.json()
    assert created["admin_password"] not in fetched.text


# ---------------------------------------------------------------------------
# The seam: the body key is `modules`, and there is no alias
# ---------------------------------------------------------------------------

def test_modules_is_the_only_accepted_key(wiring):
    client, registry, odoo = wiring
    signed_post(client, "/v1/tenants", {"slug": VALID_SLUG, "modules": ["custom_x"]})
    assert odoo.calls[0]["modules"] == ["custom_x"]


def test_install_modules_is_not_an_alias(wiring):
    """Still deliberate, and now stricter than it was.

    THE EXPECTATION HERE CHANGED ON PURPOSE, 2026-09-05. It used to assert that
    `install_modules` was ignored and the tenant was built with the environment's
    default set -- "wrong in a way the operator can see". That reasoning was
    right about aliases and wrong about timing: the operator saw it only after a
    tenant existed with the wrong modules installed, and had to infer the cause
    from the module list.

    The request body is a Pydantic model with `extra="forbid"`, so the same
    mistake is now named in the reply and NOTHING IS CREATED. That is the same
    principle arriving earlier, not a different one.
    """
    client, registry, odoo = wiring
    resp = signed_post(
        client, "/v1/tenants", {"slug": VALID_SLUG, "install_modules": ["custom_x"]}
    )
    assert resp.status_code == 400
    assert "install_modules" in resp.json()["detail"]
    # The refusal must come BEFORE anything is written. A registry row for a
    # tenant whose provisioning call was rejected is the exact debris this
    # ordering exists to avoid.
    assert registry.created == []
    assert odoo.calls == []


# ---------------------------------------------------------------------------
# Leak containment -- the point of the whole change
# ---------------------------------------------------------------------------

def test_password_never_reaches_the_action_log(wiring):
    client, registry, odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})
    password = resp.json()["admin_password"]

    assert registry.log_calls, "nothing was audited at all -- the scan proves nothing"
    assert password not in registry.audit_text()


def test_supplied_password_never_reaches_the_action_log(wiring):
    """The generated path and the caller-supplied path are separate strings."""
    client, registry, odoo = wiring
    given = "Sup3rSecretFromTheCaller"
    signed_post(client, "/v1/tenants", {"slug": VALID_SLUG, "admin_password": given})

    assert registry.log_calls
    assert given not in registry.audit_text()


def test_password_echoed_back_by_odoo_never_reaches_the_action_log(wiring):
    """The one that catches a regression to `{"job": job}`.

    Odoo's return value is a remote dict. If a future version of
    ``athera.provisioner`` echoes the credential back in it -- deliberately or
    by accident -- copying the dict whole into the audit log publishes it to
    every super-admin, permanently, in an append-only table. _job_detail
    whitelists, so this test fails the moment someone stops using it.
    """
    client, registry, odoo = wiring
    given = "EchoedBackByTheFarSide99"
    odoo.job = {
        "slug": VALID_SLUG,
        "job_uuid": "job-4242",
        "admin_password": given,   # the far side leaks it back at us
        "credentials": {"password": given},
    }

    resp = signed_post(
        client, "/v1/tenants", {"slug": VALID_SLUG, "admin_password": given}
    )
    assert resp.status_code == 202

    audit = registry.audit_text()
    assert given not in audit
    # The correlation id still survives; whitelisting must not gut the audit.
    assert "job-4242" in audit


def test_password_never_reaches_the_log_stream(wiring, caplog):
    client, registry, odoo = wiring
    with caplog.at_level("DEBUG"):
        resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})
    password = resp.json()["admin_password"]

    assert password not in caplog.text


def test_password_never_reaches_the_action_log_on_failure(wiring):
    """The 502 path persists Odoo's fault string. That is not a hiding place.

    Found by this test: the handler used to write ``str(exc)`` into the action
    log unmodified. The exception text is composed on the far side, and the far
    side has just been given the credential, so a fault that quotes its own
    arguments would have published it into an append-only table. _redact closes
    the half of that this service can close by itself.
    """
    client, registry, odoo = wiring
    given = "FailurePathSecret77"
    odoo.job = OdooError("Odoo refused; tried password %s" % given)

    resp = signed_post(
        client, "/v1/tenants", {"slug": VALID_SLUG, "admin_password": given}
    )
    assert resp.status_code == 502
    assert registry.states == [(VALID_SLUG, "failed")]

    audit = registry.audit_text()
    assert given not in audit
    assert "[redacted]" in audit
    # The rest of the diagnosis survives; redaction must not blank the reason.
    assert "Odoo refused" in audit
    assert given not in resp.text


def test_failure_reason_is_unchanged_when_it_holds_no_credential(wiring):
    """Redaction is a substring removal, not a filter over the whole message."""
    client, registry, odoo = wiring
    odoo.job = OdooError("Database already exists; refusing to provision over it.")

    resp = signed_post(client, "/v1/tenants", {"slug": VALID_SLUG})

    assert resp.status_code == 502
    assert "refusing to provision over it" in resp.json()["detail"]
    assert "[redacted]" not in registry.audit_text()


def test_the_leak_scan_can_actually_fail(wiring):
    """A negative control for every assertion above.

    An assertion that a needle is absent proves nothing unless the search would
    have found it. This plants the needle in the same recorder, through the same
    argument shapes the handler uses, and requires audit_text() to catch each
    one. If this test ever passes trivially, the tests above are decorative.
    """
    client, registry, odoo = wiring
    needle = "PlantedNeedle12345"

    registry.log_action("s", "provision", "tester", "success", {"job": {"pw": needle}})
    assert needle in registry.audit_text(), "a leak through `detail` would be missed"

    registry.log_calls.clear()
    registry.log_action("s", "provision", "tester", "failure", error=needle)
    assert needle in registry.audit_text(), "a leak through `error` would be missed"

    registry.log_calls.clear()
    registry.log_action("s", "provision", needle, "success")
    assert needle in registry.audit_text(), "a leak through `actor` would be missed"


# ---------------------------------------------------------------------------
# A malformed body is a named refusal, not an empty one
# ---------------------------------------------------------------------------

def test_body_that_is_not_json_is_refused_by_name(wiring):
    """The parser this replaces could not fail.

    It read the raw body and returned `{}` on any decode error, so `POST
    /v1/tenants` with a body of garbage reached the slug check as an ABSENT
    slug -- a 400 that named the wrong problem and sent the reader looking at
    the caller's slug logic instead of at the body.
    """
    client, registry, odoo = wiring
    resp = signed_post_raw(client, "/v1/tenants", b"this is not json at all")
    assert resp.status_code == 400
    # Names the body, not a character offset. Pydantic's `loc` for a decode
    # failure is ("body", 0), and rendering that verbatim produced
    # "0: JSON decode error" -- an offset presented as though it were a field.
    assert resp.json()["detail"] == "request body is not valid JSON"
    assert registry.created == []
    assert odoo.calls == []


def test_body_that_is_a_json_list_is_refused(wiring):
    """Valid JSON, wrong shape. The old parser turned this into `{}` as well."""
    client, registry, odoo = wiring
    resp = signed_post_raw(client, "/v1/tenants", b'["slug"]')
    assert resp.status_code == 400
    assert registry.created == []


def test_validation_failure_keeps_the_services_error_shape(wiring):
    """One error contract, whoever raised it.

    FastAPI's own answer is 422 with `detail` as a LIST of dicts. Every other
    refusal here is 400 with `detail` as a sentence, and the only consumer logs
    `resp.text[:300]` for a human. Two shapes would mean the most common failure
    reads the worst.
    """
    client, _registry, _odoo = wiring
    resp = signed_post(client, "/v1/tenants", {"slug": "Bad Slug"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_request"
    assert isinstance(resp.json()["detail"], str)
    assert "replication slot" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# The fields that were arriving and being thrown away
# ---------------------------------------------------------------------------

def test_csm_features_and_backup_schedule_reach_the_registry(wiring):
    """These three have columns, are sent on every wizard call, and were dropped.

    The INSERT did not name them and the hand-rolled parser did not read them,
    so a tenant created from the console had no CSM, no backup schedule and no
    feature flags -- with nothing anywhere reporting the loss.
    """
    client, registry, _odoo = wiring
    signed_post(client, "/v1/tenants", {
        "slug": VALID_SLUG,
        "csm_user_id": 7,
        "features": {"pajakku": True, "marketplace": False},
        "backup_schedule_cron": "0 2 * * *",
    })
    created = registry.created[0]
    assert created["csm_user_id"] == 7
    assert created["backup_schedule_cron"] == "0 2 * * *"
    # Serialised for a jsonb column, so the assertion reads the value back.
    assert json.loads(created["features"]) == {"pajakku": True, "marketplace": False}


# ---------------------------------------------------------------------------
# extend: the grant that had no button
# ---------------------------------------------------------------------------

def test_extend_without_a_reason_is_refused(wiring):
    """`reason` is the whole design.

    Extending access without payment is legitimate, and it is exactly the action
    someone will need explained six months from now. The only person who can
    explain it is the one clicking the button.
    """
    client, registry, _odoo = wiring
    resp = signed_post(client, f"/v1/tenants/{VALID_SLUG}/extend", {"days": 30})
    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"]
    assert registry.extended == []


def test_extend_with_a_token_reason_is_refused(wiring):
    """"ok" is not a reason. A field nobody can read later is decoration."""
    client, registry, _odoo = wiring
    resp = signed_post(
        client, f"/v1/tenants/{VALID_SLUG}/extend", {"days": 30, "reason": "ok"}
    )
    assert resp.status_code == 400
    assert registry.extended == []


def test_extend_beyond_the_ceiling_is_refused(wiring):
    """A slipped keystroke on a field measured in days must not grant a decade."""
    from app.main import MAX_EXTEND_DAYS

    client, registry, _odoo = wiring
    resp = signed_post(client, f"/v1/tenants/{VALID_SLUG}/extend", {
        "days": MAX_EXTEND_DAYS + 1, "reason": "annual contract renewal 2027",
    })
    assert resp.status_code == 400
    assert registry.extended == []


def test_extend_of_zero_or_negative_days_is_refused(wiring):
    client, registry, _odoo = wiring
    for days in (0, -30):
        resp = signed_post(client, f"/v1/tenants/{VALID_SLUG}/extend", {
            "days": days, "reason": "should never be applied",
        })
        assert resp.status_code == 400
    assert registry.extended == []


def test_extend_applies_and_is_written_to_the_audit_log(wiring):
    client, registry, _odoo = wiring
    resp = signed_post(client, f"/v1/tenants/{VALID_SLUG}/extend", {
        "days": 30, "reason": "pilot extended by agreement, see ticket 412",
    })
    assert resp.status_code == 200
    assert registry.extended == [(VALID_SLUG, 30)]
    audit = registry.audit_text()
    assert "extend" in audit
    assert "ticket 412" in audit


def test_extend_does_not_resume_a_suspended_tenant(wiring):
    """Suspension has its own reason and its own button.

    Payment-driven extension resumes a tenant because paying the invoice removes
    the reason for the suspension. A manual grant carries no such proof, and one
    click must not forgive two different things.
    """
    client, registry, _odoo = wiring
    registry.state_for[VALID_SLUG] = "suspended"
    resp = signed_post(client, f"/v1/tenants/{VALID_SLUG}/extend", {
        "days": 14, "reason": "invoice under dispute, access continues meanwhile",
    })
    assert resp.status_code == 200
    assert resp.json()["state"] == "suspended"
    assert registry.states == []


def test_extend_of_an_unknown_tenant_is_404(wiring):
    client, registry, _odoo = wiring
    resp = signed_post(client, f"/v1/tenants/{MISSING_SLUG}/extend", {
        "days": 30, "reason": "this tenant does not exist",
    })
    assert resp.status_code == 404
    assert registry.extended == []


# ---------------------------------------------------------------------------
# Backups: four write paths, one refusal, no 404s
# ---------------------------------------------------------------------------

BACKUP_WRITE_PATHS = (
    "/v1/tenants/acme/backups",
    "/v1/tenants/acme/backups/restore",
    "/v1/backups/1/replicate",
    "/v1/backups/enforce-retention",
)


@pytest.mark.parametrize("path", BACKUP_WRITE_PATHS)
def test_backup_write_paths_answer_501_not_404(wiring, path):
    """Three of these had no route at all, and custom_super_admin calls all four.

    A 404 tells the caller it typed the URL wrong and sends whoever reads the
    log hunting for a routing bug. 501 with a body naming the real path answers
    the question instead.
    """
    client, _registry, _odoo = wiring
    resp = signed_post(client, path, {})
    assert resp.status_code == 501, f"{path} answered {resp.status_code}"
    payload = resp.json()
    assert payload["error"] == "not_implemented"
    assert payload["implemented_by"] == "scripts/tenant-backup.sh (host)"
    assert "host" in payload["detail"]
