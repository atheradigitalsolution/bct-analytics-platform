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

---

# Published by the Data Warehouse agent

Everything above this line is the Lead's frozen text, unchanged. Everything below is DWH filling in
what the freeze deliberately left open. Verified against the running `warehouse-db`, not designed on
paper.

## A. Role model — which identity connects as what

The freeze named the tables and not the identities. Here they are. **There are four roles and that
is not incidental.** In Postgres a `SUPERUSER`, and any role holding `BYPASSRLS`, bypasses row
security unconditionally and no policy can stop it. Point the semantic-api at a superuser and every
cross-tenant test still passes — proving only that the query is well formed. A single shared
identity would have made every isolation test in this project green and worthless.

| Role | Attributes | Used by | May |
|---|---|---|---|
| `warehouse_admin` | **SUPERUSER**, the container's `POSTGRES_USER` | the init DDL, `warehouse-backup` | everything. **Nothing queries data as this role.** |
| `warehouse` | `NOSUPERUSER NOBYPASSRLS`; owns `raw` `staging` `marts` `warehouse` `snapshots` | **dbt** | build models; read every tenant *only while `app.tenant_id` is unset* |
| `warehouse_loader` | `NOSUPERUSER NOBYPASSRLS` | **Backend's CDC loader** | `INSERT`+`SELECT` on `raw.*`; full DML on `warehouse.pipeline_state`; `SELECT` on `warehouse.column_policy` and `warehouse.tenant_registry`. **No `CREATE`. No `marts`, `staging` or `snapshots`.** |
| `warehouse_rls` | `NOSUPERUSER NOBYPASSRLS` | **semantic-api**, `warehouse-exporter` | `SELECT` on `marts.*` **under RLS**; `SELECT` on the operational metadata in §B; `EXECUTE` on `warehouse.log_access()` |

Assert this rather than assume it — and note the rendering trap. Through `||` a boolean renders
`true`/`false`, not psql's `t`/`f`, so a check written against `'f'` never matches and passes forever
without testing anything:

```sql
SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
```

### 1. The CDC loader uses `warehouse_loader`

Grants, exactly as applied by `analytics/warehouse/init/sql/40-grants.sql`:

```sql
GRANT USAGE ON SCHEMA raw, warehouse TO warehouse_loader;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA raw TO warehouse_loader;   -- no UPDATE, no DELETE
GRANT SELECT ON warehouse.column_policy, warehouse.tenant_registry TO warehouse_loader;
GRANT SELECT, INSERT, UPDATE, DELETE ON warehouse.pipeline_state TO warehouse_loader;
GRANT EXECUTE ON FUNCTION warehouse.log_access(...) TO warehouse_loader;
REVOKE CREATE ON SCHEMA raw, warehouse FROM warehouse_loader;
```

Two of those are load-bearing rather than tidy:

- **No `UPDATE`, no `DELETE` on `raw.*`.** The landing zone is append-only and a delete is a
  tombstone row, never an in-place change. That rule is now enforced by the grant instead of trusted
  to the loader's code.
- **No `CREATE`.** `raw.*` DDL is generated by DWH from `warehouse.column_policy`
  (`make warehouse-raw-ddl`). A loader able to create its own landing table could land a column with
  no policy row, and "unclassified is a hard failure" would drop from a structural fact to a
  convention. **A missing `raw.*` table is a schema-drift signal: stop and tell DWH, do not create
  it.** `ALTER DEFAULT PRIVILEGES` already covers tables DWH generates later, so a new landing table
  is writable the moment it exists, with no manual grant.

### 2. semantic-api uses `warehouse_rls`, and RLS genuinely applies to it

**Ownership does not bypass RLS here**, and that is the single most likely way isolation looks
enforced and is not. Three things make it real:

1. Every mart carries `ENABLE ROW LEVEL SECURITY` **and `FORCE ROW LEVEL SECURITY`**, applied by a
   dbt `post-hook` on every model, so it survives `--full-refresh` — which drops and recreates the
   table and takes any hand-created policy with it.
2. The marts are owned by `warehouse`, which is `NOSUPERUSER NOBYPASSRLS`. `FORCE` is what makes an
   owner subject to its own policies.
3. `warehouse_rls` matches only the tenant policy, so with `app.tenant_id` unset it reads **zero
   rows**. Fail closed.

```sql
-- everyone, the owner included
CREATE POLICY p_tenant_isolation ON marts.<t> FOR ALL TO PUBLIC
  USING (tenant_id = current_setting('app.tenant_id', true));

-- the transform role ONLY, and ONLY while no tenant is set
CREATE POLICY p_transform_unscoped ON marts.<t> FOR ALL TO warehouse
  USING (coalesce(current_setting('app.tenant_id', true), '') = '');
```

`warehouse_admin` is a superuser and still bypasses all of it. That is Postgres, not a choice, and
it is exactly why nothing queries data as that role.

### 3. dbt uses `warehouse`, and does not become the role that later reads the marts

dbt must see every tenant to build a model and cannot scope itself to one, which is why
`p_transform_unscoped` exists. Note its condition: it applies **only while `app.tenant_id` is
unset**. The instant any caller sets that variable — including a human connected as the dbt role —
the policy stops applying and only `p_tenant_isolation` remains. So `SET app.tenant_id='x'` is a
genuine constraint on every non-superuser identity in this warehouse, dbt's included.

`warehouse_rls` is a separate login holding `SELECT` and nothing else. The serving path cannot
acquire the transform path's privileges, because they are not the same role.

### 4. Connection URIs

Always an environment interpolation, never a literal — Security's DSN scanner covers eight schemes
and a literal password fails the commit hook.

```
# CDC loader     -> warehouse
postgresql://${WAREHOUSE_LOADER_USER}:${WAREHOUSE_LOADER_PASSWORD}@warehouse-db:5432/${WAREHOUSE_DB}?sslmode=disable
# semantic-api   -> warehouse
postgresql://${WAREHOUSE_RLS_USER}:${WAREHOUSE_RLS_PASSWORD}@warehouse-db:5432/${WAREHOUSE_DB}?sslmode=disable
# dbt            -> warehouse
postgresql://${WAREHOUSE_DB_USER}:${WAREHOUSE_DB_PASSWORD}@warehouse-db:5432/${WAREHOUSE_DB}?sslmode=disable
# anything       -> Odoo, read-only, ALWAYS warehouse_reader (contract 04 §2)
postgresql://${WAREHOUSE_READER_USER}:${WAREHOUSE_READER_PASSWORD}@postgres:5432/<tenant_db>?sslmode=disable
```

New variables, added per contract 04 §5's documented procedure (`changeme` in `.env.example`;
`gen-env-secrets.py` picks them up with no edit to that script):
`WAREHOUSE_ADMIN_USER` `WAREHOUSE_ADMIN_PASSWORD` `WAREHOUSE_LOADER_USER`
`WAREHOUSE_LOADER_PASSWORD` `WAREHOUSE_RLS_USER` `WAREHOUSE_RLS_PASSWORD` `DBT_THREADS`.

### 5. A confusing failure mode, written down so nobody loses an hour to it

> `information_schema.tables` and `\dt` return **nothing** for a schema you hold no privilege on.
> Connected as a role without `SELECT`, the tables do not look inaccessible — they look **absent**.
> If `\dt warehouse.*` is empty, check `\du` and the grants before concluding the DDL never ran.

The same is true of `raw` seen from `warehouse_rls`, and that is deliberate: the serving identity has
no access to the landing zone at all.

## B. Tables in `warehouse` beyond the two the Lead froze

Backend and Frontend may read the **published** rows. The rest are DWH-internal: nothing should build
on them, and they will change without a contract revision.

| Table / view | Status | Who may read it |
|---|---|---|
| `warehouse.column_policy` | **contract** (frozen above) | CDC loader |
| `warehouse.pipeline_state` | **contract** (frozen above) | CDC loader (writes), semantic-api |
| `warehouse.tenant_registry` | **published** | CDC loader, semantic-api |
| `warehouse.mart_sla` | **published** | semantic-api |
| `warehouse.mart_freshness` | **published** | semantic-api |
| `warehouse.log_access()` | **published** (the function; the table is not readable) | everything, append-only |
| `warehouse.access_audit` | internal | nothing reads it through SQL |
| `warehouse.dbt_run_result` | internal | the metrics exporter only |

```sql
-- warehouse.tenant_registry — source of dim_tenant, and of a tenant's slot/publication names.
-- mask_salt_env holds the NAME of the environment variable carrying the salt, NEVER the value.
tenant_id       text PRIMARY KEY CHECK (tenant_id ~ '^[a-z][a-z0-9_]{1,30}$')  -- no dashes: slot names forbid them
display_name    text NOT NULL
source_database text NOT NULL
slot_name       text
publication     text
mask_salt_env   text NOT NULL
is_test_tenant  boolean NOT NULL DEFAULT false
active          boolean NOT NULL DEFAULT true
onboarded_at    timestamptz NOT NULL DEFAULT now()

-- warehouse.mart_sla — ADR 0001's freshness table as data. is_stale is computed against THIS.
mart_name text PRIMARY KEY, sla_seconds integer NOT NULL CHECK (sla_seconds > 0),
on_breach text NOT NULL CHECK (on_breach IN ('page','alert')),
source_tables text[] NOT NULL, note text

-- warehouse.mart_freshness — THE view semantic-api serves meta.last_refreshed_at / meta.is_stale
-- from. A mart with no pipeline_state row reports is_stale = true. Never "fresh" by default.
mart_name, tenant_id, sla_seconds, on_breach, last_refreshed_at, age_seconds, is_stale

-- warehouse.log_access(action, object_schema, object_name, row_count, principal, detail) -> bigint
-- SECURITY DEFINER. tenant_scope is read from app.tenant_id INSIDE the function, not from an
-- argument, so an audit row cannot claim a scope the query did not run under.
```

**`warehouse.access_audit` design note, because the brief asks for one.** The module it was to
mirror, `custom_pdp_audit`, **does not exist** — the five addons are `custom_demo_seed`,
`custom_operating_unit`, `custom_pdp_core`, `custom_pdp_masking`, `custom_ppob`. So it is designed
here, in three layers, because no single one of them is sufficient:

1. `ALTER ROLE warehouse_rls SET log_statement='all'` — applied by the server, so a client cannot
   opt out of it, and it still records the read when a client forgets to call the function below.
2. This table, written through `warehouse.log_access()`, which records the *semantic* fact — which
   metric, which tenant scope, how many rows — that a raw statement log cannot reconstruct.
3. RLS itself, so an unattributed read returns zero rows rather than another tenant's data.

Postgres cannot trigger on `SELECT`, so layer 2 cannot be made mandatory inside the database without
pgaudit, which `postgres:16-alpine` does not ship. Layer 1 is what closes that gap. Stated plainly
rather than left as an implied guarantee.

## Amendment at GATE 3 — `_row_id` is a fifth meta column, and that is accepted

QA noticed `raw.*` carries `_row_id` beyond the four this contract called "exactly these", and asked
whether to amend the contract or drop the column. **Amending.**

| Column | Type | Meaning |
|---|---|---|
| `_row_id` | surrogate | unique identity of one landed row |

It earns its place: `_lsn` orders changes but is **not unique** — several changes committed in one
transaction share an LSN — so `(_tenant_id, pk, _lsn)` cannot always name a single landed row.
`_row_id` can, which matters for dedup, for pointing at a specific landing row in a bug report, and
for stable pagination over an append-only table.

**Constraints on its use, binding on every agent:**
- It is a *landing-zone* surrogate. It has no meaning in Odoo and must never be exposed as a business
  key, joined on across tables, or surfaced in a mart or a metric.
- Ordering semantics are unchanged: `(_tenant_id, <pk>, _lsn)` remains the ordering key. `_row_id`
  breaks ties within an LSN; it does not replace the ordering.
- Dropping the column later is a breaking change to `stg_` models.

Raising this rather than silently tolerating the drift was the right call — "exactly these" is the
kind of wording that either binds or should be changed, and a contract nobody enforces is worse than
no contract.
