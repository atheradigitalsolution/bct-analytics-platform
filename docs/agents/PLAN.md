# Analytics Platform — Lead plan

Branch: `feat/analytics-platform` off `main`. Local git only; no remote until approved.

## Deviation from the master prompt — recorded, not hidden

The master prompt's section 0 declares an existing 162-addon Odoo platform as ground truth and
forbids greenfield scaffolding. The operator overrode that on 2026-08-31 and chose **greenfield from
zero** with a **4-addon domain set**. Consequences accepted by the operator:

- The 162 modules, the UU PDP module family, Coretax/e-Faktur and PPh withholding do not exist and
  will not be recreated. Only `custom_pdp_core`, `custom_pdp_masking`, `custom_operating_unit` and
  `custom_ppob` are written.
- Phases 1–5 now include *building* the platform those phases assumed already existed.
- `login-gateway` + Keycloak do not exist. Auth is a new `login-gateway` service authenticating
  against Odoo over JSON-RPC and issuing RS256 JWTs (operator choice).
- Anti-patterns 7.1 ("second Odoo compose stack") and 7.2 ("copying addons out") remain in force —
  there is exactly one Odoo stack in this repo and no addon is copied from anywhere.

## Environment baseline (Lead, verified 2026-08-31)

| Item | Value |
|---|---|
| Docker Engine | 29.4.2 |
| Docker Compose | v5.1.3 |
| CPU / RAM available to Docker | 16 vCPU / 15.25 GiB |
| Free disk on E: | 651 GiB |
| git / python / node / npm | 2.51.2 / 3.13.14 / v24.11.1 / 11.6.2 |
| gh / sops / age-keygen / make | 2.89.0 / 3.13.0 / v1.3.1 / 4.4.1 |
| jq | **absent** — scripts must not depend on it; use python3 |

### Digests pinned at baseline

| Image | Digest |
|---|---|
| `odoo:19.0` | `sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd` |
| `postgres:16-alpine` | `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685` |
| `redis:7-alpine` | `sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf` |
| `node:22-alpine` | `sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32` |
| `python:3.12-slim` | `sha256:09f7da3bc104798d0afb40bc08d23ab2da20a76130cec1f2ef170848f5d85217` |

## Roster — owned paths

Extended from master prompt §2.1: greenfield needs an owner for the platform itself, so **Platform**
is split into two non-overlapping agents. Every path has exactly one writer.

| Agent | Owns (exclusive write) |
|---|---|
| **Lead** | `docs/agents/**`, `docs/adr/**`, the plan, the gates |
| **Platform-Infra** | `odoo/**`, `postgres/**`, `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.observability.yml`, `Makefile`, `scripts/**` (except `scripts/analytics/`), `.env.example`, `observability/**` (except `analytics-*`) |
| **Platform-Addons** | `addons/**` |
| **Data Warehouse** | `analytics/dbt/**`, `analytics/warehouse/**`, `docker-compose.analytics.yml`, `observability/grafana/analytics-*.json`, `observability/prometheus/analytics-*.yml` |
| **Backend** | `analytics/cdc/**`, `analytics/semantic-api/**`, `scripts/analytics/**`, `login-gateway/**` |
| **Frontend** | `insight-portal/**` |
| **Security** | `.github/workflows/**`, `security/**`, `.pre-commit-config.yaml`, `.sops.yaml`, `.gitleaks.toml`, `.semgrep/**`, `.trivyignore`, `.hadolint.yaml` |
| **QA & Docs** | `docs/**` (except `docs/agents/`, `docs/adr/`), `tests/**`, `CHANGELOG.md` |

**CI conflict rule (master prompt §2.1): Security owns `ci.yml` and `cd.yml`.** QA never edits them;
QA sends Security a diff request and Security merges it. This is restated in every brief.

## Waves — max 3 agents in parallel (§2.4)

| Wave | Agents | Gate at end |
|---|---|---|
| 1 | Platform-Infra, Platform-Addons, Security(baseline) | **GATE 1** — stack boots, 4+5 modules install clean |
| 2 | Lead writes ADR | **GATE 2** — warehouse engine + `wal_level` approved |
| 3 | Data Warehouse, Backend, QA | **GATE 3** — CDC live, reconciliation + masking tests pass |
| 4 | Frontend, Security(CD), QA | **GATE 4** — 5 views render, 403 cross-tenant proven, CD rollback demonstrated |

Hard dependency **DWH → Backend → Frontend** (§2.4). Frontend may build layout against the frozen
metric-contract fixture only, never against invented shapes.

Security and QA review at **every** gate, including phases they did not build. **Security has veto;
the Lead does not override it** (§2.4).

## Lead review duty (§2.5)

No agent claim is accepted on assertion. For every "done", the Lead re-runs that brief's Evidence
commands and pastes the output. A reported-but-unrun test is the specific failure the Lead exists
to catch.

## MANDATORY — path-limited commits (added at GATE 3 after a near-miss)

**All agents share one git index.** A plain `git commit` commits *everything* currently staged,
including files another agent staged seconds earlier. This is not hypothetical:

- Security ran `git add security/scan-targets.yml && git commit` while Backend had **25 files**
  staged under `analytics/cdc/**`. Only Security's own ruff hook failing aborted the commit. That is
  luck, not a control.
- Commit `28fe2c2c` ("feat(cdc): pgoutput CDC loader…") **did** capture three Platform-Addons files —
  `custom_pdp_masking/models/pdp_export.py`, `custom_operating_unit/hooks.py`,
  `custom_demo_seed/MODULE_KNOWLEDGE.md` — under Backend's message and outside Backend's owned paths.

**The rule, binding on every agent including the Lead:**

```
git commit -m "..." -- path/i/own          # path-limited; ignores the rest of the index
```

Verified behaviour: only the named paths are committed, and another agent's staged files remain
staged and untouched.

### Why this matters beyond attribution

The captured files happened to be syntactically complete and correctly wired. They need not have
been. An agent mid-edit can have a half-written file committed under someone else's message, where
its owner will not look for it and the committing agent does not know it exists — and a security fix
(`pdp_export.py` closes the `export_data` masking bypass) is exactly the kind of file whose apparent
completion matters.

### Lead audit, run at GATE 3

All 45 commits checked for file sets spanning more than one owner. Four hits: three benign
(the Lead's own `.gitignore`; two Platform-Infra commits publishing `04-platform.md`, which that
brief explicitly authorises) and one real — `28fe2c2c`, above. No work was lost. Re-run this audit
before the final merge.

## MANDATORY gate step — verify from a clone, never from the working tree

Added at GATE 3 after `.gitignore`'s unanchored `data/` silently excluded three install-critical
files, including the entire 724-row contract 01 classification seed. Every module's
`__manifest__.py` declared them, so **a fresh clone could not install those modules at all** — while
every test passed, because they ran against a working tree where the files exist on disk.

This bug class is invisible to everything else we run: `git status` shows nothing, the working tree
keeps working, CI on a warm checkout is fine. It surfaces only on a clean clone — which is exactly
what the definition of done promises ("`make up-dev` and `make up-analytics` bring up a clean stack
from a fresh clone, verified on a machine with no prior state").

**Standing rule: gate evidence for anything installable is produced from `git clone` of the branch
into a temporary directory, not from the working tree.** Verified working: clone, install all five
modules into a brand-new database, assert declared data files present, then remove clone, container
and database.

It is the same failure shape as a contract amendment not reaching its producer, and as an isolation
test pointed at a superuser: **the thing that was verified was not the thing that ships.** Three
separate instances of that shape in one session is a pattern, not a coincidence — prefer evidence
gathered from the artefact a user would actually get.

### Related hazards in a shared tree — all three now documented in `security/CI-CONTRACT.md` §8
1. **Shared git index** — a plain `git commit` captures another agent's staged files. Use
   `git commit -- path/i/own`.
2. **Stash window** — only `git commit` (the hook path) stashes the working tree; `pre-commit run`
   by hand does not. Recovery: pre-commit writes each stash to `~/.cache/pre-commit/patch<ts>-<pid>`
   as an ordinary git diff and never deletes it, so a lost edit is recoverable with `git apply`.
3. **Unstable evidence during active waves** — a red result may be a genuine finding in a sibling's
   in-flight work rather than a regression. Re-check before asserting it.

## The dominant defect pattern in this build — a check that cannot fail

Six independent instances, found by five different agents. None was a coding error in the usual
sense; every one was a **verification that returned the right-looking answer for the wrong reason**,
and in every case the surrounding work was correct. This is the pattern to design against.

| # | The check | Why it could not fail | Found by |
|---|---|---|---|
| 1 | Addon "installs cleanly" evidence | Run against a working tree where `.gitignore` had silently excluded three manifest-declared files; a fresh clone could not install at all | Platform-Addons |
| 2 | Contract 01's barcode amendment | Written into the contract while the producer CSV and the live table still said `personal`; the loader reads the table | Security |
| 3 | `git check-ignore` exit code | Exits 0 on a **negation** match too, so a guard asserting "`.env` is ignored" passes even when a negation made it committable | Backend → Security |
| 4 | `rolsuper` compared as `'f'` | Through `\|\|` a boolean renders `true`/`false`, never psql's `t`/`f`, so the comparison never matched and passed forever | Platform-Infra |
| 5 | Alerting believed healthy | `promtool` passes and Prometheus reports `health: ok` without either saying whether a selector matches any series. The real defect turned out to be different and worse: **alertmanager, loki, promtail and node-exporter were not running at all**, so every rule fired into nothing. A cold start rebuilds the base stack via `make up-dev`, which never touches the observability overlay | QA, Platform-Infra |
| 6 | `make install-modules` / `make up-dev` | Reported success while all five modules stayed `uninstalled`; and `.env.example` shipped `ODOO_INIT_MODULES=base,web`, so a fresh clone gets no domain model and `up-analytics` fails hard | Platform-Infra, QA |
| 7 | Lead's replication-slot check | Recorded separately below — the Lead's own instance of this pattern | Platform-Infra |
| 8 | `bct_warehouse_reconciliation_failed` believed live | The exporter scoped its `latest` CTE with `ORDER BY run_started_at DESC LIMIT 1`, and `make dbt-run` excludes tests, so the newest invocation carries **zero test rows** and the whole reconciliation series vanishes. The perturbation proof passed only because it ran `dbt-test` immediately before reading the metric — an order production never uses. Under the real loop (build often, test rarely) the alert is dark while Prometheus reports `health: ok` | QA, verified by Lead |
| 9 | `dim_product_cost.sql` in the working tree | The model existed on disk and dbt built it; it was never `git add`ed, so a fresh clone builds 34 models and silently omits the cost dimension. Identical shape to instance 1 | QA |
| 10 | "Dev password is set" | `BCT_DEV_USER_PASSWORD` exists **only** in the untracked local `.env`. No Makefile target, script, or seed model ever applies it. Login worked all session because an agent set it by hand in a live shell. After the documented `make up-dev`, `authenticate('bct','admin','admin')` returns uid `2` — Odoo's **default** password — while `.env` advertises a strong one that nothing consumes | Lead, from Frontend's report |

### What actually catches this class

Not more tests. **Restoring the broken condition and confirming the check goes red**, before trusting
that it is green for the right reason:

- DWH's reconciliation **perturbation proof** — corrupt a figure, watch the pipeline fail with a
  non-zero exit and a named row, restore, watch it pass.
- Backend's **mutation test** on T-1 — flip `is_local` true→false, watch three tests fail, revert.
- QA's third alert test asserting **samples, not names** — `/api/v1/label/__name__/values` still
  lists names from an earlier window, so a name-presence check reports healthy on exactly this bug.
- QA leaving `test_the_unassigned_ou_branch_is_actually_exercised` **RED as "not covered"** rather
  than filing a note. A red test outlives a paragraph in a report.
- Security's identity-first assertion: every isolation test states `rolsuper=f, rolbypassrls=f` for
  the role under test, because pointed at a superuser it would pass while proving nothing.

### Standing rule

**A check that has never been observed to fail is not yet known to work.** Before any gate accepts a
green result, the author states how they made it go red. If they cannot, the criterion is recorded as
**not verified** — never as passing.

### Instance 7 — the Lead, on the very pattern he had just catalogued

Verifying QA's Finding 4, the Lead ran `curl … | grep -c 'pg_replication_slot'`, got `0`, and
reported four load-bearing ADR alerts as permanently inactive. **The measurement was taken at a
moment when zero replication slots existed**, because the cold start had just destroyed them, and
per-slot series only exist while slots do. Platform-Infra disproved it by creating a slot and
querying Prometheus directly:

```
pg_replication_slots_pg_wal_lsn_diff {slot_name="bct_slot_bct"} = 56
pg_replication_slots_active == 0     -> 1 series (fires)
```

postgres_exporter v0.16 emits **both** the built-in `pg_replication_slot_slot_*` family and the
legacy `pg_replication_slots_*` names the rules already use. No rule expression needed changing and
no `PG_EXPORTER_EXTEND_QUERY_PATH` was needed — a rename would have broken working rules.

The lesson is not that the check was wrong but that **it was run without establishing its
precondition**, which is the same defect as every row in the table above. A `grep -c` returning 0
means "no match", never "the thing is broken" — the two are only the same if you have separately
established that a match *should* exist. This entry stays because the Lead is not exempt from the
rule, and because an error corrected in the record is worth more than one quietly dropped.


### Instances 8–10 — the unifying shape, stated by QA

QA's summary of instances 8 and 9 is the sharpest framing this build has produced:

> a thing that exists locally but not in the clone, and a thing that exists in the database but not
> in the metric — both look fine from where the author is standing.

Instance 10 is the third member of that set and the most dangerous, because it is a **security**
defect wearing the costume of a fixed one. The operator explicitly chose "set a local dev password".
That decision was carried out — in a shell, against a running container, once. It never became a
line of repo. The result is worse than having skipped it:

- a fresh clone gets `admin`/`admin`, Odoo's default;
- `.env` contains a 20-character random string that **looks** like the decision was implemented;
- every piece of evidence that authentication works was collected against the hand-made state.

`.env.example` does not even declare the variable, so a fresh clone has no way to learn it exists.

**Generalised rule, now binding on every agent:** if a step had to be performed by hand for your
evidence to pass, that step is part of the deliverable and is not done until it is in a file the
clone gets. State such steps explicitly in your report under the heading **"performed by hand"** —
an unrecorded manual step is indistinguishable from a fabricated result at the gate.

### Lead re-verification of instances 8 and 9 (§2.5), 2026-08-31

**Instance 9 (untracked model) — VERIFIED.** `find` 35 `.sql` models, `git ls-files` 35, equal;
`dim_product_cost.sql` tracked; `git status --untracked-files=all analytics/` clean.

**Instance 8 (reconciliation metric) — VERIFIED, and note how.** DWH's code is correct but its
summary sentence is not: it reported "both `latest` CTEs now scope to the most recent invocation
that CONTAINED tests". Only one does. `bct_warehouse_dbt_test` (queries.yml:52) carries the
`WHERE resource_type = 'test'` filter and the reconciliation series; `bct_warehouse_dbt_run`
(queries.yml:106) deliberately has **no** filter, because it answers "since anything ran". Adding
the filter there would restore exactly the conflation this finding was about. **The prose is the
hazard, not the code** — a future reader "fixing" the inconsistency would reintroduce the bug.

Live scrape confirmed 7 `bct_warehouse_reconciliation_failed` series and
`count(...) = 7` in Prometheus. **That observation alone proves nothing**, because at the time of
measurement the newest invocation was test-bearing — the one state in which the OLD code also
works. The discriminating condition had to be constructed. Done read-only, without running dbt and
without disturbing two working agents, by evaluating both scopings against a horizon just after a
`dbt-run`:

```
OLD scoping (ORDER BY run_started_at DESC LIMIT 1)  ->   0 series   <- alert dark
NEW scoping (newest TEST-BEARING invocation)        -> 287 test rows
```

**Method note worth keeping.** Reproducing a broken condition does not always require breaking
something. Where the defect is in *which rows a query selects*, the broken state can be recreated
with a `WHERE` clause over data that is already there. That is cheaper than a perturbation, it is
non-destructive, and it can be run while other agents hold the stack.

**A Lead error avoided, recorded because instance 7 was not.** Before the above, the Lead curled
`127.0.0.1` on four guessed ports for the exporter, got nothing, and was one step from reporting
"reconciliation series: 0" as a defect. The exporter publishes **no host port** — `9187/tcp`,
unmapped, scraped by Prometheus over the docker network. The measurement was incapable of returning
anything else. Same shape as instance 7: a probe run without establishing that a positive result was
even possible. The precondition check (`docker ps` ports, then `count(*)` on
`warehouse.dbt_run_result` = 1853 rows / 16 invocations) is what caught it.

### The rule, sharpened by Data Warehouse — the empty-result tell

DWH closed Findings 6 and 7 with the best formulation this build has produced, and it supersedes the
looser wording above:

> Instance 8 (config on disk, not in the process), instance 9 (model on disk, not in the clone) and
> Finding 7 (results in the table, not in the metric) are all "the author's view includes something
> the consumer's does not". The reason none of the three errored is that every one of them is a
> **missing row**, and a query returning nothing looks identical to a query returning nothing to
> worry about.

**Binding rule.** Distrust any check whose passing state is an **empty result**, unless it also
asserts the subject set was non-empty. Concretely, every such check must assert two things, not one:

1. the bad condition is absent, **and**
2. the population it searched was not empty.

QA retrofitted exactly this onto its own suite (minimum subject-set size, printed). Lead's aborted
exporter probe is the same failure from the other side: `curl` returned nothing because the exporter
publishes no host port, and "no output" was indistinguishable from "no problem".

This single rule would have caught instances 1, 5, 8, 9 and the Lead's instance 7.

### Lead verification of DWH's final state (§2.5), 2026-08-31 — all claims hold

```
seed landed          sale_order_line 311 | ppob_transaction 360 | account_move_line 431 | demo users 2
recon_daily          1636 checks | 1636 passed | 0 failed
marts                17 tables, 17 rls_enabled, 17 rls_forced
dim_product_cost     tracked; the 1.46x measurement written into the model at lines 18-30
mart_revenue_daily   bct 777 rows | bct_t2 777 rows
```

**`bct_t2` now holds real rows, which is the precondition the isolation tests were missing.** Until
this moment a cross-tenant 403 and the RLS test would both have passed by having nothing to leak —
the empty-result tell again. Both Frontend and QA have been told to assert the row count first and
the isolation second.

One Lead miss worth recording: the verification query looked for `marts.recon_daily`, which does not
exist — the table is `warehouse.recon_daily`. That is a wrong-schema error in the checker, not a
missing table, and it briefly looked like a discrepancy in DWH's report. Checked before reporting.

### Open gap from DWH's "performed by hand" declaration

Item 2 of DWH's declaration is a finding in its own right, of the instance-10 family: the ordering
**Backend backfills -> DWH resyncs `load-fixture --tenant bct_t2` -> DWH builds** is currently
"coordination by message rather than by a target". `load-fixture` is inside `make up-analytics`, but
the *ordering* relative to Backend's backfill exists only in this conversation. A fresh clone cannot
reproduce it. Owner: Platform-Infra (Makefile), after the credential work. Recorded so it does not
evaporate when this session ends — which is precisely how instance 10 came to exist.
