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

### Instance 11 — the alerting gate had never run a single one of its own checks

Found by QA, reproduced by the Lead against a **healthy** Prometheus:

```
$ curl -s http://127.0.0.1:39090/-/healthy
Prometheus Server is Healthy.            <- text/plain; charset=utf-8, by design
$ make check-alerting
check-alerting: SKIP - Prometheus not reachable at ... (JSONDecodeError).
  NOT a pass: slot-lag alerting is unverified while it is down.
RC=0
```

`scripts/check-alerting.py:85` probes `get("/-/healthy")`; `get()` JSON-decodes every response;
`/-/healthy` is plain text; the bare `except Exception` at line 86 catches the `JSONDecodeError`;
line 90 returns 0. **Every check below line 85 is unreachable code** — scrape targets up, an active
Alertmanager, alert rules resolving to series. None has ever executed.

Two properties make this worse than a broken script, and both generalise:

1. **It exits 0 while printing "NOT a pass".** Every automated consumer — CI, `make`, QA's own test
   — reads success; only a human reading stdout reads failure. A gate whose failure mode is
   invisible to everything that consumes it is not a gate. **Rule: a skip must never share an exit
   code with a pass.**
2. **It defeated the test written to catch instance 5.** QA's cold-start test asserted
   `check-alerting` returned 0. It did, having verified nothing, so the test went green — and its
   `wait_for` never waited, because the first call already "passed". Fixed in `8b7285a` to require
   exit 0 **and** the absence of `SKIP`. QA found and reported this against its own work.

Line 113 carries a second instance of the residue problem: `/api/v1/label/__name__/values` returns
names Prometheus has **ever** seen, not names with current samples, so a series that stopped being
emitted still reads as present. This is the same endpoint semantics behind the Lead's instance 7 and
QA's retracted Finding 4. **Three separate agents have now been fooled by it.** Assert on samples,
never on name presence.

### Gate status after QA's final report — recorded honestly, not aspirationally

PASS, with evidence re-run: live sync incl. delete (create 0.18s / update 0.24s / delete 0.21s
against a 60s budget, reaching `dim_partner` as `is_current` t->f) · cross-tenant 403 byte-identical
incl. for a non-existent tenant · reconciliation 15/15 tables, debit=credit 439,850,000.00 over 431
lines · masking, digest re-derived by hand and 5 `secret` columns absent as columns · RLS, 359
`bct_t2` rows invisible to a `bct`-scoped session · freshness 2.3s -> frozen 35s -> 2.3s ·
idempotency zero difference.

**Not done, with named owners — no item marked green on an assertion that could not fail:**

| Item | Status | Owner |
|---|---|---|
| Cold start from a fresh clone | **FAIL twice** — Finding 5, `ODOO_INIT_MODULES=base,web` | Platform-Infra |
| Alerting live after cold start | **NOT PROVEN** — instance 11 | Platform-Infra |
| Dev credential | **RED by design** — instance 10 | Platform-Infra |
| Slot-lag alert fires live | **PARTIAL** — `promtool` green incl. negatives; live firing not induced (512 MiB WAL, shared host) | accepted as declared |
| Five views render | **not covered** — portal not yet live | Frontend |
| CD rollback demonstrated | **not covered** — no git remote | Security |

**Lead ruling on the third cold start: deferred, deliberately.** Running it now would burn the
seeded stack to re-prove three findings already known red. Order: Platform-Infra lands the three
fixes -> Frontend takes its live evidence on the seeded stack -> one final cold start proves all of
it at once. Recorded here so the deferral is a decision with a reason, not an omission.

**DSAR erasure propagation into the warehouse is NOT automated. It is a manual runbook.** Stated
plainly in `docs/pdp-compliance.md` as §3.2 requires, rather than implied.

### Instance 10 CLOSED — verified by the Lead, negative assertion first

```
admin / admin (Odoo default)               -> false     <- the default is now refused
admin / $BCT_DEV_USER_PASSWORD             -> 2
demo.ou1@contoh.invalid / $BCT_DEV_USER..  -> 5
demo.ou2@contoh.invalid / $BCT_DEV_USER..  -> 6
```

`make seed-demo` also closes QA's "no make target seeds demo data" gap, and `check-dev-passwords`
exits 1 against an uninitialised database — the property `check-alerting` lacked. Note the order of
the assertions: the negative is first, because a check that only tries the good password passes on a
stack that accepts both.

### Instance 12 — a fix that cannot reach the population it was written for

Finding 5 was fixed in `.env.example:139` and remains broken in every existing `.env`, including the
operator's:

```
.env.example:139   ODOO_INIT_MODULES=custom_pdp_core,...,custom_demo_seed   <- fixed
.env:122           ODOO_INIT_MODULES=base,web                               <- still broken
```

The remedy is `make dev-bootstrap`, which merges `.env.example` into an existing `.env`. Trace it —
`scripts/gen-env-secrets.py:159-161`:

```python
if example_value != PLACEHOLDER:
    # Not a secret. Prefer whatever .env already says so hand edits to
    # ports and tunables survive a re-run.
    value = existing.get(key, example_value)
```

For every non-secret key the **existing** value wins. `ODOO_INIT_MODULES` is not a new key — it is
present with the wrong value — so bootstrap preserves `base,web` indefinitely. **The tool built to
repair the environment is the thing that protects the defect.**

The preservation rule is correct; clobbering a hand-tuned port would be worse. The defect is that
the divergence is **silent**, which is instances 8/9/10/11 again: the author's view (`.env.example`
is right) and the consumer's view (`.env` is still wrong) differ, and nothing reports it.

**Generalised rule.** Any mechanism that reconciles two copies of state — config, fixtures, schema,
a lockfile — must **report what it chose not to change**. Silent preservation is indistinguishable
from silent breakage. This is the reconciliation form of the empty-result rule: "no output" from a
merge does not mean "nothing diverged".

Consequence for the deferred third cold start: on this host it reproduces Finding 5 regardless of
what `.env.example` says, until either a repair path lands or the operator edits one line.

## PAUSED BY THE OPERATOR — resume point, 2026-08-31

Work halted at the operator's request. Two agents were stopped mid-task; nothing committed was lost.

**Committed and safe.** Platform-Infra landed `efa6f65` ("make the dev credential, the module set
and the alerting gate real"). QA and Data Warehouse both finished and committed everything they own.

**Uncommitted, on disk only — Frontend.** 31 paths under `insight-portal/` (12 modified, 19
untracked, including `Dockerfile`, `docker-compose.portal.yml`, `src/app/api/`, `src/app/t/`,
`scripts/`, `public/`). The work is in the working tree and intact. It is NOT committed, and the
Lead deliberately did not commit it — it is Frontend's path and the Lead has not reviewed it.
**Resuming Frontend is therefore the first thing to do, before any command that touches the tree.**

**Open, with owners:**

| Item | Owner | State |
|---|---|---|
| Instance 12 — `.env` drift is silent; `dev-bootstrap` preserves `ODOO_INIT_MODULES=base,web` | Platform-Infra | routed, not started |
| Instance 11 — `check-alerting` fixed in `efa6f65`; the fix has NOT been observed to fail | Platform-Infra | needs the red proof |
| Script file modes landed 100644 — Platform-Infra was checking whether that breaks a Linux clone | Platform-Infra | mid-investigation, unresolved |
| Five views render from real data; p95; 403; 375px evidence | Frontend | portal builds; live evidence not taken |
| `account.account` classification + a storable product with no `standard_price` | Platform-Addons | never dispatched |
| Phase 5 SBOM / signing verification | Security | never resumed |
| Third cold start (proves Finding 5, alerting, credential together) | QA | deliberately deferred by the Lead; awaits the three fixes |

**Operator action outstanding:** this host's `.env:122` still reads `ODOO_INIT_MODULES=base,web`.
Until instance 12's repair path lands, a cold start here reproduces Finding 5 regardless of
`.env.example`. One line, or wait for the repair target.

**Do not** mark any deferred item green on resume without re-running its evidence. Twelve instances
in this build say the green would be for the wrong reason.

## RESUMED — instances 13 and 14

### Instance 13 — the Alertmanager check could not fail, found by obeying the standing rule

Platform-Infra fixed instance 11, then tried to make each repaired check go red as required. Check 2
would not. With `odoo19-bct-alertmanager` **stopped**, `/api/v1/alertmanagers` kept reporting
`active=1 dropped=0` for 90 seconds and the gate printed *"Alertmanager reachable"*, rc 0 — while
`:39093/-/ready` refused the connection.

The cause: that endpoint reports the **configured** target from `static_configs`, not a live one,
and Alertmanager is not itself a scrape target. **A firing alert would have gone nowhere with every
gate green.** Now probed directly: stopped -> FAIL rc 1, started -> rc 0.

This one is worth more than the bug. It was found only because the author was required to make a
*passing* check fail, on a fix that was already working. Instance 11's fix would have shipped
green and still had a dark Alertmanager underneath it. **The standing rule paid for itself here.**

`check-alerting`'s first-ever real run also revealed it had been treating the label names
`slot_name`, `wal_status`, `on_breach` and `source_table` as metric names.

### Instance 14 — a fix that arms a trap instead of springing it

Every script in the repo was committed mode `100644`, because this host is Windows with
`core.filemode=false`. `scripts/up-dev.sh:59` executes `"$REPO_ROOT/scripts/init-db.sh"` directly,
so **`make up-dev` was "Permission denied" on a Linux fresh clone** — invisible here, since the
Makefile invokes most scripts as `bash x.sh`. Platform-Infra fixed 15 scripts to `100755` and
correctly stayed out of `scripts/analytics/` (Backend's path), which remains `100644` for five files.

The Lead then found where that condition becomes load-bearing. `.github/workflows/ci.yml:822`:

```bash
FIXTURE=scripts/analytics/dbt-ci-fixture.sh
if [ ! -x "$FIXTURE" ]; then ... "does not exist" ... exit 0; fi
"$FIXTURE"
```

Today this skips honestly — the file genuinely does not exist. **The defect is latent and fires on
delivery.** When DWH/QA commit the fixture from this host it lands `100644`, `[ ! -x ]` is still
true, tier 3 still skips, and the summary asserts the file "does not exist" when it does. CI stays
green and `dbt build` never runs against a fixture everyone believes is active.

**The generalised rule.** A guard must not conflate *absent* with *present but unusable*. Those are
different states with different remedies, and collapsing them produces a message that is actively
false in the second case. Test for existence, invoke mode-independently (`bash "$FIXTURE"`, which is
what every other caller in this repo already does — `tests/helpers/loader.py:26`), and give
"exists but not executable" its own non-green outcome. Routed to Security, who owns `ci.yml`.

### Open, carried forward

- **`SEMANTIC_API_JWKS_URL` drift**, found by Platform-Infra and not planted by it: `.env` says
  `http://odoo19-bct-login-gateway:8080/...`, `.env.example` says `http://login-gateway:8080/...`.
  **Backend's to adjudicate** — one of them is wrong and the drift report will now surface it.
- **An `alertmanager` scrape job** would let check 1 cover its liveness for free. Platform-Infra
  declined to take it: it edits `observability/prometheus/scrape.d` and needs a reload while QA and
  Frontend hold the stack. Recorded as a deliberate deferral, not an oversight.
- **`scripts/analytics/*.sh` are still `100644`** — Backend's path, same exec-bit condition.
