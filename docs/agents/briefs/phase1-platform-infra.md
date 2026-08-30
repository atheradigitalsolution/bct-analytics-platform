# Brief: Platform-Infra — Phase 1 (baseline bring-up)

## Objective
Someone who has just cloned this repo onto a machine with no prior state runs two commands and gets a
healthy Odoo 19 CE stack: `make dev-bootstrap && make up-dev`. Postgres is configured for logical
decoding from the very first boot, so Phase 3 CDC needs **no** later restart of shared infrastructure.
Outcome, not activity: `docker compose ps` shows every service `healthy` and `/web/login` returns 200.

## Read first
- `docs/agents/PLAN.md` — roster, owned paths, pinned digests. The digests are non-negotiable.
- `docs/agents/contracts/01-classification.md` — you do not implement it, but `.env.example` must
  carry the `WAREHOUSE_MASK_SALT_*` placeholders it requires.
- `docs/agents/contracts/02-session.md` — `.env.example` must carry the login-gateway RS256 keypair
  paths and the JWKS URL it requires.

## Ground truth
The repository is **empty** except `docs/`. Nothing is reusable. Nothing may be copied in from
`/e/Projects/Odoo/platform`, `/e/Projects/Odoo/platform-analytics`, or any other checkout on this
machine — those are explicitly out of scope (PLAN.md, "Deviation"). Write everything fresh.

Verified host baseline: Docker 29.4.2, Compose v5.1.3, 16 vCPU, 15.25 GiB RAM, 651 GiB free.
**`jq` is NOT installed on the host** — no script you write may depend on it; use `python3` for JSON.

### Host is already busy — this is a hard constraint, not a preference
These stacks are running right now and **must not be disturbed**:
`odoo19-platform-*` (ports 18xxx), `odoo19-analytics-*` (ports 2xxxx), `smart-warga-postgres-1`.
Host ports **8069 and 5432 are already LISTENING**. Therefore:

- `COMPOSE_PROJECT_NAME` defaults to **`odoo19-bct`**, not `odoo19-platform`.
- Container naming: `${COMPOSE_PROJECT_NAME:-odoo19-bct}-<service>`.
- Port block for this project is **38xxx / 35xxx / 36xxx**, all bound to `127.0.0.1` only:

  | Service | Host port |
  |---|---|
  | odoo http | `127.0.0.1:38069` |
  | odoo longpolling | `127.0.0.1:38072` |
  | postgres | `127.0.0.1:35432` |
  | redis | `127.0.0.1:36379` |
  | grafana | `127.0.0.1:33001` |
  | prometheus | `127.0.0.1:39090` |
  | alertmanager | `127.0.0.1:39093` |
  | loki | `127.0.0.1:33100` |

  Reserved for later agents — do not bind them: warehouse db `35433`, login-gateway `38120`,
  semantic-api `38200`, insight-portal `33000`.
- Never run a bare `docker compose down` / `docker system prune` / `docker volume prune`. Those hit
  other projects. Always scope: `docker compose -p odoo19-bct ...`.

## Scope — in
1. `odoo/Dockerfile` — `FROM odoo:19.0@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`.
   Non-root runtime user. Strip SUID/SGID bits. `apt-get --only-upgrade` the OS openssl/libssl only.
   Install `postgresql-client` (scripts need `psql`). Pin every `apt` and `pip` install.
   `HEALTHCHECK` that actually exercises Odoo, not just a TCP open.
2. `odoo/odoo.conf` — `list_db` off by default, `proxy_mode` on, workers sized for a dev box,
   `admin_passwd` from env, `addons_path` covering `/mnt/extra-addons`.
3. `postgres/postgresql.conf` + `postgres/init/*.sql` — **`wal_level = logical`**,
   `max_replication_slots = 10`, `max_wal_senders = 10`, and **`max_slot_wal_keep_size = 2GB`**.
   That last one is mandatory: master prompt §7.9 — a slot with no retention cap is exactly how a
   warehouse outage becomes an Odoo outage. Create the `odoo` role, and a **separate
   `warehouse_reader` role holding only `SELECT` + `REPLICATION`** (master prompt §2, "read-only by
   construction"). The warehouse must be structurally incapable of writing to Odoo.
4. `docker-compose.yml` (base) — services `postgres`, `redis`, `odoo`. YAML anchors `*restart-policy`
   and `*default-logging`; every service gets `security_opt: [no-new-privileges:true]`,
   `cap_drop: [ALL]` (add back only what is provably needed), a real `healthcheck`, and the container
   naming above. Named volumes, one explicit network.
5. `docker-compose.dev.yml` — dev overlay: bind-mounts, the localhost-only ports above, dev logging.
6. `docker-compose.observability.yml` — prometheus, grafana, loki, alertmanager, postgres_exporter,
   node_exporter. Grafana provisioning under `observability/grafana/provisioning/`. Leave a
   documented drop-in directory for `analytics-*.json` — the DWH agent owns those files, you own the
   mechanism that loads them.
7. `.env.example` — every variable the stack reads. **Every secret value is literally `changeme`.**
   No generated value, no plausible-looking placeholder.
8. `scripts/gen-env-secrets.py` — generate real dev secrets into `.env` from `.env.example`.
   `scripts/init-db.sh`, `scripts/tenant-provision.sh`, `scripts/tenant-backup.sh`,
   `scripts/tenant-restore.sh`. Backup/restore must cover **both** database and filestore.
9. `Makefile` — `help` (default target), `dev-bootstrap`, `up-dev`, `down`, `logs`, `ps`, `init-db`,
   `install-modules`, `shell`, `psql`, `tenant-provision`, `tenant-backup`, `tenant-restore`,
   `scan-secret`. `make help` self-documents every target.
10. `.gitattributes` — **required, not optional.** The host is Windows; a CRLF line ending on a
    mounted `.sh` produces `bad interpreter: /bin/sh^M` inside the container and will cost hours.
    Force `text eol=lf` for `*.sh`, `*.py`, `*.sql`, `Dockerfile`, `Makefile`. Also `.editorconfig`
    and a `.gitignore` excluding `.env`, `data/`, `*.bak-*`, dbt `target/`.

## Scope — out
- `addons/**` — **Platform-Addons owns it.** You create the mount point and the `addons_path` entry;
  you do not write a single module.
- `analytics/**`, `docker-compose.analytics.yml` — Data Warehouse agent.
- `login-gateway/**` — Backend agent.
- `.github/workflows/**`, `.pre-commit-config.yaml`, `.sops.yaml`, `.gitleaks.toml`, `.semgrep/**` —
  **Security agent owns all of these.** Do not create them, not even as stubs.
- `insight-portal/**` — Frontend agent.
- `observability/grafana/analytics-*.json`, `observability/prometheus/analytics-*.yml` — DWH agent.

## Contracts consumed
None. You are the root of the dependency graph.

## Contracts produced — other agents depend on these exact names
Publish to `docs/agents/contracts/04-platform.md`. That is the **only** file you may create under
`docs/agents/contracts/`.
- Compose network name, volume names, and the `postgres` service hostname/port as reachable from a
  sibling compose overlay.
- Postgres roles `odoo` (owner) and `warehouse_reader` (SELECT + REPLICATION only), with the exact
  connection-URI shape for each.
- Pasted `SHOW` output proving `wal_level`, `max_replication_slots`, `max_wal_senders` and
  `max_slot_wal_keep_size` are live.
- The `.env` variable names, so DWH/Backend/Frontend extend rather than rename them.
- The Makefile target namespace already taken, so `up-analytics` / `dbt-run` / `dbt-test` /
  `warehouse-backup` cannot collide.
- The reserved port block, restated, so no later agent picks a bound port.

## Constraints
- Base stack (postgres + redis + odoo) must idle **under 4 GiB**. The eventual target is a single
  Biznet Gio VPS also carrying Prometheus/Grafana/Loki and later the warehouse plus two Next.js
  services. Report measured `docker stats`.
- No secret in any tracked file. `changeme` only.
- Multi-tenant by construction: `tenant-provision.sh` takes a tenant slug and creates its database.
  Phase 3 extends this same script for warehouse onboarding — design it to be extended and mark in a
  comment exactly where that hook goes.
- Ports bound to `127.0.0.1`, never `0.0.0.0`.

## Acceptance criteria — testable statements only
1. `docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q` exits 0.
2. From clean (`docker compose -p odoo19-bct down -v`), `make dev-bootstrap && make up-dev` reaches
   all services `healthy` within 300 s, unattended.
3. `docker compose exec -T postgres psql -U odoo -tAc "show wal_level"` prints `logical`.
4. `show max_slot_wal_keep_size` prints a bounded value, not `-1`.
5. `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:38069/web/login` prints `200`.
6. `docker compose exec -T odoo id -u` prints a non-zero uid.
7. `docker compose exec -T odoo find / -xdev -perm /6000 -type f` prints nothing.
8. `warehouse_reader` succeeds on `SELECT` and **fails** on `CREATE TABLE` and on
   `INSERT`/`UPDATE`/`DELETE` against an Odoo table. Paste both the success and the permission denial.
9. No real secret in `.env.example`.
10. `make help` lists every target with a description.
11. `docker ps` still shows `odoo19-platform-*` and `odoo19-analytics-*` healthy and untouched.

## Evidence required — paste the output of exactly these
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q && echo CONFIG_OK
make dev-bootstrap && make up-dev
docker compose ps
docker compose exec -T postgres psql -U odoo -tAc "show wal_level; show max_replication_slots; show max_wal_senders; show max_slot_wal_keep_size;"
curl -s -o /dev/null -w 'login=%{http_code}\n' http://127.0.0.1:38069/web/login
docker compose exec -T odoo id
docker compose exec -T odoo find / -xdev -perm /6000 -type f | head
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
make help
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'odoo19-(platform|analytics)' | head
```

## Escalation triggers — stop and return to Lead
- The `odoo:19.0` image entrypoint cannot run as non-root without breaking the filestore.
- Odoo 19 rejects a `postgresql.conf` setting required for logical decoding.
- You believe you need to write outside your owned paths. Raise it — do not "just this once" it.
- The base stack cannot idle under 4 GiB.
- Any action you are about to take could affect a container outside project `odoo19-bct`.
