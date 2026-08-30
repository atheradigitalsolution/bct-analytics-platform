#!/usr/bin/env python3
"""warehouse_ctl — policy sync, landing-zone DDL, FDW wiring and the dev fixture load.

WHAT THIS IS, AND WHAT IT IS NOT
================================
This is the **Data Warehouse agent's** tooling. It runs inside the `dbt`
container (which already carries psycopg2 and can reach both databases), never
on the host, so it has no host Python dependency and its credentials come from
compose rather than from a shell.

It is **not the CDC loader.** `analytics/cdc/**` is the Backend agent's and is
the only thing that streams `pgoutput`. What lives here is the three jobs that
are unambiguously DWH's under the brief, plus one development affordance that
is labelled as such:

  sync-policy   Read `pdp.field.classification` out of Odoo and materialise
                `warehouse.column_policy`. This is the seam of contract 05:
                DWH writes the policy, Backend's loader executes it.
  gen-raw-ddl   Generate `raw.*` from that policy. DWH owns landing DDL
                because CREATE TABLE is where "no unclassified column can
                land" and "a secret column does not exist" stop being
                conventions and become structural facts.
  gen-fdw       Wire the reconciliation path: foreign tables over the Odoo
                database, as `warehouse_reader`, with an explicit column list
                that contains no `secret` column at all.
  load-fixture  A DEVELOPMENT SNAPSHOT LOAD. It applies the same policy
                through the same HMAC to populate `raw.*` so the marts can be
                built and tested before, and independently of, Backend's
                consumer. It is a fixture, not a pipeline: no WAL, no slot, no
                resumability. Backend's loader writes the same tables and
                supersedes it (its rows carry a real `_lsn`, which sorts after
                every fixture row).
  tombstone     Append `_op='D'` rows, to exercise the delete semantics ADR
                0001 requires be tested.
  verify        Assert every column about to land carries a policy row, and
                that no `hmac_sha256` transform points at a non-text column.

USAGE
    docker compose -p odoo19-bct -f ... run --rm --entrypoint python \\
        dbt /warehouse/bin/warehouse_ctl.py <command> [--tenant bct]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Iterable

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# The replicated source set.
#
# Deliberately explicit rather than "every table Odoo has". A warehouse that
# replicates whatever it finds inherits every future module's columns without
# a classification decision having been made about them, which is exactly the
# failure contract 01 exists to prevent.
#
# `res_users` is absent on purpose: no mart in the metric contract needs it,
# and it is the table that carries `password` and `totp_secret`. The `secret`
# exclusion is still proven — sale_order.access_token, account_move.access_token,
# account_move.inalterable_hash, pos_order.access_token and pos_order.ticket_code
# are all `secret` and all live on tables that ARE replicated.
# ---------------------------------------------------------------------------
SOURCE_TABLES: tuple[str, ...] = (
    "res_company",
    "res_partner",
    "product_template",
    "product_product",
    "operating_unit",
    "sale_order",
    "sale_order_line",
    "account_move",
    "account_move_line",
    "stock_picking",
    "stock_move",
    "pos_order",
    "pos_order_line",
    "ppob_biller",
    "ppob_transaction",
)

# Physical table -> Odoo model, for looking the classification up. Odoo's own
# convention is dots to underscores, but pos.order.line -> pos_order_line is
# ambiguous in reverse (pos_order_line could be pos.order_line), so the map is
# written out rather than derived.
TABLE_TO_MODEL: dict[str, str] = {
    "res_company": "res.company",
    "res_partner": "res.partner",
    "product_template": "product.template",
    "product_product": "product.product",
    "operating_unit": "operating.unit",
    "sale_order": "sale.order",
    "sale_order_line": "sale.order.line",
    "account_move": "account.move",
    "account_move_line": "account.move.line",
    "stock_picking": "stock.picking",
    "stock_move": "stock.move",
    "pos_order": "pos.order",
    "pos_order_line": "pos.order.line",
    "ppob_biller": "ppob.biller",
    "ppob_transaction": "ppob.transaction",
}

# ---------------------------------------------------------------------------
# contract 05's class -> transform mapping. "Not negotiable" in the contract,
# so it is a constant here and a CHECK constraint in the database. Two places,
# because a constant can be edited and a constraint cannot be edited by
# accident.
# ---------------------------------------------------------------------------
CLASS_TO_TRANSFORM: dict[str, str] = {
    "public": "none",
    "internal": "none",
    "personal": "hmac_sha256",
    "sensitive": "hmac_sha256_nullable",
    "secret": "drop",
}

# ---------------------------------------------------------------------------
# Rulings recorded in contract 01 that the addon's committed seed has not yet
# caught up with. Each entry cites the commit that made the ruling and is
# announced loudly on every run, so it can never quietly become the DWH agent
# inventing a classification — which contract 01 forbids.
#
# Remove an entry the moment custom_pdp_core's CSV agrees; the script says so
# when that happens.
# ---------------------------------------------------------------------------
CONTRACT_01_OVERRIDES: dict[tuple[str, str], tuple[str, bool, str]] = {
    # (model, field): (pdp_class, drop_to_null, why)
    #
    # EMPTY, and that is the correct state. The mechanism stays because it was
    # needed once and will be needed again: on 2026-08-31 contract 01 was
    # amended (Lead ruling 064d3c2) to reclassify res.partner.barcode from
    # `personal` to `sensitive` + drop_to_null, and for a short window the
    # ruling existed in the contract while custom_pdp_core's committed seed
    # still said `personal`. Platform-Addons has since regenerated the seed and
    # the registry agrees, so the override was removed rather than left to rot.
    #
    # RULES for adding one:
    #   * it must cite the Lead's ruling commit;
    #   * it is announced on every run, never silent;
    #   * the script says "NO LONGER NEEDED" the moment the registry catches
    #     up, so an override cannot quietly become the DWH agent inventing a
    #     classification -- which contract 01 forbids outright.
}

METADATA_COLUMNS = """  _row_id      bigint GENERATED ALWAYS AS IDENTITY,
  _ingested_at timestamptz NOT NULL DEFAULT now(),
  _op          char(1)     NOT NULL CHECK (_op IN ('I','U','D')),
  _tenant_id   text        NOT NULL,
  _lsn         pg_lsn"""

TEXTUAL_TYPES = {"text", "varchar", "bpchar", "char", "name", "citext"}


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def connect_odoo(database: str):
    """Read-only connection to the Odoo OLTP database.

    ALWAYS as warehouse_reader. That role holds SELECT + REPLICATION and
    nothing else (contract 04 §2), so "never write to the Odoo database" is
    guaranteed by the role rather than by this code being careful.
    """
    return psycopg2.connect(
        host=os.environ.get("ODOO_PG_HOST", "postgres"),
        port=int(os.environ.get("ODOO_PG_PORT", "5432")),
        dbname=database,
        user=os.environ["WAREHOUSE_READER_USER"],
        password=os.environ["WAREHOUSE_READER_PASSWORD"],
        application_name="warehouse_ctl",
    )


def connect_warehouse(admin: bool = False):
    """Connection to the warehouse.

    `admin` is needed only for CREATE SERVER / CREATE USER MAPPING, which are
    superuser-only operations. Everything else runs as `warehouse`.
    """
    user = os.environ["WAREHOUSE_ADMIN_USER"] if admin else os.environ["WAREHOUSE_DB_USER"]
    pwd = os.environ["WAREHOUSE_ADMIN_PASSWORD"] if admin else os.environ["WAREHOUSE_DB_PASSWORD"]
    return psycopg2.connect(
        host=os.environ.get("WAREHOUSE_HOST", "warehouse-db"),
        port=int(os.environ.get("WAREHOUSE_PORT", "5432")),
        dbname=os.environ["WAREHOUSE_DB"],
        user=user,
        password=pwd,
        application_name="warehouse_ctl",
    )


def tenants(wh) -> list[dict]:
    with wh.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT tenant_id, source_database, mask_salt_env, is_test_tenant "
            "FROM warehouse.tenant_registry WHERE active ORDER BY is_test_tenant, tenant_id"
        )
        return list(cur.fetchall())


def salt_for(tenant: dict) -> str:
    """Resolve a tenant's HMAC salt from the environment.

    The registry stores the NAME of the variable, never the value (contract 01:
    the salt lives in SOPS, never in a file, never in git). An absent or empty
    salt is fatal — degrading to an unkeyed hash is item 11 of the pinned
    construction and is never acceptable.
    """
    env_name = tenant["mask_salt_env"]
    salt = os.environ.get(env_name, "")
    if not salt:
        # The documented fallback order from custom_pdp_masking §2: tenant
        # variable, then DEFAULT.
        salt = os.environ.get("WAREHOUSE_MASK_SALT_DEFAULT", "")
    if not salt:
        sys.exit(
            f"FATAL: no HMAC salt for tenant {tenant['tenant_id']}. Expected {env_name} "
            f"or WAREHOUSE_MASK_SALT_DEFAULT in the environment. Refusing to load: an "
            f"unkeyed or empty-salt digest is not masking."
        )
    return salt


# ---------------------------------------------------------------------------
# Source introspection
# ---------------------------------------------------------------------------
def source_columns(odoo, table: str) -> list[dict]:
    """Physical columns of a source table, with their exact rendered types.

    format_type() rather than information_schema.data_type because the latter
    renders `character varying` without its length and `numeric` without its
    precision, and the landing table has to be able to hold what the source
    holds.
    """
    sql = """
        SELECT a.attname                                  AS column_name,
               format_type(a.atttypid, a.atttypmod)       AS col_type,
               t.typname                                  AS udt_name,
               a.attnum                                   AS ordinal
        FROM pg_attribute a
        JOIN pg_class     c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_type      t ON t.oid = a.atttypid
        WHERE n.nspname = 'public'
          AND c.relname = %s
          AND a.attnum > 0
          AND NOT a.attisdropped
        ORDER BY a.attnum
    """
    with odoo.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (table,))
        return list(cur.fetchall())


def classification_map(odoo) -> dict[tuple[str, str], dict]:
    """The active rows of custom_pdp_core's registry, keyed by (model, field).

    Read straight from the table rather than through JSON-RPC. The registry's
    MODULE_KNOWLEDGE documents a JSON-RPC surface for the loader; DWH is
    already connected to this database read-only for reconciliation, and a
    second protocol would be a second way for the two to disagree.
    """
    with odoo.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT model_name, field_name, pdp_class, drop_to_null "
            "FROM pdp_field_classification WHERE active"
        )
        rows = cur.fetchall()
    out: dict[tuple[str, str], dict] = {}
    for r in rows:
        out[(r["model_name"], r["field_name"])] = dict(r)

    # Apply the Lead's contract 01 rulings, loudly.
    for (model, field), (klass, drop_to_null, why) in CONTRACT_01_OVERRIDES.items():
        current = out.get((model, field))
        if current is None:
            print(f"  NOTE  override for {model}.{field} targets a column absent from the registry; skipped")
            continue
        if current["pdp_class"] == klass and bool(current["drop_to_null"]) == drop_to_null:
            print(
                f"  NOTE  contract-01 override for {model}.{field} is NO LONGER NEEDED - "
                f"custom_pdp_core's seed already agrees. Remove it from CONTRACT_01_OVERRIDES."
            )
            continue
        print(
            f"  OVERRIDE  {model}.{field}: registry says "
            f"{current['pdp_class']}/drop_to_null={current['drop_to_null']}, "
            f"contract 01 says {klass}/drop_to_null={drop_to_null}."
        )
        print(f"            {why}")
        print(
            f"            The addon seed (addons/custom_pdp_core/data/pdp.field.classification.csv) "
            f"has NOT caught up. Platform-Addons must regenerate it."
        )
        out[(model, field)] = {
            "model_name": model,
            "field_name": field,
            "pdp_class": klass,
            "drop_to_null": drop_to_null,
        }
    return out


def resolve_policy(odoo) -> tuple[list[tuple], list[str]]:
    """Build the column_policy rows, and the list of unclassified columns.

    An unclassified column is returned rather than defaulted. Contract 01 is
    explicit that unclassified is a hard failure and never a silent `public`.
    """
    cmap = classification_map(odoo)
    rows: list[tuple] = []
    unclassified: list[str] = []
    type_violations: list[str] = []

    for table in SOURCE_TABLES:
        model = TABLE_TO_MODEL[table]
        for col in source_columns(odoo, table):
            hit = cmap.get((model, col["column_name"]))
            if hit is None:
                unclassified.append(f"{model}.{col['column_name']} (physical {table}.{col['column_name']})")
                continue
            klass = hit["pdp_class"]
            transform = CLASS_TO_TRANSFORM[klass]
            mask_null = bool(hit["drop_to_null"]) and klass == "sensitive"

            # THE GUARD THE LEAD MADE BINDING (contract 01, general rule 2).
            # "Hard-fail on unclassified" alone would not have caught
            # res.partner.barcode: it WAS classified, as `personal`, but its
            # physical type is jsonb and the pinned HMAC construction takes
            # str or None and nothing else. A digest transform pointed at a
            # non-text column is a contract error, not a loader bug.
            if transform.startswith("hmac") and not mask_null:
                if col["udt_name"] not in TEXTUAL_TYPES:
                    type_violations.append(
                        f"{model}.{col['column_name']}: class={klass} -> {transform}, "
                        f"but the physical type is {col['col_type']} ({col['udt_name']}), not text"
                    )
                    continue
            rows.append((table, col["column_name"], klass, transform, mask_null))

    if type_violations:
        print("\nFATAL: a digest transform points at a non-text column.", file=sys.stderr)
        for v in type_violations:
            print(f"  - {v}", file=sys.stderr)
        print(
            "\nThis is a contract 01 question, not a loader bug. Either the column is "
            "reclassified sensitive+drop_to_null, or contract 01 pins an exact text "
            "rendering. Escalate; do not cast it here.",
            file=sys.stderr,
        )
        sys.exit(3)

    return rows, unclassified


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_sync_policy(args) -> int:
    wh = connect_warehouse()
    src_db = os.environ.get("ODOO_DB_NAME", "bct")
    odoo = connect_odoo(src_db)
    print(f"==> reading pdp.field.classification from Odoo database {src_db}")
    rows, unclassified = resolve_policy(odoo)

    if unclassified:
        print("\nFATAL: columns with no classification row.", file=sys.stderr)
        for u in unclassified:
            print(f"  - {u}", file=sys.stderr)
        print(
            "\nContract 01: unclassified is a hard failure, never a silent default to "
            "`public`. Add the rows to custom_pdp_core's seed and reinstall the module.",
            file=sys.stderr,
        )
        return 2

    with wh.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            "INSERT INTO warehouse.column_policy "
            "(source_table, source_column, pdp_class, transform, mask_null) VALUES %s "
            "ON CONFLICT (source_table, source_column) DO UPDATE SET "
            "  pdp_class = EXCLUDED.pdp_class, transform = EXCLUDED.transform, "
            "  mask_null = EXCLUDED.mask_null, updated_at = now()",
            rows,
        )
        # Remove rows for columns that no longer exist upstream. A stale policy
        # row is not harmless: it makes a dropped column look classified and
        # hides the schema change that ADR 0001 says must be loud.
        cur.execute(
            "DELETE FROM warehouse.column_policy p "
            "WHERE NOT EXISTS (SELECT 1 FROM (VALUES %s) AS v(t, c) "
            "                  WHERE v.t = p.source_table AND v.c = p.source_column)"
            % ",".join(cur.mogrify("(%s,%s)", (r[0], r[1])).decode() for r in rows)
        )
        removed = cur.rowcount
    wh.commit()

    with wh.cursor() as cur:
        cur.execute("SELECT pdp_class, count(*) FROM warehouse.column_policy GROUP BY 1 ORDER BY 1")
        counts = cur.fetchall()
    print(f"==> warehouse.column_policy: {len(rows)} rows upserted, {removed} stale rows removed")
    for klass, n in counts:
        print(f"    {klass:<10} {n}")
    return 0


def _landing_ddl(odoo, wh, table: str) -> str:
    with wh.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT source_column, pdp_class, transform, mask_null "
            "FROM warehouse.column_policy WHERE source_table = %s",
            (table,),
        )
        pol = {r["source_column"]: r for r in cur.fetchall()}

    lines: list[str] = []
    dropped: list[str] = []
    for col in source_columns(odoo, table):
        p = pol.get(col["column_name"])
        if p is None:
            raise SystemExit(
                f"FATAL: {table}.{col['column_name']} has no policy row. Run sync-policy first; "
                f"if it still fails, the column is unclassified and that is a hard failure."
            )
        if p["transform"] == "drop":
            # NOT "selected and discarded" — the column has no name in the
            # landing table at all, so nothing downstream can ask for it.
            dropped.append(f"{col['column_name']} ({p['pdp_class']})")
            continue
        if p["transform"].startswith("hmac") and not p["mask_null"]:
            coltype = "text"            # a 64-character lowercase hex digest
        else:
            coltype = col["col_type"]   # verbatim, or always-NULL for mask_null
        lines.append(f'  "{col["column_name"]}" {coltype},')

    ddl = [
        f"-- raw.{table} — GENERATED by warehouse_ctl.py gen-raw-ddl. Do not hand-edit.",
    ]
    if dropped:
        ddl.append(f"-- `secret` columns structurally absent: {', '.join(dropped)}")
    ddl += [
        f"CREATE TABLE IF NOT EXISTS raw.{table} (",
        *lines,
        METADATA_COLUMNS,
        ");",
        # Contract 05: "Ordering key is (_tenant_id, <pk>, _lsn)". Every Odoo
        # table has an integer `id`, so the pk is always `id`.
        f"CREATE INDEX IF NOT EXISTS {table}_order_idx ON raw.{table} (_tenant_id, id, _lsn);",
        f"CREATE INDEX IF NOT EXISTS {table}_ingested_idx ON raw.{table} (_tenant_id, _ingested_at);",
    ]
    return "\n".join(ddl)


def cmd_gen_raw_ddl(args) -> int:
    wh = connect_warehouse()
    odoo = connect_odoo(os.environ.get("ODOO_DB_NAME", "bct"))
    stmts = [_landing_ddl(odoo, wh, t) for t in SOURCE_TABLES]
    sql = "\n\n".join(stmts)
    if args.print_only:
        print(sql)
        return 0
    with wh.cursor() as cur:
        cur.execute(sql)
    wh.commit()
    with wh.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='raw'"
        )
        n = cur.fetchone()[0]
    print(f"==> raw schema: {n} landing tables present")

    # Prove the `secret` exclusion rather than assert it.
    with wh.cursor() as cur:
        cur.execute(
            """
            SELECT p.source_table, p.source_column
            FROM warehouse.column_policy p
            JOIN information_schema.columns c
              ON c.table_schema = 'raw'
             AND c.table_name   = p.source_table
             AND c.column_name  = p.source_column
            WHERE p.pdp_class = 'secret'
            """
        )
        leaked = cur.fetchall()
    if leaked:
        print(f"FATAL: secret columns present in raw: {leaked}", file=sys.stderr)
        return 4
    with wh.cursor() as cur:
        cur.execute("SELECT count(*) FROM warehouse.column_policy WHERE pdp_class='secret'")
        n_secret = cur.fetchone()[0]
    print(f"==> {n_secret} `secret` columns exist in the policy and NONE of them exists in raw")
    return 0


def cmd_gen_fdw(args) -> int:
    """Create one foreign server + schema per tenant over the Odoo database.

    Used by reconciliation (a mart must be compared against Odoo, not against
    a control total the warehouse computed for itself) and by load-fixture.

    Containment, both enforced rather than documented:
      * the user mapping is warehouse_reader, which cannot write to Odoo;
      * the foreign tables are created with an EXPLICIT column list from the
        policy, so no `secret` column exists as a name the warehouse can type.
    """
    wh_admin = connect_warehouse(admin=True)
    wh = connect_warehouse()
    odoo_host = os.environ.get("ODOO_PG_HOST", "postgres")
    odoo_port = os.environ.get("ODOO_PG_PORT", "5432")
    reader = os.environ["WAREHOUSE_READER_USER"]
    reader_pw = os.environ["WAREHOUSE_READER_PASSWORD"]
    wh_user = os.environ["WAREHOUSE_DB_USER"]

    for t in tenants(wh):
        tid = t["tenant_id"]
        server = f"odoo_src_{tid}"
        schema = f"src_{tid}"
        odoo = connect_odoo(t["source_database"])
        with wh_admin.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_foreign_server WHERE srvname = %s", (server,)
            )
            if not cur.fetchone():
                cur.execute(
                    f"CREATE SERVER {server} FOREIGN DATA WRAPPER postgres_fdw "
                    f"OPTIONS (host %s, port %s, dbname %s, "
                    # updatable=false is belt-and-braces on top of a role that
                    # cannot write: postgres_fdw will refuse the statement
                    # locally before it ever reaches Odoo.
                    f"        updatable 'false', fetch_size '10000')",
                    (odoo_host, odoo_port, t["source_database"]),
                )
            cur.execute(
                "SELECT 1 FROM pg_user_mappings WHERE srvname = %s AND usename = %s",
                (server, wh_user),
            )
            if not cur.fetchone():
                cur.execute(
                    f"CREATE USER MAPPING FOR {wh_user} SERVER {server} "
                    f"OPTIONS (user %s, password %s)",
                    (reader, reader_pw),
                )
            cur.execute(f"GRANT USAGE ON FOREIGN SERVER {server} TO {wh_user}")
            # Created by the admin WITH AUTHORIZATION, not by `warehouse`
            # itself: CREATE SCHEMA needs CREATE on the database, and granting
            # the transform role that privilege would let it create schemas
            # outside the four contract 05 names for no benefit.
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {wh_user}")
        wh_admin.commit()

        with wh.cursor() as cur:
            for table in SOURCE_TABLES:
                cur.execute(
                    "SELECT source_column, transform FROM warehouse.column_policy "
                    "WHERE source_table = %s AND transform <> 'drop'",
                    (table,),
                )
                allowed = {r[0] for r in cur.fetchall()}
                cols = [c for c in source_columns(odoo, table) if c["column_name"] in allowed]
                if not cols:
                    raise SystemExit(f"FATAL: no policy rows for {table}; run sync-policy first")
                coldef = ",\n".join(f'  "{c["column_name"]}" {c["col_type"]}' for c in cols)
                cur.execute(f"DROP FOREIGN TABLE IF EXISTS {schema}.{table} CASCADE")
                cur.execute(
                    f"CREATE FOREIGN TABLE {schema}.{table} (\n{coldef}\n) "
                    f"SERVER {server} OPTIONS (schema_name 'public', table_name '{table}')"
                )
        wh.commit()
        print(f"==> {schema}: {len(SOURCE_TABLES)} foreign tables over {t['source_database']} as {reader}")
    return 0


def _mask_expr(col: dict, pol: dict) -> str:
    """The SQL that applies one column's policy. This is the policy EXECUTED."""
    name = f'"{col["column_name"]}"'
    if pol["transform"] == "none":
        return name
    if pol["mask_null"]:
        # `sensitive` free text and the company-dependent jsonb: NULL, typed,
        # so the landing column keeps its shape and holds nothing.
        return f'NULL::{col["col_type"]}'
    # hmac_sha256 / hmac_sha256_nullable without mask_null.
    return f"warehouse.pdp_hmac({name}::text, %(salt)s)"


def cmd_load_fixture(args) -> int:
    wh = connect_warehouse()
    total = 0
    for t in tenants(wh):
        if args.tenant and t["tenant_id"] != args.tenant:
            continue
        tid = t["tenant_id"]
        salt = salt_for(t)
        odoo = connect_odoo(t["source_database"])
        schema = f"src_{tid}"
        print(f"==> loading tenant {tid} from {schema} (test tenant: {t['is_test_tenant']})")
        for table in SOURCE_TABLES:
            with wh.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT source_column, transform, mask_null FROM warehouse.column_policy "
                    "WHERE source_table = %s",
                    (table,),
                )
                pol = {r["source_column"]: r for r in cur.fetchall()}
            cols = [c for c in source_columns(odoo, table) if pol.get(c["column_name"], {}).get("transform") != "drop"]
            target = ", ".join(f'"{c["column_name"]}"' for c in cols)
            exprs = ", ".join(_mask_expr(c, pol[c["column_name"]]) for c in cols)
            sql = (
                f"INSERT INTO raw.{table} ({target}, _op, _tenant_id, _lsn) "
                f"SELECT {exprs}, 'I', %(tenant)s, NULL FROM {schema}.{table}"
            )
            with wh.cursor() as cur:
                cur.execute(sql, {"salt": salt, "tenant": tid})
                n = cur.rowcount
                # pipeline_state is the ONLY source of meta.last_refreshed_at.
                # Writing it here means the freshness a dashboard shows after a
                # fixture load is real metadata, not a fabricated timestamp.
                cur.execute(
                    "INSERT INTO warehouse.pipeline_state "
                    "  (tenant_id, source_table, last_success_at, rows_loaded, slot_name) "
                    "VALUES (%s, %s, now(), %s, NULL) "
                    "ON CONFLICT (tenant_id, source_table) DO UPDATE SET "
                    "  last_success_at = now(), "
                    "  rows_loaded = warehouse.pipeline_state.rows_loaded + EXCLUDED.rows_loaded, "
                    "  last_error = NULL, failure_count = 0",
                    (tid, table, n),
                )
            total += n
            print(f"    raw.{table:<22} {n:>6} rows")
        wh.commit()
    print(f"==> {total} rows landed")
    return 0


def cmd_tombstone(args) -> int:
    """Append `_op='D'` rows so the delete semantics can be exercised.

    ADR 0001: a decoded DELETE lands as a tombstone; the landing zone stays
    append-only; marts filter to the latest non-deleted version per key. This
    is what makes that testable without waiting for somebody to delete a real
    record in Odoo.
    """
    wh = connect_warehouse()
    with wh.cursor() as cur:
        cur.execute(
            f"INSERT INTO raw.{args.table} (id, _op, _tenant_id, _lsn) "
            f"SELECT %s, 'D', %s, NULL",
            (args.id, args.tenant),
        )
    wh.commit()
    print(f"==> tombstone appended: raw.{args.table} id={args.id} tenant={args.tenant}")
    return 0


def cmd_verify(args) -> int:
    """Standalone re-check of the two invariants, for CI and for a human."""
    odoo = connect_odoo(os.environ.get("ODOO_DB_NAME", "bct"))
    rows, unclassified = resolve_policy(odoo)
    ok = True
    if unclassified:
        ok = False
        print("UNCLASSIFIED COLUMNS (hard failure per contract 01):", file=sys.stderr)
        for u in unclassified:
            print(f"  - {u}", file=sys.stderr)
    else:
        print(f"OK  every one of {len(rows)} replicated columns carries a classification")

    wh = connect_warehouse()
    with wh.cursor() as cur:
        cur.execute(
            "SELECT p.source_table, p.source_column FROM warehouse.column_policy p "
            "JOIN information_schema.columns c ON c.table_schema='raw' "
            "  AND c.table_name = p.source_table AND c.column_name = p.source_column "
            "WHERE p.pdp_class = 'secret'"
        )
        leaked = cur.fetchall()
    if leaked:
        ok = False
        print(f"SECRET COLUMNS PRESENT IN raw: {leaked}", file=sys.stderr)
    else:
        print("OK  no `secret`-class column exists as a warehouse column")
    return 0 if ok else 5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sync-policy", help="Materialise warehouse.column_policy from custom_pdp_core")

    p = sub.add_parser("gen-raw-ddl", help="Generate and apply raw.* landing tables from the policy")
    p.add_argument("--print-only", action="store_true", help="print the DDL instead of applying it")

    sub.add_parser("gen-fdw", help="Create the per-tenant foreign schema over the Odoo database")

    p = sub.add_parser("load-fixture", help="DEV ONLY: policy-driven masked snapshot load into raw.*")
    p.add_argument("--tenant", help="load only this tenant")

    p = sub.add_parser("tombstone", help="Append an _op='D' row to exercise delete semantics")
    p.add_argument("--table", required=True)
    p.add_argument("--id", required=True, type=int)
    p.add_argument("--tenant", required=True)

    sub.add_parser("verify", help="Re-check the classification and secret-exclusion invariants")

    args = ap.parse_args()
    return {
        "sync-policy": cmd_sync_policy,
        "gen-raw-ddl": cmd_gen_raw_ddl,
        "gen-fdw": cmd_gen_fdw,
        "load-fixture": cmd_load_fixture,
        "tombstone": cmd_tombstone,
        "verify": cmd_verify,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
