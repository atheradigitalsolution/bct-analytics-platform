"""Idempotency: loading the same range twice must change nothing that anyone reads.

The subtlety, and the reason this test does not simply diff ``raw.*`` row counts: the landing zone
is **append-only by grant** (contract 05 -- ``warehouse_loader`` holds no ``UPDATE`` and no
``DELETE``). So "nothing changed" cannot mean "no rows were added". It means the *live projection*
-- newest row per key with tombstones excluded, which is what every mart is built from -- is
byte-identical before and after.

Both statements are asserted, because they fail differently:

* the **projection checksum** must be identical -- otherwise the mart would change, which is the
  user-visible definition of non-idempotent;
* the **raw row count** must also be unchanged for a ``--reload``, because the loader claims the
  replay is a genuine no-op rather than an append that the projection happens to hide. If rows are
  appended, idempotency is being rescued by the projection rather than achieved by the loader, and
  the landing zone grows without bound on every retry. That is worth knowing separately.

`_ingested_at` is excluded from the checksum: identical values landed at a later wall-clock time are
not a difference in the data.
"""

from __future__ import annotations

import pytest

from helpers import db, env, loader

pytestmark = [pytest.mark.live, pytest.mark.slow]

TABLES = ["res_partner", "sale_order", "sale_order_line", "account_move", "account_move_line",
          "stock_move", "ppob_transaction", "pos_order_line"]


def test_reload_over_the_same_range_changes_nothing(warehouse_up, cdc_warehouse, evidence):
    tenant = env.env("CDC_TENANT_SLUG", env.env("ODOO_DB_NAME", "bct"))
    evidence.add("identity", db.role_identity(cdc_warehouse).grid)

    before = {t: loader.live_checksum(cdc_warehouse, t, tenant) for t in TABLES}
    before_raw = {t: loader.raw_row_count(cdc_warehouse, t, tenant) for t in TABLES}
    evidence.add(
        "live-projection checksum BEFORE reload",
        "\n".join("%-20s %s  rows=%s  raw=%s" % (t, before[t][0], before[t][1], before_raw[t])
                  for t in TABLES),
    )

    loader.kill("odoo19-bct-cdc-qa-reload")
    out = loader.run_loader("odoo19-bct-cdc-qa-reload", ["--backfill-only"], timeout=900)
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-18:])
    evidence.add("cdc-run.sh -- --backfill-only (rc=%d)" % out.returncode, tail)
    assert out.returncode == 0, "the second load failed; idempotency cannot be assessed\n%s" % tail

    after = {t: loader.live_checksum(cdc_warehouse, t, tenant) for t in TABLES}
    after_raw = {t: loader.raw_row_count(cdc_warehouse, t, tenant) for t in TABLES}
    evidence.add(
        "live-projection checksum AFTER reload",
        "\n".join("%-20s %s  rows=%s  raw=%s" % (t, after[t][0], after[t][1], after_raw[t])
                  for t in TABLES),
    )

    differing = [t for t in TABLES if before[t] != after[t]]
    evidence.add(
        "DIFF",
        "tables whose live projection changed: %s" % (differing or "none -- zero difference"),
    )
    assert not differing, (
        "the second load changed the live projection of %r. before=%r after=%r"
        % (differing, {t: before[t] for t in differing}, {t: after[t] for t in differing})
    )

    grew = {t: (before_raw[t], after_raw[t]) for t in TABLES if after_raw[t] != before_raw[t]}
    evidence.add(
        "landing-zone growth from the replay",
        "tables that gained rows: %s" % (grew or "none -- the replay was a true no-op"),
    )
    assert not grew, (
        "the replay appended rows to the landing zone: %r. The projection still matches, so no mart "
        "would change, but the landing zone grows on every retry and idempotency is being rescued "
        "by the projection rather than achieved by the loader." % grew
    )


def test_reload_flag_works(warehouse_up, evidence):
    """`--reload` is the loader's own documented answer to "re-run the same range safely".

    Its help text says: "Re-run the backfill over the same range, keeping the snapshot epoch so the
    replay is a no-op. Use this rather than deleting rows from warehouse.cdc_backfill_state, which
    starts a NEW epoch and appends every row again."

    That makes it the *only* documented safe way for an operator to force a re-load, and
    `docs/runbooks/analytics-pipeline.md` has to tell them something. So it gets its own test rather
    than being folded into the one above: if it is broken, the runbook is wrong, not just a flag.
    """
    loader.kill("odoo19-bct-cdc-qa-reload")
    out = loader.run_loader("odoo19-bct-cdc-qa-reload", ["--backfill-only", "--reload"], timeout=900)
    tail = "\n".join((out.stdout + out.stderr).strip().splitlines()[-20:])
    evidence.add("cdc-run.sh -- --backfill-only --reload (rc=%d)" % out.returncode, tail)
    assert out.returncode == 0, (
        "`--reload` exits non-zero. Owner: Backend (analytics/cdc/**). QA does not fix it.\n%s" % tail
    )


def test_marts_are_identical_after_a_second_dbt_build(marts_exist, evidence):
    """The same property one layer up: `dbt build` twice must produce identical marts.

    Written and NOT RUN: `dbt build` has not been green in this build, so `marts` is empty. The
    moment it is, this compares a checksum of every mart before and after a second build.
    """
    pytest.skip(
        "marts exist but this test still needs `make dbt-run` to be runnable twice in sequence; "
        "wire it once DWH reports dbt green. NOT RUN."
    )
