#!/usr/bin/env bash
# Development fixture ONLY. Stands in for the Data Warehouse agent's warehouse-db until it lands.
#
# Contract 05 is Lead-frozen, so Backend builds against the frozen names rather than idling until
# DWH's DDL exists. This script brings up a throwaway Postgres that matches that contract exactly.
#
# Deliberate choices, so this cannot collide with anything real:
#   * NO published host port. Port 35433 is reserved for DWH's warehouse-db; taking it -- or any
#     other port -- would be squatting on an allocation that is not Backend's.
#   * Its own container name (odoo19-bct-cdc-fixture-db), not the service name `warehouse-db`, so
#     DWH's compose service can come up beside it without a name clash.
#   * Joined to the existing odoo19-bct_bct network, never creating one.
#   * Started with `docker run`, not a compose file, so no `docker compose down` anywhere can sweep
#     it up and no compose project is modified.
#
# Tear down with:  scripts/analytics/dev-warehouse-fixture.sh down
set -euo pipefail

NAME=odoo19-bct-cdc-fixture-db
NETWORK=odoo19-bct_bct
IMAGE='postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685'

repo_root() { cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd; }
ROOT="$(repo_root)"

# shellcheck disable=SC1091
set -a; . "$ROOT/.env"; set +a

case "${1:-up}" in
  down)
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    echo "fixture warehouse removed"
    exit 0
    ;;
  up) ;;
  *) echo "usage: $0 [up|down]" >&2; exit 2 ;;
esac

if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null || echo false)" = "true" ]; then
  echo "fixture warehouse already running"
else
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" \
    --network "$NETWORK" \
    --security-opt no-new-privileges \
    -e POSTGRES_DB="${WAREHOUSE_DB}" \
    -e POSTGRES_USER="${WAREHOUSE_DB_USER}" \
    -e POSTGRES_PASSWORD="${WAREHOUSE_DB_PASSWORD}" \
    "$IMAGE" >/dev/null
  echo "started $NAME on network $NETWORK (no host port bound)"
fi

for _ in $(seq 1 30); do
  if docker exec "$NAME" pg_isready -U "${WAREHOUSE_DB_USER}" -d "${WAREHOUSE_DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Contract 05's DDL, verbatim. DWH owns this table in production; the fixture creates it so the
# loader has something to read, and the loader itself still refuses to create it (see
# warehouse.ColumnPolicyMissing) so a missing DWH schema can never be papered over at runtime.
docker exec -i "$NAME" psql -U "${WAREHOUSE_DB_USER}" -d "${WAREHOUSE_DB}" -v ON_ERROR_STOP=1 <<'SQL'
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;

CREATE TABLE IF NOT EXISTS warehouse.column_policy (
  source_table   text NOT NULL,
  source_column  text NOT NULL,
  pdp_class      text NOT NULL
                 CHECK (pdp_class IN ('public','internal','personal','sensitive','secret')),
  transform      text NOT NULL
                 CHECK (transform IN ('none','hmac_sha256','hmac_sha256_nullable','drop')),
  mask_null      boolean NOT NULL DEFAULT false,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_table, source_column)
);
SQL

echo "fixture warehouse ready: contract-05 schemas and warehouse.column_policy created"
echo "seed the policy with: python scripts/analytics/dev-fixture-column-policy.py"
