#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Initialise the default Odoo database, idempotently.
#
#     scripts/init-db.sh [--modules base,web] [--force]
#
# Called automatically by `make up-dev`, so that a clean checkout reaches a
# working /web/login in two commands with no manual step in between.
#
# Idempotency matters here more than anywhere else: up-dev runs this on every
# invocation. If the database is already initialised it is a no-op and costs
# one query.
# ---------------------------------------------------------------------------
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

MODULES=""
FORCE=0

usage() {
    cat >&2 <<'USAGE'
usage: scripts/init-db.sh [options]

  --modules LIST   Comma-separated modules to install (default: $ODOO_INIT_MODULES
                   from .env, or "base,web").
  --force          Re-run the install even if the database already has an Odoo
                   schema. Does NOT drop data; it is `odoo -u`, not a reset.
  -h, --help       This message.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --modules) MODULES="${2:?--modules needs a value}"; shift 2 ;;
        --modules=*) MODULES="${1#*=}"; shift ;;
        --force) FORCE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

require_docker
load_env

DB="$ODOO_DB_NAME"
MODULES="${MODULES:-${ODOO_INIT_MODULES:-base,web}}"

require_healthy postgres

if db_initialised "$DB" && [ "$FORCE" -eq 0 ]; then
    log "database '$DB' already carries an Odoo schema — nothing to do."
    info "re-run with --force to update modules: $MODULES"
else
    if db_initialised "$DB"; then
        log "updating modules in '$DB': $MODULES"
        ODOO_ARGS=(-d "$DB" -u "$MODULES")
    else
        log "initialising database '$DB' with modules: $MODULES"
        # Odoo creates the database itself, with the encoding and LC_COLLATE it
        # requires (UTF8 / C from template0). Creating it by hand with createdb
        # risks a collation Odoo then rejects at registry load.
        ODOO_ARGS=(-d "$DB" -i "$MODULES")
    fi

    # --no-deps: postgres and redis are already up and healthy (checked above);
    # without it, `run` would start a second dependency chain.
    # --rm: the init container is disposable.
    # A separate one-off container rather than `exec` into the running server,
    # so this also works before the odoo service has ever started — which is
    # exactly the ordering `make up-dev` relies on.
    dc run --rm --no-deps -T odoo \
        odoo "${ODOO_ARGS[@]}" \
             --stop-after-init \
             --without-demo=True \
             --load-language=en_US

    db_initialised "$DB" || die "odoo exited 0 but '$DB' has no ir_module_module — check 'make logs'."
    log "database '$DB' initialised."
fi

# ---------------------------------------------------------------------------
# Baseline privileges. Applied on EVERY run, not only on first creation:
# installing a module creates new tables, and although ALTER DEFAULT PRIVILEGES
# covers them, re-applying makes the state converge even if someone installed a
# module by hand from the UI.
# ---------------------------------------------------------------------------
log "applying baseline privileges to '$DB' (warehouse_reader: SELECT only)"
dc exec -T postgres psql -v ON_ERROR_STOP=1 --no-psqlrc --quiet \
    -U "$POSTGRES_USER" -d "$DB" \
    -v dbname="$DB" \
    -v reader="$WAREHOUSE_READER_USER" \
    -f - < "$REPO_ROOT/scripts/lib/database-baseline.sql"

log "done. Odoo database '$DB' is ready."
info "login page: http://${BIND_ADDRESS:-127.0.0.1}:${ODOO_HOST_HTTP_PORT:-38069}/web/login"
