"""Everything the loader does to the warehouse database: landing DDL, writes, and pipeline state.

Contract 05 governs every name here. The landing zone is **append-only**: this module never emits an
``UPDATE`` or a ``DELETE`` against a ``raw.*`` table. A change is a new row; a delete is a tombstone.
"""

from __future__ import annotations

import datetime as dt
import logging

import psycopg2
import psycopg2.extras
from psycopg2 import sql

from .pgoutput import format_lsn
from .policy import ColumnPolicy

_logger = logging.getLogger(__name__)

#: The four bookkeeping columns of contract 05, in the order they are appended to every raw table.
META_COLUMNS = (
    ("_ingested_at", "timestamptz"),
    ("_op", "char(1)"),
    ("_tenant_id", "text"),
    ("_lsn", "pg_lsn"),
)

#: Source types that survive into the landing zone unchanged. Anything else is landed as ``text``:
#: the landing zone's job is fidelity of *content*, and dbt's ``stg_`` models cast. Landing an exotic
#: Odoo enum as its source type would couple the warehouse to an ERP module upgrade.
_PASSTHROUGH_TYPES = {
    "bigint",
    "boolean",
    "bytea",
    "character varying",
    "date",
    "double precision",
    "integer",
    "json",
    "jsonb",
    "numeric",
    "real",
    "smallint",
    "text",
    "time without time zone",
    "timestamp without time zone",
    "timestamp with time zone",
    "uuid",
}


# Hand back json/jsonb as the raw text Postgres sent, rather than letting psycopg2 parse it into a
# dict. Two reasons, both about fidelity of the landing zone:
#   * a parsed dict cannot be re-adapted on insert without a Json() wrapper, and wrapping it would
#     re-serialise with Python's key order -- so the bytes in the warehouse would differ from the
#     bytes in Odoo for no reason;
#   * the pgoutput stream delivers every value as text, so keeping the backfill on text too means
#     both code paths land byte-identical values. A row that differs between snapshot and stream
#     would show up as a spurious "change" in the mart forever.
# Odoo 19 uses jsonb heavily (49 of the 724 columns in scope) for translated and company-dependent
# fields, so this is not an edge case.
psycopg2.extras.register_default_json(loads=lambda value: value)
psycopg2.extras.register_default_jsonb(loads=lambda value: value)


def connect(dsn: str, autocommit: bool = False):
    conn = psycopg2.connect(dsn)
    conn.autocommit = autocommit
    return conn


# ----------------------------------------------------------------------------------------------
# Policy and pipeline state -- contract 05
# ----------------------------------------------------------------------------------------------

PIPELINE_STATE_DDL = """
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE TABLE IF NOT EXISTS warehouse.pipeline_state (
  tenant_id        text NOT NULL,
  source_table     text NOT NULL,
  last_lsn         pg_lsn,
  last_success_at  timestamptz,
  rows_loaded      bigint NOT NULL DEFAULT 0,
  last_error       text,
  failure_count    integer NOT NULL DEFAULT 0,
  slot_name        text,
  PRIMARY KEY (tenant_id, source_table)
);
"""

#: Backfill bookkeeping. Contract 05 fixes the columns of ``pipeline_state``, so resumability state
#: lives in its own Backend-owned table rather than by bolting columns onto a frozen contract table.
BACKFILL_STATE_DDL = """
CREATE TABLE IF NOT EXISTS warehouse.cdc_backfill_state (
  tenant_id        text NOT NULL,
  source_table     text NOT NULL,
  snapshot_lsn     pg_lsn,
  last_pk          bigint NOT NULL DEFAULT 0,
  max_pk           bigint NOT NULL DEFAULT 0,
  rows_done        bigint NOT NULL DEFAULT 0,
  started_at       timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz,
  PRIMARY KEY (tenant_id, source_table)
);
"""


class ColumnPolicyMissing(RuntimeError):
    """``warehouse.column_policy`` does not exist.

    DWH owns that DDL (contract 05). The loader will not create it and will not proceed without it:
    a loader that invents its own policy table is a loader that masks according to its own opinion.
    """


def ensure_pipeline_tables(conn) -> None:
    """Create the Backend-owned metadata tables. Idempotent, and never alters DWH's tables."""
    with conn, conn.cursor() as cur:
        cur.execute(PIPELINE_STATE_DDL)
        cur.execute(BACKFILL_STATE_DDL)


def load_column_policy(conn) -> list:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('warehouse.column_policy') IS NOT NULL")
        if not cur.fetchone()[0]:
            raise ColumnPolicyMissing(
                "warehouse.column_policy does not exist. It is produced by the Data Warehouse "
                "agent (frozen contract 05); the CDC loader reads it and never creates it. "
                "Refusing to start: with no policy there is no classification, and an unclassified "
                "column must never default to 'public'."
            )
        cur.execute(
            "SELECT source_table, source_column, pdp_class, transform, mask_null "
            "FROM warehouse.column_policy"
        )
        return [
            ColumnPolicy(
                source_table=r[0],
                source_column=r[1],
                pdp_class=r[2],
                transform=r[3],
                mask_null=bool(r[4]),
            )
            for r in cur.fetchall()
        ]


def record_success(conn, tenant: str, table: str, lsn: int | None, rows: int, slot: str) -> None:
    """Advance ``warehouse.pipeline_state``. This is what ``meta.last_refreshed_at`` reads."""
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO warehouse.pipeline_state
                (tenant_id, source_table, last_lsn, last_success_at, rows_loaded, last_error,
                 failure_count, slot_name)
            VALUES (%s, %s, %s, now(), %s, NULL, 0, %s)
            ON CONFLICT (tenant_id, source_table) DO UPDATE SET
                last_lsn        = COALESCE(EXCLUDED.last_lsn, warehouse.pipeline_state.last_lsn),
                last_success_at = EXCLUDED.last_success_at,
                rows_loaded     = warehouse.pipeline_state.rows_loaded + EXCLUDED.rows_loaded,
                last_error      = NULL,
                failure_count   = 0,
                slot_name       = EXCLUDED.slot_name
            """,
            (tenant, table, format_lsn(lsn) if lsn else None, rows, slot),
        )


def record_failure(conn, tenant: str, table: str, error: str, slot: str) -> None:
    """Record a failure without clearing the last success -- a stale mart must still say *when*."""
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO warehouse.pipeline_state
                (tenant_id, source_table, last_error, failure_count, slot_name)
            VALUES (%s, %s, %s, 1, %s)
            ON CONFLICT (tenant_id, source_table) DO UPDATE SET
                last_error    = EXCLUDED.last_error,
                failure_count = warehouse.pipeline_state.failure_count + 1,
                slot_name     = EXCLUDED.slot_name
            """,
            (tenant, table, error[:2000], slot),
        )


# ----------------------------------------------------------------------------------------------
# Landing zone DDL
# ----------------------------------------------------------------------------------------------


def landing_column_type(source_type: str, action: str) -> str:
    """Decide the landing column type for one column.

    A hashed column is always ``text``: the digest is 64 hex characters regardless of what the
    source column was, and keeping ``varchar(64)`` here would break the day someone widens a source
    column. A nulled column keeps its source type so dbt's ``stg_`` models still see the shape they
    expect -- it is simply always NULL.
    """
    if action == "hash":
        return "text"
    if source_type in _PASSTHROUGH_TYPES:
        return source_type
    return "text"


def ensure_landing_table(conn, table: str, columns: list) -> None:
    """Create or converge ``raw.<table>``.

    Deliberately additive only: ``CREATE TABLE IF NOT EXISTS`` and ``ADD COLUMN IF NOT EXISTS``,
    never a type change and never a drop. The Data Warehouse agent may ship its own landing DDL in
    ``analytics/warehouse/``; two additive converging writers cannot corrupt each other, whereas a
    loader that "fixes" a column type would silently rewrite DWH's schema.

    ``columns`` is a list of ``(name, type)`` after masking; ``secret`` columns are already absent.
    """
    ident = sql.Identifier("raw", table)
    coldefs = [sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in columns]
    coldefs += [sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(t)) for n, t in META_COLUMNS]
    with conn, conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cur.execute(
            sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(ident, sql.SQL(", ").join(coldefs))
        )
        for name, type_ in list(columns) + list(META_COLUMNS):
            cur.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS {} {}").format(
                    ident, sql.Identifier(name), sql.SQL(type_)
                )
            )
        # Idempotency key. A change's LSN is unique per change, and backfill rows all share the
        # snapshot LSN, so (_tenant_id, id, _lsn) identifies a landing row exactly. With
        # ON CONFLICT DO NOTHING this makes a replayed range a no-op rather than a duplicate --
        # append-only is preserved because a skipped insert modifies nothing.
        cur.execute(
            sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {} (_tenant_id, id, _lsn)").format(
                sql.Identifier("%s_ingest_key" % table), ident
            )
        )
        # Ordering key of contract 05, used by every stg_ model to find the latest version.
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} (_tenant_id, id, _lsn DESC)").format(
                sql.Identifier("%s_latest" % table), ident
            )
        )


def insert_rows(conn, table: str, columns: list, rows: list) -> int:
    """Append masked rows to ``raw.<table>``. Returns the number actually landed.

    ``ON CONFLICT DO NOTHING`` on the ingest key is what makes re-running the loader over the same
    source range produce an identical mart instead of duplicated facts.
    """
    if not rows:
        return 0
    ident = sql.Identifier("raw", table)
    all_columns = list(columns) + [name for name, _ in META_COLUMNS]
    statement = sql.SQL("INSERT INTO {} ({}) VALUES %s ON CONFLICT DO NOTHING").format(
        ident, sql.SQL(", ").join(sql.Identifier(c) for c in all_columns)
    )
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, statement.as_string(cur), rows, page_size=1000)
        return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else len(rows)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
