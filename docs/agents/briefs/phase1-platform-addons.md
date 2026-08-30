# Brief: Platform-Addons — Phase 1 (domain modules)

## Objective
Four custom Odoo 19 modules that make the Phase 3 dimensional model *real* rather than aspirational:
a PDP field-classification registry, a masking policy, an Operating Unit dimension, and a PPOB
transaction vertical. Plus one fixture module that can generate 12 months of demo volume, because
the Phase 4 performance budget ("p95 under 2 s with 12 months of data") cannot be measured against
an empty database. Outcome: every fact and dimension named in master prompt §3.1 has a real source
table, and `custom_pdp_core` is the single source of the classification taxonomy.

## Read first
- `docs/agents/PLAN.md` — roster and owned paths.
- `docs/agents/contracts/01-classification.md` — **you are the producer of this contract.** The five
  classes and their masking transforms are frozen. You implement them exactly; you do not add a
  sixth class or rename one.
- `docs/agents/contracts/03-metric.md` — the facts and dimensions your models must be able to feed.
- `docs/agents/briefs/phase1-platform-infra.md` — for the addons mount path and project conventions.

## Ground truth
The repository is empty except `docs/`. Nothing may be copied from `/e/Projects/Odoo/platform` or any
other checkout on this machine. Write every module fresh.

The Odoo image is pulled and available locally:
`odoo:19.0@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`.

### Odoo 19 is not Odoo 17 — verify, do not recall
Odoo 19 removed and renamed fields that older tutorials still use. One confirmed example:
**`res.partner.mobile` does not exist in Odoo 19.** Do not write a model or a view referencing a
field you have not confirmed exists in *this* image. Confirm with:

```
docker run --rm odoo:19.0@sha256:f99ffac9... python3 -c "..."   # or
docker compose exec -T odoo odoo shell -d <db> --no-http
```

Every field you reference on a stock Odoo model must be checked against `ir.model.fields` in a live
database before you ship the view. A module that fails to install because of a phantom field is the
single most likely way this brief goes wrong.

## Scope — in

### 1. `addons/custom_pdp_core`
- Model `pdp.field.classification` with `(model_name, field_name, pdp_class, legal_basis, notes)`.
  `pdp_class` is a `Selection` of exactly `public | internal | personal | sensitive | secret`.
- A unique constraint on `(model_name, field_name)`.
- Seed data classifying, at minimum, every field the warehouse will read on: `res.partner`,
  `res.users`, `res.company`, `product.template`, `product.product`, `sale.order`,
  `sale.order.line`, `account.move`, `account.move.line`, `stock.move`, `pos.order`,
  `pos.order.line`, and your `ppob.transaction`.
- A JSON-RPC-reachable read method the CDC loader calls at startup, returning the full map.
- `MODULE_KNOWLEDGE.md` documenting the taxonomy decisions and their UU 27/2022 basis.

### 2. `addons/custom_pdp_masking`
- Model `pdp.masking.rule` mapping `pdp_class` → transform, matching contract 01 exactly:
  `public`/`internal` → none, `personal` → deterministic `hmac_sha256(value, per_tenant_salt)`,
  `sensitive` → same hash with free-text dropped to NULL, `secret` → never selected.
- In-Odoo enforcement: a user without the `PDP Data Viewer` group sees masked values in the UI for
  `personal`/`sensitive` fields.
- The **reference implementation of the hash** lives here as a documented, testable function, so the
  CDC loader and Odoo produce identical output for identical input. Cross-language agreement matters:
  publish the exact construction (encoding, salt position, digest, hex casing).
- Odoo unit tests asserting the transform is deterministic within a tenant and different across
  tenants.

### 3. `addons/custom_operating_unit`
- Model `operating.unit`: `name`, `code`, `company_id`, `parent_id`, `active`.
- `operating_unit_id` m2o added to `sale.order`, `account.move`, `stock.picking`, `pos.order`, and
  your `ppob.transaction`. Stored and indexed — the warehouse groups by it.
- `res.users` gains `allowed_operating_unit_ids` (this is what the Session contract's `allowed_ou`
  claim is read from) plus a `default_operating_unit_id`.
- Record rules restricting each model to the user's allowed OUs.
- `MODULE_KNOWLEDGE.md` — the DWH agent is instructed to read it before modelling `dim_operating_unit`,
  so it must actually explain the hierarchy and the company relationship.

### 4. `addons/custom_ppob`
- Model `ppob.transaction`: `name`/reference, `partner_id`, `biller_id`, `product_id`,
  `operating_unit_id`, `company_id`, `amount`, `admin_fee`, `commission`, `customer_ref`,
  `state` (`draft|pending|success|failed|reversed`), `requested_at`, `settled_at`, `sla_seconds`
  (stored compute), `failure_reason`.
- Model `ppob.biller`: `name`, `code`, `active`, `sla_target_seconds`.
- `customer_ref` is a subscriber/meter number — classify it `sensitive` in `custom_pdp_core`.
- Enough business logic that `state` transitions are constrained; the warehouse asserts
  `accepted_values` on it.

### 5. `addons/custom_demo_seed` — fixture module, not a fifth domain module
- A callable method generating parameterised demo volume: N partners, N products, and 12 months of
  sale orders, invoices, stock moves, POS orders and PPOB transactions across ≥2 Operating Units,
  with realistic date spread. Idempotent and re-runnable; takes a seed for reproducibility.
- Must be installable but must **never** be in the default install set for a production database.
  Say so in its manifest and in `MODULE_KNOWLEDGE.md`.

## Scope — out
- `docker-compose*.yml`, `Makefile`, `scripts/**`, `odoo/**`, `postgres/**`, `.env.example` —
  **Platform-Infra owns all of these.** If you need a Makefile target or a container change, raise a
  request to the Lead; do not edit those files.
- `analytics/**` — Data Warehouse agent. You do not write dbt models or SQL marts.
- `.github/**`, `.pre-commit-config.yaml` — Security agent.
- `docs/**` except the `MODULE_KNOWLEDGE.md` files that live *inside* your own addon directories.

## Contracts consumed
- `04-platform.md` (Platform-Infra) — addons mount path, database name, how to run `odoo shell`.
  If it is not published yet, develop against the mount path in the Infra brief and reconcile at the
  gate.

## Contracts produced
- **Contract 01 is realised by you.** Publish, in `addons/custom_pdp_core/MODULE_KNOWLEDGE.md`: the
  exact `pdp.field.classification` schema, the JSON-RPC method signature the CDC loader will call,
  and the complete seeded classification map.
- The exact HMAC construction from `custom_pdp_masking`, precise enough for a Python CDC loader to
  reimplement byte-identically.
- The `operating.unit` schema and the `res.users.allowed_operating_unit_ids` field name, which the
  Backend agent reads to populate the `allowed_ou` JWT claim.
- The `ppob.transaction` and `ppob.biller` schemas.

## Constraints
- Odoo 19 CE only. **No Enterprise dependency** in any manifest — the stack is CE and the module will
  simply fail to install.
- Every module: correct `__manifest__.py` with explicit `depends`, `license` (`LGPL-3`), version
  `19.0.1.0.0`, and a `security/ir.model.access.csv` for every new model. A missing ACL is an
  install-time or runtime failure, not a warning.
- Modules must install **one at a time, in dependency order**, per master prompt Phase 1.4.
- No personal data invented for demo seeding that looks like a real person's real identifiers — use
  obviously synthetic values. Demo NIK/customer refs must be clearly fake.

## Acceptance criteria — testable statements only
1. Each of the five modules installs cleanly into a fresh database, installed one at a time, exit 0.
2. `odoo -d <db> -u <module> --test-enable --stop-after-init` passes for each module.
3. `pdp.field.classification` returns a non-empty map covering every model listed in Scope 1, and a
   query for an unclassified field returns nothing (so the loader can hard-fail on it).
4. The masking function is deterministic: same input + same salt → identical digest across two calls;
   different tenant salt → different digest. Asserted by a module test.
5. `operating_unit_id` exists and is stored+indexed on all five target models — proven by a query
   against `ir.model.fields` and `pg_indexes`.
6. A user restricted to OU A cannot read an OU B `sale.order` — asserted by a module test.
7. `custom_demo_seed` generates ≥12 months of data spanning ≥2 OUs, and running it twice does not
   duplicate rows. Report actual row counts per table.
8. No module manifest declares an Enterprise dependency.

## Evidence required — paste the output of exactly these
```
for m in custom_pdp_core custom_pdp_masking custom_operating_unit custom_ppob; do \
  docker compose exec -T odoo odoo -d erp_dev -i $m --stop-after-init --no-http; echo "$m exit=$?"; done
docker compose exec -T odoo odoo -d erp_dev -u custom_pdp_core,custom_pdp_masking,custom_operating_unit,custom_ppob --test-enable --stop-after-init --no-http 2>&1 | tail -40
docker compose exec -T postgres psql -U odoo -d erp_dev -c "select pdp_class, count(*) from pdp_field_classification group by 1 order by 1;"
docker compose exec -T postgres psql -U odoo -d erp_dev -c "select model, name from ir_model_fields where name='operating_unit_id' order by model;"
docker compose exec -T postgres psql -U odoo -d erp_dev -c "select count(*) from ppob_transaction; select count(*) from sale_order; select min(date_order), max(date_order) from sale_order;"
grep -rn "depends" addons/*/__manifest__.py
```

## Escalation triggers — stop and return to Lead
- A field you need on a stock Odoo model does not exist in Odoo 19 and there is no clean equivalent.
- A module cannot install without an Enterprise module.
- You need a change in `docker-compose*.yml`, `Makefile` or `scripts/**` — those are Platform-Infra's.
- Implementing contract 01 faithfully turns out to be impossible for some field type. Say so; do not
  quietly widen the taxonomy.
