"""The initial snapshot: a separate code path from steady state, and resumable by construction.

Why separate at all (Backend brief, scope A): a snapshot reads whole tables with ``SELECT`` while
steady state reads a WAL stream. Sharing one code path between them means one of the two is being
emulated by the other, and the emulation is where the bugs live.

**How the two paths meet without losing a row.** Order matters and is enforced by
:func:`bct_cdc.runner`:

1. The publication is created (out of band, as ``odoo``).
2. The replication slot is created. From this instant Postgres retains WAL, so the slot's
   ``consistent_point`` is a floor: every change after it *will* be replayed.
3. The backfill runs, landing rows with ``_lsn`` = the snapshot LSN.
4. Streaming starts from the slot and replays everything since step 2.

A row modified *during* the backfill therefore lands twice: once from the snapshot at the snapshot
LSN, and once from the stream at a strictly higher LSN. Contract 05's mart rule -- latest
non-deleted version per key, ordered by ``_lsn`` -- makes the stream version win. A row deleted
during the backfill lands as a snapshot row plus a higher-LSN tombstone, and disappears from the
mart. That is why this is at-least-once rather than exactly-once, and why at-least-once is enough.

**The snapshot epoch, and why replay is a no-op.** ``_lsn`` for every snapshot row is the *epoch
LSN*: the slot's consistent point, written into ``warehouse.cdc_backfill_state`` on the first chunk
and never re-derived while that row exists -- not even after the backfill completes. Because
``raw.<table>`` carries a unique index on ``(_tenant_id, id, _lsn)`` and inserts use
``ON CONFLICT DO NOTHING``, re-running the same range appends nothing at all.

That durability is load-bearing, and it was not obvious: an earlier version re-derived the epoch LSN
whenever the state row was absent, so a deliberate re-run picked up a *newer* LSN, never conflicted,
and silently doubled the landing table. Deleting the state row is therefore not "re-run the load" --
it is "begin a new snapshot epoch", which is what a re-snapshot after slot invalidation genuinely
needs. The two are different operations and are now spelled differently: ``--reload`` clears
``completed_at`` and keeps the epoch; deleting the row starts a new one and says so in the log.

**Resumability.** Progress is committed to ``warehouse.cdc_backfill_state`` after every chunk, and
paging is by keyset (``WHERE id > last_pk ORDER BY id``), not ``OFFSET``. A kill at 80% resumes at
80%: the next run reads ``last_pk`` and continues. An ``OFFSET`` pager would re-scan everything
before the cursor on every page, which makes resuming *more* expensive than restarting -- which is
how a nominally resumable backfill becomes one nobody dares resume.
"""

from __future__ import annotations

import logging
import time

from . import metrics as m
from . import source as src
from . import warehouse as wh
from .pgoutput import parse_lsn

_logger = logging.getLogger(__name__)


def _landing_has_rows(conn, tenant: str, table: str) -> bool:
    from psycopg2 import sql as _sql

    with conn.cursor() as cur:
        cur.execute(
            _sql.SQL("SELECT EXISTS (SELECT 1 FROM {} WHERE _tenant_id = %s)").format(
                _sql.Identifier("raw", table)
            ),
            (tenant,),
        )
        return bool(cur.fetchone()[0])


def clear_completion(conn, tenant: str, tables=None) -> int:
    """Mark backfills incomplete while KEEPING the snapshot epoch, so a re-run is idempotent."""
    with conn, conn.cursor() as cur:
        if tables:
            cur.execute(
                "UPDATE warehouse.cdc_backfill_state SET completed_at = NULL "
                "WHERE tenant_id = %s AND source_table = ANY(%s)",
                (tenant, list(tables)),
            )
        else:
            cur.execute(
                "UPDATE warehouse.cdc_backfill_state SET completed_at = NULL WHERE tenant_id = %s",
                (tenant,),
            )
        return cur.rowcount


def _get_state(conn, tenant: str, table: str) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_pk, max_pk, rows_done, completed_at, snapshot_lsn::text "
            "FROM warehouse.cdc_backfill_state WHERE tenant_id = %s AND source_table = %s",
            (tenant, table),
        )
        row = cur.fetchone()
    if row is None:
        return {"last_pk": 0, "max_pk": 0, "rows_done": 0, "completed": False, "snapshot_lsn": None}
    return {
        "last_pk": int(row[0]),
        "max_pk": int(row[1]),
        "rows_done": int(row[2]),
        "completed": row[3] is not None,
        "snapshot_lsn": row[4],
    }


def _save_state(conn, cur, tenant: str, table: str, last_pk: int, max_pk: int,
                rows_done: int, snapshot_lsn: str, completed: bool) -> None:
    """Persist progress **in the same transaction as the rows it describes**.

    If the state were committed separately, a crash between the two commits would either lose rows
    (state ahead of data) or duplicate them (data ahead of state). Sharing the transaction makes the
    pair atomic, so a kill at any instant leaves a consistent resume point.
    """
    cur.execute(
        """
        INSERT INTO warehouse.cdc_backfill_state
            (tenant_id, source_table, snapshot_lsn, last_pk, max_pk, rows_done, completed_at)
        VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)
        ON CONFLICT (tenant_id, source_table) DO UPDATE SET
            snapshot_lsn = COALESCE(warehouse.cdc_backfill_state.snapshot_lsn, EXCLUDED.snapshot_lsn),
            last_pk      = EXCLUDED.last_pk,
            max_pk       = EXCLUDED.max_pk,
            rows_done    = EXCLUDED.rows_done,
            completed_at = CASE WHEN %s THEN now() ELSE NULL END
        """,
        (tenant, table, snapshot_lsn, last_pk, max_pk, rows_done, completed, completed),
    )


def backfill_table(
    source_conn,
    warehouse_conn,
    tenant: str,
    table: str,
    plan,
    snapshot_lsn: str,
    slot: str,
    batch_size: int = 2000,
    on_chunk=None,
) -> int:
    """Snapshot one table into ``raw.<table>``. Returns rows landed in *this* run."""
    state = _get_state(warehouse_conn, tenant, table)
    if state["completed"]:
        _logger.info("backfill %s.%s already complete, skipping", tenant, table)
        m.BACKFILL_PROGRESS.labels(tenant=tenant, source_table=table).set(1.0)
        return 0

    if state["snapshot_lsn"]:
        # Reuse the epoch established by the first run. This is what makes a replay a no-op.
        snapshot_lsn = state["snapshot_lsn"]
    elif _landing_has_rows(warehouse_conn, tenant, table):
        # No epoch row, but rows are already landed: this is a NEW epoch over a non-empty table,
        # i.e. a re-snapshot. Legitimate after slot invalidation, and a duplicate-maker otherwise.
        _logger.warning(
            "starting a NEW snapshot epoch (%s) for %s.%s while %s already holds rows. Every row "
            "will be appended again at the new LSN and will win over the old copies. This is "
            "correct after a slot invalidation and wrong if you only meant to re-run the load -- "
            "use --reload for that, which keeps the epoch and makes the replay a no-op.",
            snapshot_lsn, tenant, table, "raw.%s" % table,
        )
    columns = plan.select_columns
    last_pk = state["last_pk"]
    rows_done = state["rows_done"]
    total = src.max_pk(source_conn, table)
    landed = 0

    if last_pk:
        _logger.info(
            "resuming backfill of %s.%s from id > %d (%d rows already landed)",
            tenant, table, last_pk, rows_done,
        )

    while True:
        chunk = src.fetch_chunk(source_conn, table, columns, last_pk, batch_size)
        if not chunk:
            break
        now = wh.utcnow()
        rows = []
        for raw_row in chunk:
            masked = plan.apply(raw_row)
            rows.append(
                tuple(masked[c] for c in columns) + (now, "I", tenant, snapshot_lsn)
            )
        chunk_last_pk = int(chunk[-1]["id"])

        # One transaction: the rows and the progress marker that describes them.
        with warehouse_conn:
            written = wh.insert_rows(warehouse_conn, table, columns, rows)
            with warehouse_conn.cursor() as cur:
                _save_state(
                    warehouse_conn, cur, tenant, table, chunk_last_pk, total,
                    rows_done + len(chunk), snapshot_lsn, completed=False,
                )
        landed += written
        rows_done += len(chunk)
        last_pk = chunk_last_pk

        m.ROWS_TOTAL.labels(tenant=tenant, source_table=table, op="I").inc(written)
        if total:
            m.BACKFILL_PROGRESS.labels(tenant=tenant, source_table=table).set(
                min(1.0, last_pk / float(total))
            )
        m.LAST_SUCCESS.labels(tenant=tenant, source_table=table).set(time.time())
        _logger.info(
            "backfill %s.%s: %d rows (id <= %d of %d)", tenant, table, rows_done, last_pk, total
        )
        if on_chunk is not None:
            # Test hook: lets the resumability test kill the process at a known point.
            on_chunk(table, last_pk, rows_done)

    with warehouse_conn:
        with warehouse_conn.cursor() as cur:
            _save_state(
                warehouse_conn, cur, tenant, table, last_pk, total, rows_done,
                snapshot_lsn, completed=True,
            )
    m.BACKFILL_PROGRESS.labels(tenant=tenant, source_table=table).set(1.0)
    wh.record_success(warehouse_conn, tenant, table, parse_lsn(snapshot_lsn), landed, slot)
    _logger.info("backfill %s.%s complete: %d rows landed this run", tenant, table, landed)
    return landed
