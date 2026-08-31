"""Cold start: from genuinely removed volumes, `make up-dev` and `make up-analytics` bring the
stack up.

**This test destroys this project's data.** It is gated twice, deliberately:

* the ``coldstart`` marker, which nothing selects by accident; and
* ``RUN_COLDSTART=1``, without which every test here skips.

``make test-coldstart`` sets both, through ``scripts/coldstart-guard.sh``, which also snapshots
every volume and container belonging to another project and fails if any of them disappeared. This
host runs ``odoo19-platform-*``, ``odoo19-analytics-*`` and ``smart-warga-postgres-1``; their data
is not recoverable from this repository and ``docker volume rm`` has no undo.

Nothing in this file names a container, volume or project other than ``odoo19-bct``, and every
compose invocation goes through the Makefile, which is scoped with ``-p $(PROJECT)`` on every line.

**Why this cannot be replaced by "it worked when I set it up".** The state a developer's machine is
in after a week of work is not the state a fresh clone is in. `.gitignore` has already hidden three
install-critical files from a clone while every working-tree test passed; a compose file can
likewise depend on a volume that only exists because something created it by hand months ago. The
cold start is the only test whose starting state is the one a new machine actually has.
"""

from __future__ import annotations

import os

import time

import pytest

from conftest import run, wait_for
from helpers import db, env, web

pytestmark = [pytest.mark.coldstart, pytest.mark.destructive, pytest.mark.slow]

PROJECT = "odoo19-bct"
NEWLINE = chr(10)


def _foreign_resources():
    volumes = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    containers = run(["docker", "ps", "-a", "--format", "{{.Names}}"]).stdout.splitlines()
    return (
        sorted(v for v in volumes if v and not v.startswith((PROJECT + "-", PROJECT + "_"))),
        sorted(c for c in containers if c and not c.startswith(PROJECT + "-")),
    )


@pytest.fixture(scope="module")
def armed():
    if os.environ.get("RUN_COLDSTART") != "1":
        pytest.skip(
            "cold start destroys this project's volumes. Run `make test-coldstart` (which sets "
            "RUN_COLDSTART=1 and guards the other stacks on this host). NOT RUN."
        )


@pytest.fixture(scope="module")
def foreign_before(armed):
    volumes, containers = _foreign_resources()
    assert volumes or containers, (
        "no foreign volumes or containers found at all -- the guard has nothing to compare against, "
        "which is itself suspicious on this host"
    )
    return volumes, containers


def test_project_volumes_are_genuinely_removed(foreign_before, evidence):
    """`down -v` scoped to this project, then assert the volumes are actually gone.

    Asserting the removal matters more than performing it: a `down -v` that silently no-ops leaves
    the next step starting from a warm state, and the whole test then proves nothing.
    """
    before = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    ours_before = sorted(v for v in before if v.startswith((PROJECT + "-", PROJECT + "_")))
    evidence.add("this project's volumes before", "\n".join(ours_before) or "(none)")

    # Through the Makefile's own compose invocation, which carries -p odoo19-bct on every line.
    # `down-hard` prompts for confirmation, so the project name is fed to it on stdin.
    result = run(
        ["docker", "compose", "-p", PROJECT,
         "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml",
         "-f", "docker-compose.analytics.yml", "-f", "docker-compose.observability.yml",
         "down", "-v", "--remove-orphans"],
        timeout=600,
    )
    evidence.add("docker compose -p %s down -v" % PROJECT,
                 (result.stdout + result.stderr).strip()[-2000:])

    after = run(["docker", "volume", "ls", "--format", "{{.Name}}"]).stdout.splitlines()
    ours_after = sorted(v for v in after if v.startswith((PROJECT + "-", PROJECT + "_")))
    evidence.add("this project's volumes after", "\n".join(ours_after) or "(none -- removed)")
    assert not ours_after, (
        "volumes survived `down -v`, so the cold start would begin from a warm state: %r"
        % ours_after
    )


def test_make_up_dev_brings_the_stack_up_from_nothing(foreign_before, evidence):
    started = time.time()
    result = run(["make", "up-dev"], timeout=1800)
    evidence.add(
        "make up-dev (rc=%d, %.0fs)" % (result.returncode, time.time() - started),
        (result.stdout + result.stderr).strip()[-3000:],
    )
    assert result.returncode == 0, "make up-dev failed from a clean state"

    ok, seconds = wait_for(
        lambda: web.service_up("http://127.0.0.1:%s/web/login" % env.env("ODOO_HOST_HTTP_PORT", "38069")),
        300, 5.0,
    )
    evidence.add("/web/login answers", "after %.0fs: %s" % (seconds, bool(ok)))
    assert ok, "Odoo never answered /web/login after a cold start"

    ps = run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml",
              "-f", "docker-compose.dev.yml", "ps"], timeout=120)
    evidence.add("docker compose -p %s ps" % PROJECT, ps.stdout)


def test_the_modules_install_into_a_brand_new_database(foreign_before, evidence):
    """The five addons must install into the database `make up-dev` just created."""
    installed = db.query(
        db.oltp_odoo(),
        "SELECT name, state FROM ir_module_module WHERE name LIKE 'custom_%' ORDER BY name;",
    )
    evidence.add(
        "custom modules in the new database",
        "\n".join("%-26s %s" % r for r in installed) or "(none)",
    )
    not_installed = [n for n, s in installed if s != "installed"]
    assert installed, "no custom_* module is present in the freshly created database"
    assert not not_installed, "these modules did not install: %r" % not_installed

    seeded = db.scalar(db.oltp_odoo(), "SELECT count(*) FROM pdp_field_classification;")
    evidence.add("pdp_field_classification rows", seeded)
    assert int(seeded) > 0, (
        "the classification registry is empty in a fresh database. Its seed is a declared data file; "
        "if it is missing from the clone, `.gitignore` has hidden it again."
    )


def test_the_documented_credential_works_and_the_default_one_does_not(foreign_before, evidence):
    """A stack that came up is not a stack you can log into -- and worse, may be one anyone can.

    This test exists because the cold start it belongs to handed back an Odoo whose `admin` password
    was still Odoo's default `admin`, and reported success. Every assertion in this file was true:
    the containers were healthy, `/web/login` answered 200, the modules were present. None of them
    asked the question that mattered.

    `BCT_DEV_USER_PASSWORD` was set once, by hand, in a shell. It appears nowhere in the repository
    except an untracked local `.env` -- no Makefile target, no script, no seed model applies it, and
    `.env.example` does not declare it, so a fresh clone cannot learn that it exists. The stack a
    new machine gets therefore accepts `admin`/`admin`.

    **Both halves are required.** Asserting only that the documented credential works passes on a
    stack that accepts both, which is strictly worse than the one that accepts only the default:
    it looks configured.

    Owners: Platform-Addons for the demo users (in the seed, so it survives a rebuild) and
    Platform-Infra for `admin` and for declaring the variable in `.env.example`. Not QA's to fix.
    """
    from helpers import odoo as odoo_helper

    documented = env.env("BCT_DEV_USER_PASSWORD", "")
    example = (env.repo_root() / ".env.example").read_text(encoding="utf-8")

    default_admin = odoo_helper.authenticate("admin", "admin")
    results = [("admin", "admin (Odoo default)", default_admin)]
    if documented:
        for login in ("admin", "demo.ou1@contoh.invalid", "demo.ou2@contoh.invalid"):
            results.append((login, "$BCT_DEV_USER_PASSWORD", odoo_helper.authenticate(login, documented)))
    evidence.add(
        "authenticate() over JSON-RPC against the stack this cold start just built",
        "\n".join("%-28s %-24s -> %s" % r for r in results),
    )
    evidence.add(
        "BCT_DEV_USER_PASSWORD declared in .env.example",
        "yes" if "BCT_DEV_USER_PASSWORD" in example else "NO -- a fresh clone cannot learn it exists",
    )

    assert documented, (
        "BCT_DEV_USER_PASSWORD is not set, so there is no documented credential to verify. A cold "
        "start cannot be said to produce a usable stack."
    )
    assert "BCT_DEV_USER_PASSWORD" in example, (
        "BCT_DEV_USER_PASSWORD is absent from .env.example, so it exists only in one untracked "
        "local file. A fresh clone gets a stack whose password nobody can discover from the repo."
    )
    assert not default_admin, (
        "Odoo's DEFAULT password `admin` authenticates as uid %s on the stack this cold start just "
        "built. The dev password was applied by hand, once, and never became repo, so every rebuild "
        "hands back a default-credential Odoo." % default_admin
    )
    working = [login for login, _, uid in results[1:] if uid]
    assert working, (
        "no account accepts BCT_DEV_USER_PASSWORD on a freshly built stack. The documented "
        "credential is documentation only."
    )


def test_make_up_analytics_brings_the_warehouse_up_from_nothing(foreign_before, evidence):
    started = time.time()
    result = run(["make", "up-analytics"], timeout=1800)
    evidence.add(
        "make up-analytics (rc=%d, %.0fs)" % (result.returncode, time.time() - started),
        (result.stdout + result.stderr).strip()[-3000:],
    )
    assert result.returncode == 0, "make up-analytics failed from a clean state"

    admin = db.warehouse_admin()
    schemas = db.grid(
        admin, "SELECT nspname FROM pg_namespace WHERE nspname IN "
               "('raw','staging','marts','warehouse','snapshots') ORDER BY 1;"
    )
    evidence.add("schemas in the new warehouse", schemas)
    policy = db.scalar(admin, "SELECT count(*) FROM warehouse.column_policy;")
    roles = db.grid(
        admin,
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname IN "
        "('warehouse_admin','warehouse','warehouse_loader','warehouse_rls') ORDER BY 1;",
    )
    evidence.add("warehouse.column_policy rows", policy)
    evidence.add("roles created by the init DDL", roles)
    assert int(policy) > 0, "the column policy is empty after a cold start; nothing could replicate"
    for role in ("warehouse", "warehouse_loader", "warehouse_rls"):
        identity = db.role_identity(
            {"warehouse": db.warehouse_dbt(), "warehouse_loader": db.warehouse_loader(),
             "warehouse_rls": db.warehouse_rls()}[role]
        )
        assert identity.rls_applies, "%s came back as a superuser after a cold start" % role


def test_the_observability_overlay_comes_back_and_alerting_is_live(foreign_before, evidence):
    """A cold start that leaves alerting down is a cold start that has broken the safety net.

    `make up-dev` and `make up-analytics` do not touch the observability overlay, so a teardown that
    removed it leaves Prometheus, Alertmanager, Loki, promtail and node-exporter down. Every alert
    rule then fires into nothing -- and `make verify` keeps passing, because nothing it checks looks
    at alerting. That is the same "a check that cannot fail" shape as a rule on a series nobody
    emits; it simply arrives through a different door.

    **This widens the cold start's footprint**, and that is worth saying rather than doing quietly:
    before this test the overlay stayed down after a run, so the measured bring-up cost excluded it.
    It now includes Prometheus, Grafana, Loki, promtail, Alertmanager and both exporters.
    """
    started = time.time()
    result = run(["make", "up-obs"], timeout=900)
    evidence.add(
        "make up-obs (rc=%d, %.0fs)" % (result.returncode, time.time() - started),
        (result.stdout + result.stderr).strip()[-1500:],
    )
    assert result.returncode == 0, "make up-obs failed after a cold start"

    # `check-alerting` exits **0** when it skips -- it prints "NOT a pass" and returns success, so
    # an exit-code-only assertion passes while alerting is entirely unverified. That is the same
    # vacuous shape this suite exists to catch, and it was caught here in this very test on its
    # first run: Prometheus was still starting, the script skipped, rc was 0, and the assertion
    # went green. Exit code AND output, therefore.
    def verdict():
        out = run(["make", "check-alerting"], timeout=300)
        text = (out.stdout + out.stderr)
        return out.returncode == 0 and "SKIP" not in text, text

    ok, seconds = wait_for(lambda: verdict()[0], 300, 15.0)
    final = run(["make", "check-alerting"], timeout=300)
    text = (final.stdout + final.stderr).strip()
    evidence.add(
        "make check-alerting (rc=%d, settled after %.0fs)" % (final.returncode, seconds), text[-2500:]
    )
    assert final.returncode == 0, (
        "alerting is not live after the cold start. Every rule in the project is currently firing "
        "into nothing, and no other check in this project would notice."
    )
    assert "SKIP" not in text, (
        "check-alerting SKIPPED rather than verified. It exits 0 on a skip and says so in words "
        "('NOT a pass'), so the exit code alone would have reported this cold start as having live "
        "alerting when nothing had been checked."
    )


def test_the_documented_pipeline_targets_bring_the_rest_of_the_stack_up(
    foreign_before, evidence
):
    """`up-gateway` -> `up-semantic` -> `cdc-start`, in the documented order, from a cold start.

    Platform-Infra reported the container-starting halves of these targets as NOT VERIFIED, because
    verifying them would have meant restarting services underneath Frontend's live measurements.
    This run is the one that can: everyone else has finished, so the stack is disposable.

    The order is load-bearing and encoded in the Makefile's own help text -- `up-semantic` fetches
    JWKS from the gateway, and `cdc-start` provisions the publication before the consumer creates
    the slot. Running them out of order is a different test; running them in order is this one.
    """
    from helpers import web

    for target, ready in (
        ("up-gateway", lambda: web.service_up(web.gateway_url("/healthz"))),
        ("up-semantic", lambda: web.service_up(web.semantic_url("/healthz"))),
        ("cdc-start", None),
    ):
        started = time.time()
        result = run(["make", target], timeout=1800)
        evidence.add(
            "make %s (rc=%d, %.0fs)" % (target, result.returncode, time.time() - started),
            (result.stdout + result.stderr).strip()[-1200:],
        )
        assert result.returncode == 0, "make %s failed from a cold start" % target
        if ready is not None:
            ok, seconds = wait_for(ready, 180, 3.0)
            evidence.add("%s answers /healthz" % target, "after %.0fs: %s" % (seconds, bool(ok)))
            assert ok, "make %s returned 0 but the service never answered /healthz" % target

    status = run(["make", "cdc-status"], timeout=300)
    evidence.add("make cdc-status", (status.stdout + status.stderr).strip()[-1500:])

    # The loader must actually be streaming, not merely started. A slot with a consumer is the
    # observable fact; `cdc-status` deliberately never fails, so it cannot be the assertion.
    slots = db.grid(
        db.oltp_odoo(),
        "SELECT slot_name, active, wal_status FROM pg_replication_slots ORDER BY slot_name;",
    )
    evidence.add("replication slots after cdc-start", slots)
    rows = db.query(
        db.oltp_odoo(), "SELECT slot_name, active FROM pg_replication_slots;"
    )
    assert rows, "cdc-start returned 0 but created no replication slot"
    assert any(r[1] == "t" for r in rows), (
        "a slot exists but has no consumer after cdc-start: %r" % (rows,)
    )


def test_the_fixture_tenant_and_cross_tenant_403_survive_a_cold_start(
    foreign_before, evidence
):
    """`bct_t2` must hold rows before any isolation claim, then the 403 must still be exact.

    Order matters here and it is the whole point: the precondition is asserted first, so that a 403
    returned because the other tenant has no data cannot be mistaken for a 403 returned because the
    boundary held.
    """
    from helpers import tokens, web

    admin = db.warehouse_admin()
    grid = db.grid(
        admin,
        "SELECT tenant_id, count(*) FROM marts.fct_sale_order_line GROUP BY 1 ORDER BY 1;",
    )
    evidence.add("rows per tenant in marts.fct_sale_order_line", grid)
    other = db.scalar(
        admin,
        "SELECT count(*) FROM marts.fct_sale_order_line WHERE tenant_id = 'bct_t2';",
    )
    evidence.add("bct_t2 rows", other)
    assert int(other or 0) > 0, (
        "tenant bct_t2 holds no rows after the cold start, so a cross-tenant 403 below would pass "
        "by having nothing to leak. `make up-analytics` loads this fixture tenant."
    )

    token = tokens.valid(tokens.claims(tenant="bct"))
    response = web.request(
        web.semantic_url("/v1/query"), method="POST",
        payload={"metric": "revenue_net", "dimensions": ["date_day"],
                 "filters": {"date_range": ["2026-01-01", "2026-12-31"],
                             "tenant_id": "bct_t2"}, "limit": 5},
        headers={"Authorization": "Bearer %s" % token},
    )
    evidence.add("bct token requesting bct_t2", "HTTP %s%s%s" % (response.status, NEWLINE, response.body))
    assert response.status == 403, "expected 403, got %s: %s" % (response.status, response.body[:300])
    assert response.json() == {
        "error": "tenant_scope_violation",
        "detail": "Session is not scoped to the requested tenant.",
    }, "the 403 body no longer matches frozen contract 02: %s" % response.body


def test_the_other_stacks_on_this_host_are_still_there(foreign_before, evidence):
    """The tripwire. Runs last, and is the assertion this whole file is gated for."""
    before_volumes, before_containers = foreign_before
    after_volumes, after_containers = _foreign_resources()
    lost_volumes = [v for v in before_volumes if v not in after_volumes]
    lost_containers = [c for c in before_containers if c not in after_containers]
    evidence.add(
        "foreign resources, before -> after",
        "volumes    %d -> %d\ncontainers %d -> %d\nlost volumes:    %s\nlost containers: %s"
        % (len(before_volumes), len(after_volumes), len(before_containers), len(after_containers),
           lost_volumes or "none", lost_containers or "none"),
    )
    assert not lost_volumes, (
        "the cold start destroyed volumes belonging to another project: %r. This is irreversible."
        % lost_volumes
    )
    assert not lost_containers, "containers belonging to another project disappeared: %r" % lost_containers
