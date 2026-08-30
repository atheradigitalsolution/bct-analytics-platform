# Frozen contract 3 — metric (DWH → Backend → Frontend)

Status: **shape FROZEN at GATE 0; instances frozen at GATE 2.** Producer: Data Warehouse agent.
Consumers: `semantic-api` (Backend), `insight-portal` (Frontend).

Master prompt §3.5: one place defines each metric. The front-end must never hand-write business
logic in SQL or TypeScript. This file is the machine-readable seam — prose is not a contract.

## Machine-readable form

Every metric is one entry in `analytics/semantic-api/metrics/*.yml`, validated against
`analytics/semantic-api/metrics/metric.schema.json` in CI. A metric that fails the schema fails
the build.

```yaml
- name: revenue_net                      # snake_case, unique, stable — renaming is a breaking change
  label: "Pendapatan Neto"
  description: "Invoiced revenue excluding tax, credit notes netted off."
  grain: [date_day, tenant_id, operating_unit_id]   # the lowest level it may be requested at
  dimensions:                            # legal group-by keys
    - date_day
    - date_month
    - tenant_id
    - operating_unit_id
    - partner_key
    - product_key
    - company_id
  filters:                               # legal filter keys and their types
    date_range: {type: daterange, required: true}
    operating_unit_id: {type: int[], required: false}
    product_key: {type: string[], required: false}
  type: decimal                          # decimal | integer | percent | duration_seconds | count
  unit: IDR
  aggregation: sum                       # sum | avg | count | count_distinct | ratio
  source_model: mart_revenue_daily       # the dbt model that answers it
  refresh_sla_seconds: 300               # see GATE 2 ADR; breach is an alert, not a silent stale read
  pdp_class: internal                    # from contract 01 — a metric may never expose a `secret` class
```

## Rules that bind all three agents

1. **`tenant_id` is always in `grain`.** A metric that can be computed across tenants does not exist.
2. **The API never accepts raw SQL.** `semantic-api` exposes `POST /v1/query` taking
   `{metric, dimensions[], filters{}, order_by, limit}` and compiles it from this contract. Anything
   not declared above is rejected with 400 before a query is planned.
3. **`refresh_sla_seconds` is served, not assumed.** Every response carries
   `meta.last_refreshed_at` and `meta.is_stale`, read from real pipeline metadata
   (`warehouse.pipeline_state`), never from a clock on the client (§4, "last refreshed at").
4. **Masking is upstream.** By the time a metric is computed the data is already masked per
   contract 01. `semantic-api` performs no masking and can perform none.
5. Adding a dimension is backwards-compatible. Removing one, renaming a metric, or changing `grain`,
   `type` or `unit` is **breaking** — it requires the Lead to re-brief Backend and Frontend.

## Frontend fixture rule

Frontend may develop against `analytics/semantic-api/metrics/fixtures/*.json`, which are generated
from this contract by `make metric-fixtures` and validated in CI. Hand-written fixture shapes are a
brief violation (§2.4).
