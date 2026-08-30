# Frozen contract 5 — warehouse landing and policy seam (Lead-frozen)

Status: **FROZEN by the Lead at GATE 1.** Producer of the DDL: Data Warehouse agent. Consumer:
Backend agent (CDC loader, semantic-api).

The Lead froze this rather than letting DWH publish it after the fact, so that **DWH and Backend can
build in parallel** instead of Backend idling. Neither agent may change a name here unilaterally;
a change means the Lead re-briefs the other (§2.3).

## Why this file exists

Master prompt §3.2 assigns PDP masking to the DWH agent but requires it applied *during load*, and
the loader is Backend's code. Two agents must never write one file (§7.11). The seam is therefore a
**table**, not a code call:

- **DWH owns the DDL and populates the policy.**
- **Backend's loader reads the policy and executes it.** It invents no transform and hardcodes no
  classification.
- **DWH verifies the result** with dbt tests asserting masked columns are unreadable.

## Schemas

```
raw        -- append-only landing zone, one table per replicated source table
staging    -- dbt stg_ models
marts      -- dbt int_ and mart_ models, facts and dimensions
warehouse  -- pipeline metadata and policy (this contract)
```

## `warehouse.column_policy` — DWH writes, Backend reads

```sql
CREATE TABLE warehouse.column_policy (
  source_table   text NOT NULL,          -- e.g. 'res_partner'
  source_column  text NOT NULL,          -- e.g. 'email'
  pdp_class      text NOT NULL           -- public|internal|personal|sensitive|secret
                 CHECK (pdp_class IN ('public','internal','personal','sensitive','secret')),
  transform      text NOT NULL           -- none|hmac_sha256|hmac_sha256_nullable|drop
                 CHECK (transform IN ('none','hmac_sha256','hmac_sha256_nullable','drop')),
  mask_null      boolean NOT NULL DEFAULT false,  -- free-text sensitive → NULL rather than hashed
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_column)
);
```

Mapping from contract 01, and it is not negotiable:

| `pdp_class` | `transform` | `mask_null` |
|---|---|---|
| `public`, `internal` | `none` | false |
| `personal` | `hmac_sha256` | false |
| `sensitive` | `hmac_sha256_nullable` | true for free text |
| `secret` | `drop` | — column is never selected, so it cannot land |

**Unclassified is a hard failure.** If the loader is about to extract a column with no row here, it
exits non-zero. Neither agent may default it to `public` (Backend brief, escalation trigger 1).

## `warehouse.pipeline_state` — Backend writes, DWH and semantic-api read

```sql
CREATE TABLE warehouse.pipeline_state (
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
```

This is the **only** source of `meta.last_refreshed_at` and `meta.is_stale` (metric contract §3).
The dashboard's freshness indicator reads real pipeline metadata — never a client clock (§4).
`is_stale` is computed against the per-mart SLA in the accepted ADR.

## `raw.*` conventions — Backend writes, DWH's `stg_` models read

Every landing table mirrors its source columns **unmodified** (post-masking) plus exactly these:

| Column | Type | Meaning |
|---|---|---|
| `_ingested_at` | `timestamptz` | when the loader wrote the row |
| `_op` | `char(1)` | `I`, `U`, or `D` |
| `_tenant_id` | `text` | source database / tenant slug |
| `_lsn` | `pg_lsn` | WAL position, for ordering and resumability |

- **Append-only.** Never `UPDATE` or `DELETE` a landing row. A change is a new row.
- **Deletes are tombstones** (`_op='D'`), never physical removal. Marts must filter to the latest
  non-deleted version per key, so a delete in Odoo disappears from the mart within the SLA.
- Naming: `raw.<source_table>` — `res_partner` → `raw.res_partner`.
- Ordering key is `(_tenant_id, <pk>, _lsn)`.

## RLS session variable

```
app.tenant_id
```

Set per query, read by every RLS policy on `marts.*`. Both agents use exactly this name.

**T-1 applies here and is blocking on Backend** (see the Backend brief): RLS reads a *session*
variable, so a pooled connection reused across tenants defeats it silently. `SET LOCAL` inside an
explicit transaction, a per-tenant pool, or a checkout/checkin guard that fails closed — Backend
states which, and proves it with a pooled-connection leakage test.

## HMAC construction

Backend must reproduce `custom_pdp_masking`'s function **byte-identically**. The addon's
`MODULE_KNOWLEDGE.md` is authoritative for encoding, salt position, digest and hex casing. If the two
disagree, joins break silently and the discrepancy will surface as a reconciliation failure, not as
an error — so verify equality with a cross-language test on shared vectors.

Salts come from the environment (`WAREHOUSE_MASK_SALT_<TENANT>`, SOPS-managed), never a file, never
git, `changeme` in `.env.example`.

## Mart list and grain — DWH publishes, Backend binds `source_model` against it

DWH appends the final table here once models exist. Facts: `fct_sale_order_line`,
`fct_account_move_line`, `fct_stock_move`, `fct_pos_order_line`, `fct_ppob_transaction`.
Dimensions: `dim_date`, `dim_partner` (SCD2), `dim_product` (SCD2), `dim_company`,
`dim_operating_unit`, `dim_tenant`. **Every fact and dimension carries `tenant_id`.**
