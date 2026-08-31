#!/usr/bin/env bash
# ===========================================================================
# warehouse-backup.sh — logical dump of the analytics warehouse.
#
#   bash analytics/warehouse/bin/warehouse-backup.sh [--out DIR]
#   bash analytics/warehouse/bin/warehouse-backup.sh --restore DIR
#
# Follows scripts/tenant-backup.sh's conventions exactly, because one runbook
# is the whole point of ADR 0001 choosing Postgres: same layout, same
# pg_dump --format=custom --compress=9 --no-owner --no-acl, same manifest.json,
# same SHA256SUMS verified BEFORE anything is dropped.
#
# WHAT IS AND IS NOT BACKED UP, and why the difference matters here more than
# it does for the ERP:
#
#   raw.*        BACKED UP. It is the append-only landing zone and it is the
#                only copy of history that Odoo no longer has - a row updated
#                five times in Odoo leaves one current value there and five
#                versions here.
#   marts, staging, snapshots   BACKED UP, but they are DERIVED: `dbt build`
#                reproduces marts and staging from raw exactly. The snapshots
#                schema is the exception that justifies backing the rest up
#                anyway - SCD2 history is NOT reproducible from raw once the
#                landing zone has been trimmed, because a snapshot records what
#                the world looked like when it ran.
#   warehouse.*  BACKED UP. column_policy is re-derivable from custom_pdp_core,
#                but pipeline_state is not: losing it means the CDC consumer
#                does not know where it stopped.
#
# NO FILESTORE HALF. tenant-backup.sh insists on both halves because an Odoo
# database without its filestore restores to broken attachments. The warehouse
# has no filestore: `ir_attachment` is never replicated (custom_pdp_core §7 -
# an attachment can be anything at all, a scanned KTP included, and there is no
# classification that would make it safe). So one file is a COMPLETE backup
# here, and that is a property of the design rather than an omission.
# ===========================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

PROJECT="${PROJECT:-odoo19-bct}"
DC=(docker compose -p "$PROJECT" -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.analytics.yml)

# shellcheck disable=SC1091
set -a; . ./.env; set +a

WH_ADMIN="${WAREHOUSE_ADMIN_USER:-warehouse_admin}"
WH_DB="${WAREHOUSE_DB:-warehouse}"
OUT_ROOT="${BACKUP_DIR:-./backups}/warehouse"
MODE=backup
RESTORE_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --out)     OUT_ROOT="$2"; shift 2 ;;
    --restore) MODE=restore; RESTORE_DIR="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '  %s\n' "$*" >&2; }

# --- restore ---------------------------------------------------------------
if [ "$MODE" = restore ]; then
  [ -d "$RESTORE_DIR" ] || { echo "no such backup directory: $RESTORE_DIR" >&2; exit 1; }
  log "[1/3] verifying SHA256SUMS BEFORE touching the database"
  ( cd "$RESTORE_DIR" && sha256sum -c SHA256SUMS ) >&2

  log "[2/3] restoring into database ${WH_DB}"
  # --clean --if-exists rather than DROP DATABASE: dbt, the CDC loader and the
  # semantic API all hold pooled connections, and DROP DATABASE fails while any
  # session is attached. This restores in place and is what a real recovery
  # would do with services running.
  MSYS_NO_PATHCONV=1 "${DC[@]}" exec -T -e PGPASSWORD="${WAREHOUSE_ADMIN_PASSWORD}" warehouse-db \
    pg_restore --clean --if-exists --no-owner --no-acl \
               -U "$WH_ADMIN" -d "$WH_DB" < "$RESTORE_DIR/database.dump"

  log "[3/3] re-applying the tracked DDL (roles, grants, RLS functions)"
  # A dump carries objects, not role passwords or ALTER ROLE settings. Without
  # this the restored warehouse has its tables and none of the privilege
  # separation that makes RLS mean anything.
  bash analytics/warehouse/bin/warehouse-apply.sh >/dev/null
  log "restore complete. Run 'make dbt-run' to rebuild derived models."
  exit 0
fi

# --- backup ----------------------------------------------------------------
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_ROOT/$STAMP"
mkdir -p "$DEST"

log "[1/3] pg_dump (custom format, compress 9)"
MSYS_NO_PATHCONV=1 "${DC[@]}" exec -T -e PGPASSWORD="${WAREHOUSE_ADMIN_PASSWORD}" warehouse-db \
  pg_dump --format=custom --compress=9 --no-owner --no-acl \
          -U "$WH_ADMIN" -d "$WH_DB" > "$DEST/database.dump"
[ -s "$DEST/database.dump" ] || { echo "pg_dump produced an empty file." >&2; exit 1; }

log "[2/3] manifest"
DEST="$DEST" WH_DB="$WH_DB" STAMP="$STAMP" python3 - <<'PY'
import hashlib, json, os, subprocess, sys

dest = os.environ["DEST"]
entries = {}
for name in sorted(os.listdir(dest)):
    path = os.path.join(dest, name)
    if not os.path.isfile(path) or name in ("manifest.json", "SHA256SUMS"):
        continue
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    entries[name] = {"sha256": h.hexdigest(), "bytes": os.path.getsize(path)}


def git(*args):
    try:
        return subprocess.check_output(["git", *args], text=True).strip()
    except Exception:
        return None


manifest = {
    "kind": "analytics-warehouse",
    "database": os.environ["WH_DB"],
    "taken_at_utc": os.environ["STAMP"],
    "files": entries,
    "total_bytes": sum(e["bytes"] for e in entries.values()),
    "git_commit": git("rev-parse", "HEAD"),
    "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
    # Recorded because a warehouse dump is only meaningful against the dbt
    # project that built it: restoring this dump and running a different
    # revision's models produces marts that match neither.
    "note": "Derived schemas (staging, marts) are reproducible from raw by `dbt build`; "
            "snapshots and warehouse.pipeline_state are NOT.",
}
with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
with open(os.path.join(dest, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as fh:
    for name, meta in entries.items():
        fh.write(f"{meta['sha256']}  {name}\n")
print(f"    {manifest['total_bytes'] / 1024 / 1024:.1f} MiB", file=sys.stderr)
PY

log "[3/3] verifying the checksums just written"
( cd "$DEST" && sha256sum -c SHA256SUMS ) >&2

log "backup complete: $DEST"
