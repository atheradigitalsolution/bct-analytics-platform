#!/usr/bin/env bash
# Run the semantic API.
#
# Reserved port 38200 (contract 04 section 4), bound to 127.0.0.1 only.
#
# Connects as warehouse_rls, which holds SELECT and nothing else and is NOSUPERUSER NOBYPASSRLS, so
# row-level security genuinely applies to it. Never as `warehouse` (that is dbt's transform role,
# which has a policy allowing it to read unscoped) and never as `warehouse_admin` (a superuser,
# which bypasses RLS unconditionally). Contract 05 section A.2.
#
# It holds ONE database DSN, to the warehouse. It has no route to Odoo's OLTP Postgres at all,
# which is how anti-pattern 7.3 is prevented structurally rather than by policy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
set -a; . "$ROOT/.env"; set +a

NAME="odoo19-bct-semantic-api"
DETACH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --detach) DETACH="-d"; shift ;;
    *) break ;;
  esac
done

docker rm -f "$NAME" >/dev/null 2>&1 || true

DSN="host=${SEMANTIC_API_WAREHOUSE_HOST:-warehouse-db} port=${SEMANTIC_API_WAREHOUSE_PORT:-5432}"
DSN="$DSN dbname=${WAREHOUSE_DB} user=${WAREHOUSE_RLS_USER} password=${WAREHOUSE_RLS_PASSWORD}"

# MSYS_NO_PATHCONV is scoped to this one invocation, never exported (contract 04 section 11).
# shellcheck disable=SC2086
exec env MSYS_NO_PATHCONV=1 docker run --rm $DETACH --name "$NAME" \
  --network odoo19-bct_bct \
  -p "${BIND_ADDRESS:-127.0.0.1}:${SEMANTIC_API_HOST_PORT:-38200}:8080" \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --read-only \
  -e SEMANTIC_API_WAREHOUSE_DSN="$DSN" \
  -e SEMANTIC_API_JWKS_URL="${SEMANTIC_API_JWKS_URL:-http://login-gateway:8080/.well-known/jwks.json}" \
  -e SEMANTIC_API_JWT_ISSUER="${SEMANTIC_API_JWT_ISSUER:-${LOGIN_GATEWAY_JWT_ISSUER}}" \
  -e SEMANTIC_API_JWT_AUDIENCE="${SEMANTIC_API_JWT_AUDIENCE:-${LOGIN_GATEWAY_JWT_AUDIENCE}}" \
  -e SEMANTIC_API_MAX_LIMIT="${SEMANTIC_API_MAX_LIMIT:-5000}" \
  odoo19-bct-semantic-api:local "$@"
