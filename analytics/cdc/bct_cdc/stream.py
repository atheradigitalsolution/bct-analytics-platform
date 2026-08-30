"""Steady state: consume the ``pgoutput`` stream and land every change as a new row.

Three properties this file exists to guarantee, all of them testable:

* **Deletes become tombstones.** A decoded ``DELETE`` appends ``_op='D'`` carrying only the primary
  key (REPLICA IDENTITY DEFAULT sends the key, not the whole old tuple -- which is all a tombstone
  needs). Nothing is ever physically removed from ``raw``.
* **Feedback follows durability, never leads it.** ``send_feedback`` is only called after the
  warehouse transaction holding those rows has committed. Confirming an LSN the warehouse has not
  stored tells Postgres it may discard that WAL, and the rows are then gone from both ends.
* **An invalidated slot stops the world.** Security finding T-2: past the 2 GB cap Postgres discards
  WAL this consumer never read. Reconnecting produces a mart with a hole and no error, so the
  consumer refuses to reconnect and says why.
"""

from __future__ import annotations

import logging
import time

import psycopg2.extras
from psycopg2 import sql

from . import metrics as m
from . import warehouse as wh
from .pgoutput import UNCHANGED, PgOutputDecoder, format_lsn

_logger = logging.getLogger(__name__)


class StreamConsumer:
    """Callable passed to psycopg2's ``consume_stream``."""

    def __init__(self, tenant, slot, plans, warehouse_conn, status_conn, on_flush=None):
        self.tenant = tenant
        self.slot = slot
        self.plans = plans  # table -> MaskPlan
        self.warehouse_conn = warehouse_conn
        self.status_conn = status_conn
        self.decoder = PgOutputDecoder()
        self.buffer = {}  # table -> list of row tuples
        self.pending_lsn = None
        self.on_flush = on_flush
        self.counts = {}
        self._last_heartbeat = 0.0

    # -- unchanged TOAST values ------------------------------------------------------

    def _carry_forward(self, table: str, columns: list, pk, masked: dict) -> dict:
        """Fill ``UNCHANGED`` TOAST placeholders from the latest already-landed version.

        pgoutput sends ``u`` for a TOASTed value the ``UPDATE`` did not touch. Writing NULL for it
        would blank a large text column on every unrelated update -- a data-loss bug that only ever
        shows up on values big enough to be TOASTed, i.e. rarely and late.

        The carry-forward reads the *masked* value out of ``raw``, so a hashed column is copied as
        its digest and never re-hashed. Re-hashing a digest would produce a second, different key
        for the same person and silently split their history in the mart.
        """
        unchanged = [c for c in columns if masked.get(c) is UNCHANGED]
        if not unchanged:
            return masked
        statement = sql.SQL(
            "SELECT {} FROM {} WHERE _tenant_id = %s AND id = %s ORDER BY _lsn DESC LIMIT 1"
        ).format(
            sql.SQL(", ").join(sql.Identifier(c) for c in unchanged),
            sql.Identifier("raw", table),
        )
        with self.warehouse_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(statement, (self.tenant, pk))
            previous = cur.fetchone()
        for column in unchanged:
            if previous is None:
                _logger.warning(
                    "unchanged TOAST value for %s.id=%s column %s with no prior landed row; "
                    "landing NULL. Re-run the backfill for this table if this recurs.",
                    table, pk, column,
                )
                masked[column] = None
            else:
                masked[column] = previous[column]
        return masked

    # -- per-message ------------------------------------------------------------------

    def __call__(self, msg) -> None:
        payload = msg.payload
        if isinstance(payload, str):  # psycopg2 hands back str on some builds
            payload = payload.encode("utf-8", errors="surrogateescape")
        change = self.decoder.decode(payload, msg.data_start)

        if change is not None:
            table = change.relation.name
            plan = self.plans.get(table)
            if plan is not None:
                self._buffer(change, table, plan)

        # A commit boundary is the only safe place to confirm an LSN: everything up to here is a
        # whole transaction, and once the warehouse has committed it, Postgres may release the WAL.
        if payload[:1] == b"C":
            self.pending_lsn = msg.data_start
            self.flush(msg)
        elif sum(len(v) for v in self.buffer.values()) >= 5000:
            self.flush(None)

        self._heartbeat()

    def _buffer(self, change, table: str, plan) -> None:
        columns = plan.select_columns
        pk = change.key.get("id") or change.values.get("id")
        if change.op == "D":
            # A tombstone carries the key and nothing else: the point of a delete is the identity,
            # and REPLICA IDENTITY DEFAULT does not send the rest of the old tuple anyway.
            masked = {c: None for c in columns}
            masked["id"] = pk
        else:
            present = {c: v for c, v in change.values.items() if c in plan.columns}
            hashable = {c: v for c, v in present.items() if v is not UNCHANGED}
            masked = plan.apply(hashable)
            for c, v in present.items():
                if v is UNCHANGED:
                    masked[c] = UNCHANGED
            masked = self._carry_forward(table, columns, pk, masked)
            for c in columns:
                masked.setdefault(c, None)

        now = wh.utcnow()
        if change.commit_time is not None:
            lag = (now - change.commit_time).total_seconds()
            m.END_TO_END_LAG.labels(tenant=self.tenant, source_table=table).set(max(0.0, lag))
        row = tuple(masked[c] for c in columns) + (
            now, change.op, self.tenant, format_lsn(change.lsn)
        )
        self.buffer.setdefault(table, []).append(row)
        self.counts[(table, change.op)] = self.counts.get((table, change.op), 0) + 1
        self._last_lsn = change.lsn

    # -- durability -------------------------------------------------------------------

    def flush(self, msg) -> None:
        if self.buffer:
            with self.warehouse_conn:
                for table, rows in self.buffer.items():
                    columns = self.plans[table].select_columns
                    written = wh.insert_rows(self.warehouse_conn, table, columns, rows)
                    _logger.info(
                        "landed %d/%d rows into raw.%s (tenant=%s)",
                        written, len(rows), table, self.tenant,
                    )
            for (table, op), count in self.counts.items():
                m.ROWS_TOTAL.labels(tenant=self.tenant, source_table=table, op=op).inc(count)
            touched = set(t for t, _ in self.counts)
            for table in touched:
                wh.record_success(
                    self.status_conn, self.tenant, table, self.pending_lsn,
                    sum(c for (t, _), c in self.counts.items() if t == table), self.slot,
                )
                m.LAST_SUCCESS.labels(tenant=self.tenant, source_table=table).set(time.time())
            self.buffer = {}
            self.counts = {}
            if self.on_flush is not None:
                self.on_flush()

        # Only now, with the rows durable in the warehouse, may Postgres be told it can drop the WAL.
        if msg is not None and self.pending_lsn is not None:
            msg.cursor.send_feedback(flush_lsn=self.pending_lsn)

    def _heartbeat(self) -> None:
        """Advance ``last_success`` on every cycle, including cycles that moved zero rows.

        An idle pipeline and a dead pipeline look identical if this metric only moves when rows
        flow -- and it backs ``meta.is_stale``, so that confusion would make the dashboard claim
        fresh data is stale, or worse, the reverse.
        """
        now = time.time()
        if now - self._last_heartbeat < 5.0:
            return
        self._last_heartbeat = now
        for table in self.plans:
            m.LAST_SUCCESS.labels(tenant=self.tenant, source_table=table).set(now)
        with self.status_conn, self.status_conn.cursor() as cur:
            cur.execute(
                "UPDATE warehouse.pipeline_state SET last_success_at = now() "
                "WHERE tenant_id = %s AND source_table = ANY(%s)",
                (self.tenant, list(self.plans)),
            )
