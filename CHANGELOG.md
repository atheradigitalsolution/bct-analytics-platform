# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries describe what was **built and verified**, not what was planned. Where something is a known
gap it appears under *Known gaps* rather than being omitted.

## [Unreleased] — `feat/analytics-platform`

Greenfield build of an Odoo 19 platform and a live analytics warehouse. The operator overrode the
original brief's "existing 162-addon platform" premise on 2026-08-31 and chose greenfield with a
five-addon domain set; `docs/agents/PLAN.md` records that deviation and its consequences.

### Added — platform

- **Odoo 19 CE stack** (`docker-compose.yml`, `docker-compose.dev.yml`), Postgres 16 with
  `wal_level=logical` and `max_slot_wal_keep_size=2GB` set at first boot, Redis 7. All images
  digest-pinned. Every compose invocation scoped to project `odoo19-bct`.
- **Five addons**: `custom_pdp_core` (the 698-column classification registry), `custom_pdp_masking`
  (the HMAC specification, in-UI masking and the `export_data` path), `custom_operating_unit`
  (fail-closed OU record rules), `custom_ppob`, `custom_demo_seed` (12 months across 2 operating
  units). 94 addon tests, exit 0.
- **`Makefile`** as the single entry point; a `RESERVED` block names the target namespaces each
  agent may claim, because `make` silently takes the last definition of a duplicated target.
- **Observability overlay**: Prometheus, Alertmanager, Grafana, Loki, promtail, node and postgres
  exporters, plus replication-slot alert rules keyed to ADR 0001's thresholds.

### Added — analytics

- **ADR 0001**: Postgres-native marts fed by native `pgoutput` logical replication, transformed by
  dbt-core. ClickHouse considered and rejected on SCD2 support, CDC path maturity and RLS
  idiomaticity, not on image size.
- **Warehouse** (`analytics/warehouse/`): schemas `raw`/`staging`/`marts`/`warehouse`/`snapshots`,
  four roles, and the contract-05 metadata tables — `column_policy`, `pipeline_state`,
  `tenant_registry`, `mart_sla`, the `mart_freshness` view and `log_access()`.
- **CDC loader** (`analytics/cdc/`): resumable keyset backfill, then a `pgoutput` stream. Masking is
  applied **during** load. Deletes land as tombstones. The LSN is confirmed only after the warehouse
  transaction commits, so Postgres is never told it may discard WAL the warehouse has not stored.
- **dbt project** (`analytics/dbt/`): 16 marts, SCD2 snapshots for `dim_partner` and `dim_product`,
  and a `post-hook` applying `ENABLE` + `FORCE ROW LEVEL SECURITY` to every model so it survives
  `--full-refresh`.
- **`login-gateway`**: authenticates against Odoo over JSON-RPC, issues RS256 JWTs, publishes JWKS
  with two distinct keys for rotation.
- **`semantic-api`**: `POST /v1/query` compiled from the metric contract. No raw SQL is accepted.

### Added — tests (`tests/`, 71 tests)

Integration tests exercising the seams between components, runnable with `make test`.

- **Live sync with real timestamps** — create → update → **delete** through the Odoo ORM, asserted
  end to end in the warehouse, including that the delete disappears from the latest-non-deleted
  projection. This is the test that distinguishes a live mart from a nightly dump.
- **Reconciliation** — warehouse totals against Odoo, per table, per day, plus the debit==credit
  identity and stock quantity.
- **Idempotency** — a second load over the same range, asserted to change neither the live
  projection *nor* the landing-zone row count.
- **Masking** — asserted against the actual stored value, with the digest re-derived in the test
  from the specification rather than imported from the loader, plus a `sha256(salt||value)` negative
  control.
- **Tenant isolation** — RLS at the storage layer, asserting the connection's own identity first,
  and asserting that the other tenant *has* rows so the zero is evidence rather than absence.
- **Cross-tenant 403** — the contract-02 body asserted character for character, and identical for a
  tenant that does not exist.
- **Token abuse** — tampered signature, `alg:none` and HS256-substitution hand-assembled from
  base64url segments rather than minted with a library that refuses to produce them.
- **Freshness** — asserting that `last_success_at` *stops* when the pipeline stops, which is the
  half a clock-driven implementation would fail.
- **Slot-lag alerts** — `promtool test rules`, including the below-threshold negative cases.
- **Backfill resumability** — `SIGKILL` mid-run, then resume, asserting the byte-identical result.
- **Clone verification** — every claim about installability made against a `git clone` of the
  branch, never the working tree.

### Added — documentation

- `docs/architecture.md` — what was built, with the data path from Odoo's WAL to a dashboard pixel.
- `docs/runbooks/analytics-pipeline.md` — dropped-slot recovery, re-seeding, a restored-source
  database, reconciliation triage, and what each alert means.
- `docs/pdp-compliance.md` — UU 27/2022 position, stating **in those words** that DSAR erasure
  propagation is a manual runbook and not automated.
- `docs/cicd-activation.md`, `docs/prod-deploy-checklist.md` — activation and deploy procedures,
  with the sections Security owns marked rather than invented.
- `docs/adr/`, `docs/agents/` — decisions, contracts and the plan (Lead-owned).

### Fixed

- **`allowed_ou: []` reversed to mean *no* Operating Units** (contract 02, GATE 3 amendment). The
  contract as frozen said "all" while the producer's record rules said "none", so the same token
  would have shown a user with no entitlement *more* in the dashboard than in Odoo — a privilege
  escalation manufactured purely by two documents disagreeing. The bypass is now an explicit
  `all_ou` boolean, and an absent claim grants nothing.
- **`export_data` masking bypass** — a user with `base.group_allow_export` but without the PDP
  viewer group received cleartext; now receives the masked value.
- **`.gitignore` patterns anchored**, after an unanchored `data/` silently excluded three
  install-critical files — including the entire 724-row classification seed — so a fresh clone could
  not install those modules while every working-tree test passed. `make check-gitignore` now guards
  it, and `tests/test_12_clone_install.py` verifies from a clone.
- **Freshness heartbeat moved out of the message callback** into a timer thread. It had been
  reachable only when a message arrived, so `last_success_at` aged on a healthy but idle pipeline —
  measured at 76 s and rising against a 60 s PPOB SLA. Now bounded at ~15 s.
- **Slot invalidation made fatal.** The monitor previously only logged it, leaving the consumer
  running against a slot whose WAL Postgres had already discarded — producing a mart with a hole and
  no error anywhere.
- **`--reload` removed** rather than repaired: it crashed on every invocation
  (`AttributeError: … 'clear_completion'`) and belonged to a design superseded when the resume point
  moved into the landing zone. Re-running `--backfill-only` is the supported path, and
  `test_cli_flags.py` now asserts every advertised flag is actually dispatched.

### Security

- **Read-only by construction.** The pipeline connects to Odoo as `warehouse_reader`, holding only
  `SELECT` and `REPLICATION`. `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE` and `CREATE TEMP TABLE`
  are all denied — verified with pasted denials, not asserted.
- **Append-only by grant.** `warehouse_loader` holds no `UPDATE`, `DELETE`, `TRUNCATE` or `CREATE`,
  so the landing-zone rules are enforced by the database rather than trusted to the loader's code.
- **Four warehouse roles**, of which only `warehouse_admin` is a superuser, and nothing queries data
  as it. A single shared identity would have made every isolation test in the project pass and mean
  nothing, because RLS is never evaluated for a `SUPERUSER` or `BYPASSRLS` role.
- **Storage-layer tenant isolation**: 13,755 rows belonging to a second tenant exist across the
  marts, and a session scoped to the first saw none of them.
- CI: pre-commit, semgrep, gitleaks over full history, hadolint, trivy image and filesystem scans,
  `pip-audit` and SBOM generation, gated by a single `ci-gate` check.

### Known gaps

- **DSAR erasure is a manual runbook, not automated.** `docs/pdp-compliance.md` §5 states this
  explicitly and gives the procedure. Recorded as a gap against UU 27/2022 Pasal 8 and 16(1)(f),
  not presented as a design choice.
- **No `cd.yml`.** Deployment is the manual `docs/prod-deploy-checklist.md`. Rollback is documented
  but **not demonstrated**, and the phase-5 criterion asks for a demonstration.
- **Cold start FAILS.** Executed twice with operator approval. `ODOO_INIT_MODULES=base,web` in
  `.env.example`, so `make up-dev` on a fresh clone installs none of the five addons and
  `make up-analytics` then exits 2 on `relation "pdp_field_classification" does not exist`.
- **A fresh stack accepts Odoo's default `admin`/`admin` password.** `BCT_DEV_USER_PASSWORD` was
  applied by hand once and exists only in an untracked local `.env`; it is not declared in
  `.env.example`, so a clone cannot learn it exists. Red test, deliberately.
- **"Alerting is live after a cold start" is NOT PROVEN.** The observability overlay is not brought
  up by `make up-dev` or `make up-analytics`, and the assertion that would prove it end to end has
  not yet run inside a cold-start execution. `make check-alerting` itself is now fixed and verified
  able to fail in both directions — it exits non-zero with Alertmanager stopped, 0 with it running,
  and 77 on a skip. It reached that state through two versions that passed while proving nothing:
  one JSON-decoded the plain-text `/-/healthy` and returned 0 on the resulting error, the other
  reported `1 active` Alertmanager with Alertmanager stopped, because `static_configs` makes
  `/api/v1/alertmanagers` report the configured target whether or not anything is listening.
- **Demo data is not seeded by any `make` target.** `demo.seed.generator.generate()` must be called
  explicitly, so a cold start yields an empty Odoo and nothing downstream can be verified until
  someone runs it by hand.
- **`allowed_ou: []` → UNASSIGNED not exercised.** No fact row carries `operating_unit_id = -1`, so
  the corrected mapping is indistinguishable from the bug it replaced. Recorded as a *failing* test
  that names what must be seeded, rather than a passing one that proves nothing.
- **Semantic audit cannot be made mandatory** inside Postgres: there is no `SELECT` trigger and
  `postgres:16-alpine` does not ship `pgaudit`. `log_statement='all'` on the serving role is the
  compensating control.
