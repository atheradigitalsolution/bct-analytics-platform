# ===========================================================================
# odoo19-bct — developer entry points.
#
#   make                 same as `make help`
#   make dev-bootstrap   one-time setup on a fresh clone
#   make up-dev          bring the stack up and leave /web/login answering 200
#
# EVERY docker compose invocation in this file is scoped with -p $(PROJECT).
# This host also runs odoo19-platform-*, odoo19-analytics-* and
# smart-warga-postgres-1. An unscoped `docker compose down` or a
# `docker system prune` would hit them, and their data is not recoverable from
# here. There is no target in this file that can touch another project.
#
# Recipes are shell, so lines are tab-indented. See .editorconfig.
# ===========================================================================

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
.ONESHELL:

PROJECT      ?= odoo19-bct
COMPOSE_BASE := docker-compose.yml
COMPOSE_DEV  := docker-compose.dev.yml
COMPOSE_OBS  := docker-compose.observability.yml
COMPOSE_ANALYTICS := docker-compose.analytics.yml

DC     := docker compose -p $(PROJECT) -f $(COMPOSE_BASE) -f $(COMPOSE_DEV)
DC_OBS := docker compose -p $(PROJECT) -f $(COMPOSE_BASE) -f $(COMPOSE_DEV) -f $(COMPOSE_OBS)

# Optional argument variables, documented per target:
#   TENANT=<slug>   MODULES=<a,b>   FROM=<backup dir>   INTO=<slug>   SERVICE=<name>
TENANT  ?=
MODULES ?=
FROM    ?=
INTO    ?=
SERVICE ?=
ARGS    ?=

# python3, not python: the Windows hosts here have no `python` on PATH.
PYTHON  ?= python3
OUT     ?=

# ---------------------------------------------------------------------------
# help — the default target.
#
# Descriptions are parsed out of the `## ` comment after each target name, so a
# new target is self-documenting the moment it is written and cannot drift out
# of sync with a hand-maintained list.
# ---------------------------------------------------------------------------
.PHONY: help
help: ## Show this help (default target)
	@echo ""
	@echo "  odoo19-bct - Odoo 19 CE + Postgres 16 (wal_level=logical) + Redis 7"
	@echo "  project: $(PROJECT)   ports: 127.0.0.1 38069/38072/35432/36379"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} \
	     /^# ==== / { printf "\n  \033[1m%s\033[0m\n", substr($$0, 8); next } \
	     /^[a-zA-Z0-9_-]+:.*?## / { printf "    \033[36m%-22s\033[0m %s\n", $$1, $$2 }' \
	     $(MAKEFILE_LIST)
	@echo ""
	@echo "  variables:  TENANT=<slug>  MODULES=<a,b>  FROM=<dir>  INTO=<slug>  SERVICE=<name>"
	@echo ""

# ==== Setup

.PHONY: dev-bootstrap
dev-bootstrap: ## One-time setup: generate .env, create addons/, verify ports and line endings
	@bash scripts/dev-bootstrap.sh

.PHONY: build
build: ## Rebuild the Odoo image (pinned digest; no cache reuse for apt layers)
	@$(DC) build odoo

.PHONY: config
config: ## Validate and print the merged compose configuration
	@$(DC) config -q && echo "CONFIG_OK"

# ==== Lifecycle

.PHONY: up-dev
up-dev: ## Start the dev stack, initialise the database, wait for healthy
	@bash scripts/up-dev.sh

.PHONY: down
down: ## Stop and remove this project's containers (volumes are KEPT)
	@echo "scoped to project $(PROJECT) only — other stacks on this host are untouched"
	@$(DC_OBS) down --remove-orphans

.PHONY: down-hard
down-hard: ## DESTRUCTIVE: down + delete this project's volumes (all data lost)
	@echo ""
	@echo "  This deletes volumes $(PROJECT)_pgdata, _odoodata, _redisdata."
	@echo "  Every database and every filestore in project $(PROJECT) is lost."
	@echo "  Other projects on this host are NOT affected."
	@echo ""
	@read -r -p "  Type the project name to confirm: " reply; \
	 if [ "$$reply" = "$(PROJECT)" ]; then \
	     $(DC_OBS) down -v --remove-orphans; \
	 else \
	     echo "  aborted."; exit 1; \
	 fi

.PHONY: restart
restart: ## Restart services (SERVICE=<name> for one, default all)
	@$(DC) restart $(SERVICE)

.PHONY: ps
ps: ## Show this project's containers and health
	@$(DC) ps

.PHONY: logs
logs: ## Follow logs (SERVICE=<name> for one, default all)
	@$(DC) logs -f --tail=200 $(SERVICE)

.PHONY: stats
stats: ## One-shot memory and CPU usage for this project's containers
	@docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' \
	    $$($(DC_OBS) ps -q 2>/dev/null) 2>/dev/null || \
	 docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'

# ==== Database

.PHONY: init-db
init-db: ## Create and initialise the default Odoo database (idempotent)
	@bash scripts/init-db.sh $(if $(MODULES),--modules $(MODULES),)

.PHONY: install-modules
install-modules: ## Install/upgrade modules: make install-modules MODULES=custom_pdp_core
	@test -n "$(MODULES)" || { echo "MODULES is required, e.g. MODULES=custom_pdp_core,custom_ppob"; exit 1; }
	@bash scripts/init-db.sh --modules "$(MODULES)" --force

.PHONY: psql
psql: ## Open a psql shell as the odoo superuser (TENANT=<slug> for another database)
	@$(DC) exec postgres psql -U odoo -d $(if $(TENANT),$(TENANT),$${ODOO_DB_NAME:-bct})

.PHONY: shell
shell: ## Open an Odoo shell (ORM REPL) against the default database
	@$(DC) exec odoo odoo shell -d $${ODOO_DB_NAME:-bct} --no-http

.PHONY: sh
sh: ## Open a plain shell in a container (SERVICE=odoo|postgres|redis)
	@$(DC) exec $(if $(SERVICE),$(SERVICE),odoo) bash 2>/dev/null || \
	 $(DC) exec $(if $(SERVICE),$(SERVICE),odoo) sh

# ==== Tenants

.PHONY: tenant-provision
tenant-provision: ## Create a tenant database: make tenant-provision TENANT=acme
	@test -n "$(TENANT)" || { echo "TENANT is required, e.g. make tenant-provision TENANT=acme"; exit 1; }
	@bash scripts/tenant-provision.sh "$(TENANT)" $(if $(MODULES),--modules $(MODULES),) $(ARGS)

.PHONY: tenant-backup
tenant-backup: ## Back up a tenant's DATABASE and FILESTORE: make tenant-backup TENANT=bct
	@test -n "$(TENANT)" || { echo "TENANT is required, e.g. make tenant-backup TENANT=bct"; exit 1; }
	@bash scripts/tenant-backup.sh "$(TENANT)" $(ARGS)

.PHONY: tenant-restore
tenant-restore: ## Restore a tenant: make tenant-restore TENANT=bct FROM=backups/bct/<stamp> [INTO=copy]
	@test -n "$(TENANT)" || { echo "TENANT is required"; exit 1; }
	@test -n "$(FROM)"   || { echo "FROM is required, e.g. FROM=backups/bct/20260831T041500Z"; exit 1; }
	@bash scripts/tenant-restore.sh "$(TENANT)" "$(FROM)" $(if $(INTO),--into $(INTO),) $(ARGS)

# ==== Verification

.PHONY: warehouse-reader-check
warehouse-reader-check: ## Prove warehouse_reader can SELECT and replicate but cannot write
	@bash scripts/warehouse-reader-check.sh $(if $(TENANT),--db $(TENANT),)

.PHONY: check-gitignore
check-gitignore: ## Fail if .gitignore would drop an addon data file or a dbt seed
	@python3 scripts/check-gitignore.py

.PHONY: check-alerting
check-alerting: ## Fail if a scrape target is down, Alertmanager is absent, or a rule can never fire
	@$(PYTHON) scripts/check-alerting.py

.PHONY: scan-secret
scan-secret: ## Fail if a real secret is committed, or .env.example drifts off `changeme`
	@python3 scripts/scan-secrets.py

.PHONY: verify
verify: ## Run every Phase 1 acceptance check and print the evidence
	@bash scripts/verify.sh

# ==== Tests

.PHONY: test
test: ## Run the integration suite in tests/ (ARGS='-k live' to filter)
	@bash tests/run.sh $(ARGS)

.PHONY: test-coldstart
test-coldstart: ## DESTRUCTIVE: cold-start suite; scoped to THIS project, other stacks checked after
	@bash scripts/coldstart-guard.sh $(ARGS)

.PHONY: metric-fixtures
metric-fixtures: ## Generate the semantic-api metric fixtures the Frontend agent builds against
	@$(PYTHON) scripts/analytics/metric-fixtures.py $(ARGS)

# ==== Observability

.PHONY: up-obs
up-obs: ## Start Prometheus, Grafana, Loki, Alertmanager and the exporters
	@$(DC_OBS) up -d prometheus grafana loki promtail alertmanager postgres-exporter node-exporter
	@echo "grafana      http://127.0.0.1:$${GRAFANA_HOST_PORT:-33001}"
	@echo "prometheus   http://127.0.0.1:$${PROMETHEUS_HOST_PORT:-39090}"
	@echo "alertmanager http://127.0.0.1:$${ALERTMANAGER_HOST_PORT:-39093}"

.PHONY: down-obs
down-obs: ## Stop only the observability services (the base stack keeps running)
	@$(DC_OBS) stop prometheus grafana loki promtail alertmanager postgres-exporter node-exporter
	@$(DC_OBS) rm -f prometheus grafana loki promtail alertmanager postgres-exporter node-exporter

# ==== Analytics warehouse (Data Warehouse agent)
#
# Every target here is scoped -p $(PROJECT) through $(DC_ANALYTICS), like the
# rest of this file. Names are taken from the namespace reserved in
# docs/agents/contracts/04-platform.md 6 and collide with nothing above.

DC_ANALYTICS := docker compose -p $(PROJECT) -f $(COMPOSE_BASE) -f $(COMPOSE_DEV) -f $(COMPOSE_ANALYTICS)

# `run --rm --no-deps`, not `exec`: dbt is a batch job, not a service. Leaving a
# restart-policy container idling would burn ~150 MiB of the VPS budget for
# something that runs for twelve seconds. --no-deps because the compose
# dependency is only there to order a `up`, and re-checking warehouse-db health
# on every invocation adds a second to every command.
DBT := MSYS_NO_PATHCONV=1 $(DC_ANALYTICS) run --rm --no-deps dbt
WCTL := MSYS_NO_PATHCONV=1 $(DC_ANALYTICS) run --rm --no-deps --entrypoint python dbt /warehouse/bin/warehouse_ctl.py

.PHONY: up-analytics
up-analytics: ## Start the warehouse, apply its DDL, sync the PDP policy and load the landing zone
	@# PRECONDITION, and it is here because the failure without it is a
	@# psycopg2 traceback ending in "could not translate host name postgres",
	@# which reads like a warehouse bug and is not one. The policy sync, the
	@# raw DDL generator and the reconciliation FDW all read the OLTP database
	@# as warehouse_reader; none of them can do anything useful without it.
	@$(DC_ANALYTICS) ps --services --filter status=running | grep -qx postgres || { 		echo ""; 		echo "  The base stack is not running. up-analytics reads Odoo's Postgres"; 		echo "  as warehouse_reader to sync the PDP policy, generate raw.* and wire"; 		echo "  the reconciliation FDW, and it cannot do any of that without it."; 		echo ""; 		echo "      make up-dev"; 		echo ""; 		exit 1; 	}
	@$(DC_ANALYTICS) up -d warehouse-db warehouse-exporter
	@# RESTART, not just up. The exporter reads
	@# analytics/warehouse/exporter/queries.yml from a bind mount, and
	@# `up -d` only recreates a container when its DEFINITION changes - a
	@# changed mounted file is invisible to it. That gap already produced
	@# one alert (MartStalePage) whose selector matched zero series while
	@# promtool passed and Prometheus reported health=ok. Restarting on
	@# every bring-up costs a second and removes the whole class.
	@$(DC_ANALYTICS) restart warehouse-exporter >/dev/null
	@bash analytics/warehouse/bin/warehouse-apply.sh
	@$(DC_ANALYTICS) --profile tools build dbt
	@$(WCTL) sync-policy
	@$(WCTL) gen-raw-ddl
	@$(WCTL) gen-fdw
	@$(WCTL) load-fixture --tenant bct_t2
	@echo "warehouse    127.0.0.1:$${WAREHOUSE_HOST_PORT:-35433}  (db $${WAREHOUSE_DB:-warehouse})"

.PHONY: down-analytics
down-analytics: ## Stop only the analytics services (the base stack keeps running)
	@$(DC_ANALYTICS) stop warehouse-db warehouse-exporter
	@$(DC_ANALYTICS) rm -f warehouse-db warehouse-exporter

.PHONY: dbt-run
dbt-run: ## Build every dbt model (seeds, snapshots, staging, marts)
	@$(DBT) build --exclude-resource-type test

.PHONY: dbt-test
dbt-test: ## Run every dbt test, including the reconciliation against live Odoo
	@$(DBT) test

.PHONY: dbt-docs
dbt-docs: ## Generate the dbt catalogue into analytics/dbt/target
	@$(DBT) docs generate

.PHONY: warehouse-backup
warehouse-backup: ## pg_dump the warehouse with a manifest and SHA256SUMS
	@bash analytics/warehouse/bin/warehouse-backup.sh $(if $(OUT),--out $(OUT),)

.PHONY: warehouse-restore
warehouse-restore: ## Restore a warehouse backup: make warehouse-restore FROM=backups/warehouse/<stamp>
	@test -n "$(FROM)" || { echo "FROM=<backup dir> is required"; exit 2; }
	@bash analytics/warehouse/bin/warehouse-backup.sh --restore $(FROM)

# ===========================================================================
# RESERVED — do not define these here.
#
# Namespace claimed by later agents (docs/agents/contracts/04-platform.md):
#   Data Warehouse : CLAIMED above, in the "Analytics warehouse" section.
#   Backend        : up-gateway  up-semantic  cdc-start  cdc-status
#   Frontend       : up-portal  portal-build
#
# Claimed since publication, on request via the Lead:
#   QA             : test  test-coldstart          (recipes here, tests/run.sh is QA's)
#   Backend        : metric-fixtures               (recipe here, the script is Backend's)
#   Security       : lint  sast  sbom  sign  ci-local
#
# Adding a target with one of those names silently overrides theirs, because
# make takes the LAST definition. Check this list before naming a new target.
# ===========================================================================
