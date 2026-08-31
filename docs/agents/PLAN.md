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
