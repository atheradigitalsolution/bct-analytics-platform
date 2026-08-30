#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bring the dev stack up and leave it actually usable.
#
#     make up-dev
#
# "Usable" means /web/login returns 200, not merely that three containers are
# running. That requires the database to be initialised, and initialisation has
# to happen while Postgres is up but before the long-running Odoo server is
# expected to be healthy — so the order below is not incidental:
#
#   1. postgres + redis        (odoo depends_on both being healthy)
#   2. init-db                 one-off `docker compose run`, idempotent
#   3. odoo                    now its healthcheck can hit a real database
#   4. wait                    with a real timeout and real logs on failure
#
# Doing 2 after 3 would leave Odoo unhealthy for its whole start_period on a
# clean machine, and would make `make up-dev` non-deterministic.
# ---------------------------------------------------------------------------
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

BUILD=1
SKIP_INIT=0
while [ $# -gt 0 ]; do
    case "$1" in
        --no-build)  BUILD=0; shift ;;
        --skip-init) SKIP_INIT=1; shift ;;
        -h|--help)
            printf 'usage: %s [--no-build] [--skip-init]\n' "$0" >&2; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

require_docker
[ -f "$ENV_FILE" ] || die ".env not found — run 'make dev-bootstrap' first."
load_env

[ -d "$REPO_ROOT/addons" ] || mkdir -p "$REPO_ROOT/addons"

if [ "$BUILD" -eq 1 ]; then
    log "[1/4] building the odoo image"
    dc build odoo
fi

log "[2/4] starting postgres and redis"
dc up -d postgres redis
WAIT_TIMEOUT=180 wait_healthy postgres redis || die "postgres/redis did not become healthy."

if [ "$SKIP_INIT" -eq 0 ]; then
    log "[3/4] ensuring the database is initialised"
    "$REPO_ROOT/scripts/init-db.sh"
else
    log "[3/4] skipping database init (--skip-init)"
fi

log "[4/4] starting odoo"
dc up -d
WAIT_TIMEOUT=180 wait_healthy postgres redis odoo || die "odoo did not become healthy."

URL="http://${BIND_ADDRESS:-127.0.0.1}:${ODOO_HOST_HTTP_PORT:-38069}/web/login"
code="$(curl -s -o /dev/null -w '%{http_code}' "$URL" || echo 000)"
if [ "$code" = "200" ]; then
    log "stack is up. $URL -> HTTP $code"
else
    warn "$URL returned HTTP $code (expected 200). Recent odoo logs:"
    dc logs --tail 40 odoo >&2 || true
    exit 1
fi

dc ps
