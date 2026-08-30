# Brief: Security — Phase 1 (supply-chain and secrets baseline)

## Objective
From the very first commit this repo cannot leak a secret and cannot merge an unscanned artefact.
You deliver the secret-management substrate (SOPS/age), the local pre-commit gate, and a CI workflow
that lints, SASTs, SCAs and scans every image the other agents are building — including the Node
services and analytics images that do not exist yet, wired so they are picked up the moment they land.
Phase 5 will extend this into CD; do not build CD now.

## Read first
- `docs/agents/PLAN.md` — roster, owned paths, pinned digests, wave plan.
- `docs/agents/contracts/01-classification.md` and `02-session.md` — **you are the authority on both.**
  Review that the other agents implement them faithfully; you hold veto at every gate (§2.4).
- `docs/agents/briefs/phase1-platform-infra.md` and `phase1-platform-addons.md` — what those two
  agents are shipping, so your scans cover it.

## Ground truth
The repository is empty except `docs/`. There is **no CI, no SOPS config, no pre-commit, no remote**.
`git init` has been run; the branch is `main`; there is no `origin` and none may be added — the
operator chose "local first, push later". Write the workflows anyway; they must be correct on the day
a remote is added, and CI correctness is reviewable without executing it.

Host has `sops 3.13.0`, `age-keygen v1.3.1`, `gh 2.89.0`, `git 2.51.2`. **`jq` is absent** — no script
you write may depend on it.

## Scope — in
1. `.sops.yaml` — age-based encryption rules. Creation rule covering `.secrets.enc.yaml` and any
   `*.enc.yaml`. Document the key-generation and team-onboarding flow.
   **The age private key is never committed.** The public recipient goes in `.sops.yaml`; the private
   key lives outside the repo and is referenced by path in `.gitignore`d config.
2. `.secrets.enc.yaml` — an encrypted example holding only `changeme`-grade dev values, proving the
   round-trip works. If encrypting requires a key the operator does not have yet, ship the config and
   the documented flow, and say plainly in your report that the round-trip is **not verified** rather
   than pretending it is.
3. `.gitleaks.toml` — rules plus a documented, minimal allowlist. No blanket path exclusions.
4. `.pre-commit-config.yaml` — SHA/rev-pinned hooks: `gitleaks`, `ruff` (or `flake8`+`black`) for
   Python, `sqlfluff` for the dbt SQL that Phase 3 will add, `hadolint` for Dockerfiles,
   `check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-added-large-files`, and a
   **CRLF guard** (`mixed-line-ending --fix=lf`) — the host is Windows and a CRLF `.sh` breaks
   containers.
5. `.semgrep/` — rule config for Python and TypeScript. `.semgrepignore`.
6. `.hadolint.yaml`, `.trivyignore` — with every ignore carrying a comment saying **why** and an
   expiry date. An undated permanent ignore is not acceptable.
7. `.github/workflows/ci.yml` — **you are the sole owner of this file** (master prompt §2.1). Jobs:
   - `lint` — pre-commit run over all files.
   - `sast` — Semgrep.
   - `sca-python` — `pip-audit` + CycloneDX SBOM upload.
   - **`sca-node`** — `npm audit --audit-level=high` **plus OSV-Scanner**, matrixed over
     `login-gateway`, `insight-portal` (they arrive in later waves; the matrix must tolerate a path
     not existing yet without silently passing — skip explicitly and say so in the job summary).
     CycloneDX SBOMs for each, uploaded alongside the Python ones.
   - `secrets` — gitleaks over full history.
   - `hadolint` — every Dockerfile.
   - `container-scan` — Trivy, **matrixed over every image this repo builds**: `odoo`, and later
     `analytics/dbt`, `semantic-api`, `login-gateway`, `insight-portal`. Master prompt §5.2: no new
     image ships unscanned. Structure the matrix so adding an image is a one-line change, and
     document that line in `docs/`-bound notes you hand to QA.
   - `fs-scan` — Trivy filesystem/config scan.
   - `dbt-ci` — placeholder job, **disabled with an explicit reason**, that Phase 3 will fill in.
     Do not fake a passing dbt job.
8. `security/` — a short threat model covering: the CDC replication slot as an availability risk to
   Odoo, the warehouse as a second copy of personal data under UU 27/2022, cross-tenant read as the
   primary confidentiality risk, and the JWT trust boundary from contract 02.

## Scope — out
- **`.github/workflows/cd.yml` — Phase 5, not now.** Do not create it, not even as a stub.
- Cosign/SLSA attestation — Phase 5.
- `docker-compose*.yml`, `Makefile`, `scripts/**`, `odoo/**`, `postgres/**` — Platform-Infra.
- `addons/**` — Platform-Addons.
- `analytics/**`, `insight-portal/**`, `login-gateway/**` — later agents.
- `docs/**` — QA & Docs owns it, except `security/` which is yours.
- **Do not run `git push`, `gh repo create`, or add a remote.** There is no remote by operator
  decision. Creating one is an outward-facing action you are not authorised to take.

## Contracts consumed
- `04-platform.md` (Platform-Infra) — the image names and Dockerfile paths your scan matrix targets,
  and the `.env` variable names whose secrets you must confirm are `changeme` in the example.

## Contracts produced
- The **CI job names and their pass/fail semantics**, which Phase 5 CD will gate on
  ("require all CI jobs green").
- The scan-matrix extension point: the exact place a new image is registered, published so DWH,
  Backend and Frontend can request their image be added via the Lead rather than editing `ci.yml`.
- The SOPS onboarding flow, so every other agent knows how to add a secret without ever writing a
  plaintext one.

## Constraints
- **Every third-party action is SHA-pinned**, not tag-pinned. `actions/checkout@v4` is a finding, not
  a convention. Pin to a full 40-char commit SHA with the version in a trailing comment.
- Least-privilege `permissions:` at workflow level, elevated per-job only where genuinely required.
- Pin runner versions; do not use `ubuntu-latest` for anything whose reproducibility matters.
- No secret in any file you create. `changeme` only, matching `.env.example`.
- **CI conflict rule (§2.1): you own `ci.yml` and `cd.yml`. QA does not edit them.** QA sends you a
  diff request for test jobs and you merge it. Restate this when you report.

## Acceptance criteria — testable statements only
1. `pre-commit run --all-files` completes; every hook either passes or fails with a real, actionable
   finding. No hook errors out on a missing tool.
2. Every `uses:` in `.github/workflows/ci.yml` is a 40-char SHA. Verified by a grep that finds zero
   `uses: .*@v[0-9]` and zero `uses: .*@(main|master)`.
3. `gitleaks detect --source . --no-git` exits 0 on the tree, and `gitleaks detect --source .` exits 0
   over full history.
4. Every `.trivyignore` and `.hadolint.yaml` ignore entry has a reason comment and an expiry date.
5. `sops --decrypt .secrets.enc.yaml` round-trips — **or** you state explicitly that it is unverified
   and why.
6. Workflow YAML is syntactically valid — parsed by `python -c "import yaml,sys; yaml.safe_load(...)"`,
   since `actionlint` may not be installed.
7. The `container-scan` matrix already lists every image the PLAN says will exist, with the
   not-yet-existing ones explicitly skipped rather than silently absent.
8. `.pre-commit-config.yaml` includes a CRLF guard.

## Evidence required — paste the output of exactly these
```
pre-commit run --all-files 2>&1 | tail -40
grep -rnE 'uses: .*@(v[0-9]|main|master)' .github/workflows/ || echo "NO_UNPINNED_ACTIONS"
grep -rncE 'uses: .*@[0-9a-f]{40}' .github/workflows/ci.yml
gitleaks detect --source . --no-git --redact -v 2>&1 | tail -20
python -c "import yaml,glob,sys; [yaml.safe_load(open(f,encoding='utf-8')) for f in glob.glob('.github/workflows/*.yml')]; print('WORKFLOW_YAML_OK')"
sops --decrypt .secrets.enc.yaml >/dev/null && echo SOPS_ROUNDTRIP_OK || echo SOPS_UNVERIFIED
grep -rn "expiry\|expires" .trivyignore .hadolint.yaml | head
```

## Escalation triggers — stop and return to Lead
- A required scanner cannot run locally at all, so you cannot verify your own workflow. Report what
  is unverifiable rather than asserting it passes.
- You find a design in another agent's brief that you would veto at the gate — raise it **now**, at
  brief time, not at the gate. Early veto is cheaper.
- You believe a secret must be committed for the stack to work. It must not; escalate instead.
- Anything requires creating a remote, pushing, or otherwise leaving this machine.
