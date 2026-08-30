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
