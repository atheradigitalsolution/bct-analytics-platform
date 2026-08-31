"""Slot lag: the alert rules, the metric names they depend on, and the lag itself.

ADR 0001 makes this load-bearing rather than decorative. `max_slot_wal_keep_size = 2GB` means
Postgres will drop the warehouse's slot rather than let WAL fill the disk and take Odoo with it --
a deliberate trade. The consequence is that the alert firing *before* the cap is the only thing
standing between "the pipeline is behind" and "the warehouse silently has a hole in it".

Three separate things have to be true, and they are three separate tests because two of them can be
true while the third is false and nothing would report it:

1. **The rules fire at the ADR's thresholds.** Proved with `promtool test rules`, including the
   negative cases -- just below the threshold, and a healthy slot -- which a manual test almost
   never covers. See `tests/prometheus/slot_lag_alerts_test.yml` for why this is not a live firing
   test; the short version is that generating 512 MiB of WAL to prove it would risk the exact Odoo
   outage the cap exists to prevent.
2. **The thresholds are the ADR's numbers**, asserted from the rule file against the ADR's stated
   25% / 50% of a 2 GiB cap. A rule unit test proves a rule fires at its own threshold; it cannot
   notice the threshold has drifted from the decision.
3. **The metric names exist in reality.** A perfect rule on a series `postgres_exporter` never
   emits fires exactly never, and looks healthy on a dashboard for ever.

And the observable behaviour: stopping the consumer must make retained WAL grow and the slot go
inactive, which is what the rules key off.
"""

from __future__ import annotations

import time

import pytest

from conftest import run
from helpers import db, env, loader

pytestmark = [pytest.mark.live]

PROMETHEUS_IMAGE = "prom/prometheus:v2.55.1"
RULES = "observability/prometheus/rules/platform.rules.yml"

#: ADR 0001, "Replication slot safety": cap 2 GiB, warn at 512 MiB, critical at 1 GiB.
CAP_BYTES = 2 * 1024 ** 3
WARN_BYTES = 512 * 1024 ** 2
CRITICAL_BYTES = 1024 ** 3


def _promtool(args, evidence, label):
    """Run promtool out of the pinned Prometheus image, with the repo mounted read-only."""
    repo = str(env.repo_root()).replace("\\", "/")
    # `//x/...` is the form Docker Desktop accepts for a Windows path via a POSIX shell, and
    # MSYS_NO_PATHCONV stops Git Bash rewriting the container-side path.
    mount = "//" + repo[0].lower() + repo[2:] + ":/repo:ro"
    out = run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/promtool",
         "-e", "MSYS_NO_PATHCONV=1", "-v", mount, PROMETHEUS_IMAGE] + args,
        timeout=300,
    )
    evidence.add(label, (out.stdout + out.stderr).strip())
    return out


def test_alert_rules_are_syntactically_valid(evidence):
    out = _promtool(["check", "rules", "/repo/" + RULES], evidence, "promtool check rules")
    assert out.returncode == 0, out.stdout + out.stderr


def test_slot_alerts_fire_at_the_adr_thresholds(evidence):
    """The §6 "slot lag alert fires" requirement, as a rule unit test."""
    out = _promtool(
        ["test", "rules", "/repo/tests/prometheus/slot_lag_alerts_test.yml"],
        evidence, "promtool test rules (tests/prometheus/slot_lag_alerts_test.yml)",
    )
    assert out.returncode == 0, (
        "the slot-lag alert rules did not behave as specified:\n%s" % (out.stdout + out.stderr)
    )
    assert "SUCCESS" in out.stdout, out.stdout


def test_thresholds_still_match_adr_0001(evidence):
    """A rule unit test proves a rule fires at its own threshold, not that the threshold is right."""
    text = (env.repo_root() / RULES).read_text(encoding="utf-8")
    evidence.add(
        "threshold literals found in %s" % RULES,
        "\n".join(line.strip() for line in text.splitlines() if "expr:" in line and "lsn_diff" in line),
    )
    assert str(WARN_BYTES) in text, (
        "the 512 MiB warning threshold (%d) is not in the rule file; ADR 0001 sets warn at 25%% of "
        "the %d-byte cap" % (WARN_BYTES, CAP_BYTES)
    )
    assert str(CRITICAL_BYTES) in text, (
        "the 1 GiB critical threshold (%d) is not in the rule file" % CRITICAL_BYTES
    )
    assert 'wal_status="lost"' in text, (
        "no rule keys off wal_status=\"lost\"; an invalidated slot would be discovered from a stale "
        "dashboard, which ADR 0001 explicitly rules out"
    )


def test_the_metrics_the_rules_depend_on_actually_exist(oltp_up, evidence):
    """A rule on a series nobody emits fires never and looks healthy for ever.

    Checked against the postgres exporter if it is running; otherwise against the underlying
    `pg_replication_slots` view, which is what the exporter reads, so the test still says something.
    """
    from helpers import web

    exporter_up = env.container_running("odoo19-bct-postgres-exporter")
    if exporter_up:
        body = web.request("http://127.0.0.1:9187/metrics", timeout=10).body
        names = [n for n in ("pg_replication_slots_pg_wal_lsn_diff",
                             "pg_replication_slot_wal_status",
                             "pg_replication_slots_active") if n in body]
        evidence.add("series present on the exporter", "\n".join(names) or "(none)")
        assert len(names) == 3, "missing series: %r" % (set(names) ^ {
            "pg_replication_slots_pg_wal_lsn_diff", "pg_replication_slot_wal_status",
            "pg_replication_slots_active"})
        return

    grid = db.grid(
        db.oltp_odoo(),
        "SELECT slot_name, slot_type, active, wal_status, "
        "pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes "
        "FROM pg_replication_slots ORDER BY slot_name;",
    )
    evidence.add(
        "pg_replication_slots (the view postgres_exporter reads; the exporter is not running)", grid
    )
    rows = db.query(db.oltp_odoo(), "SELECT slot_name, wal_status, active FROM pg_replication_slots;")
    assert rows, "there are no replication slots at all; nothing for the rules to alert on"
    for slot, wal_status, _active in rows:
        assert wal_status in ("reserved", "extended", "unreserved", "lost"), (slot, wal_status)
    pytest.skip(
        "postgres-exporter is not running, so the exported series names could not be confirmed "
        "against a live /metrics endpoint. The underlying pg_replication_slots columns are present "
        "and were printed above. PARTIALLY RUN."
    )


@pytest.mark.destructive
@pytest.mark.slow
def test_stopping_the_consumer_makes_the_slot_inactive_and_lag_grow(
    oltp_up, cdc_running, evidence
):
    """The observable behaviour the alerts key off, measured in real bytes.

    Restarts the loader in a `finally`. Retained WAL of a few MiB is nowhere near the 512 MiB
    warning threshold, let alone the 2 GiB cap, so this is safe by a factor of about a hundred.
    """
    odoo = db.oltp_odoo()
    slot_sql = (
        "SELECT slot_name, active, wal_status, "
        "pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint "
        "FROM pg_replication_slots WHERE plugin = 'pgoutput' ORDER BY slot_name;"
    )
    before = db.query(odoo, slot_sql)
    evidence.add("slots while the consumer is running", db.grid(odoo, slot_sql))
    assert before, "no pgoutput slot exists"
    assert any(r[1] == "t" for r in before), "no slot is active even though the loader is running"

    try:
        loader.stop_main()
        time.sleep(5)
        inactive = db.query(odoo, slot_sql)
        evidence.add("slots immediately after stopping the consumer", db.grid(odoo, slot_sql))
        assert all(r[1] == "f" for r in inactive), (
            "the slot is still marked active after the consumer was stopped: %r" % (inactive,)
        )

        # Generate WAL so retention has something to hold on to.
        from helpers import odoo as odoo_helper
        pk = odoo_helper.create_partner(
            "QA slot lag probe", "qa.slotlag@contoh.invalid", "+62-800-000000"
        )
        odoo_helper.write_partner(pk, {"comment": "x" * 20000})
        db.execute(odoo, "SELECT pg_switch_wal();")
        time.sleep(3)

        after = db.query(odoo, slot_sql)
        evidence.add("slots after generating WAL with no consumer", db.grid(odoo, slot_sql))
        grew = [
            (b[0], int(b[3]), int(a[3]))
            for b, a in zip(before, after, strict=False) if int(a[3]) > int(b[3])
        ]
        evidence.add(
            "retained WAL, before -> after (bytes)",
            "\n".join("%s  %d -> %d  (+%d)" % (n, x, y, y - x) for n, x, y in grew) or "no growth",
        )
        assert grew, (
            "retained WAL did not grow while the consumer was stopped and WAL was being written. "
            "Either the slot is not holding anything back, or it has already been invalidated: %r"
            % (after,)
        )
        for name, start, end in grew:
            assert end - start < WARN_BYTES, (
                "this test generated %d bytes of retained WAL on %s, which is at or past the "
                "512 MiB warning threshold. That is far more than intended." % (end - start, name)
            )
        odoo_helper.unlink_partner(pk)
    finally:
        result = loader.start_main()
        evidence.add("loader restarted", "rc=%d" % result.returncode)
        assert result.returncode == 0, "failed to restart the loader; the stack is left degraded"
        time.sleep(8)
        evidence.add("slots after the consumer is back", db.grid(odoo, slot_sql))
        recovered = db.query(odoo, slot_sql)
        assert any(r[1] == "t" for r in recovered), "the slot did not become active again"


@pytest.mark.notyet
def test_alertmanager_receives_the_firing_alert(evidence):
    """End-to-end: Prometheus evaluates the rule and Alertmanager shows it.

    NOT RUN. The observability overlay (`make up-obs`) is not running in this build, and the
    thresholds cannot be reached without generating half a gigabyte of WAL on a shared host. When
    the overlay is up, the honest version of this test lowers the threshold in a *copy* of the rule
    file, loads it into a throwaway Prometheus, and asserts the alert reaches Alertmanager's
    `/api/v2/alerts` -- which tests the delivery path without touching the real thresholds.
    """
    pytest.skip("observability overlay not running and thresholds unreachable safely. NOT RUN.")
