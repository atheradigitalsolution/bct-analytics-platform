#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Back up one tenant: DATABASE **and** FILESTORE.
#
#     scripts/tenant-backup.sh <slug> [--out DIR] [--keep-days N]
#
# Both halves, always. An Odoo backup that contains only the database restores
# to a system whose every attachment, logo, product image and generated PDF is
# a broken link — ir_attachment rows point at files under
# /var/lib/odoo/filestore/<db>/ that the dump does not contain. This is the
# single most common way an Odoo "backup" turns out not to be one.
#
# Output layout:
#     backups/<slug>/<UTC timestamp>/
#         database.dump     pg_dump -Fc  (compressed, restores with pg_restore)
#         filestore.tar.gz  tar of /var/lib/odoo/filestore/<db>
#         manifest.json     what was taken, from where, and its size
#         SHA256SUMS        integrity, verified by tenant-restore.sh
# ---------------------------------------------------------------------------
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

SLUG=""
OUT_ROOT=""
KEEP_DAYS=""

usage() {
    cat >&2 <<'USAGE'
usage: scripts/tenant-backup.sh <slug> [options]

  --out DIR        Backup root (default: $BACKUP_DIR from .env, or ./backups).
  --keep-days N    Delete backups for this tenant older than N days
                   (default: $BACKUP_RETENTION_DAYS, or 14). 0 disables pruning.
  -h, --help       This message.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --out)         OUT_ROOT="${2:?--out needs a value}"; shift 2 ;;
        --out=*)       OUT_ROOT="${1#*=}"; shift ;;
        --keep-days)   KEEP_DAYS="${2:?--keep-days needs a value}"; shift 2 ;;
        --keep-days=*) KEEP_DAYS="${1#*=}"; shift ;;
        -h|--help)     usage; exit 0 ;;
        -*)            die "unknown option: $1 (try --help)" ;;
        *)             [ -z "$SLUG" ] || die "only one slug may be given."; SLUG="$1"; shift ;;
    esac
done

[ -n "$SLUG" ] || { usage; die "a tenant slug is required."; }

require_docker
load_env
validate_slug "$SLUG"

DB="$SLUG"
OUT_ROOT="${OUT_ROOT:-$BACKUP_DIR}"
case "$OUT_ROOT" in /*|[A-Za-z]:*) ;; *) OUT_ROOT="$REPO_ROOT/${OUT_ROOT#./}" ;; esac
KEEP_DAYS="${KEEP_DAYS:-$BACKUP_RETENTION_DAYS}"

require_healthy postgres odoo
db_exists "$DB" || die "database '$DB' does not exist."

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$OUT_ROOT/$SLUG/$STAMP"
mkdir -p "$DEST"

log "backing up tenant '$SLUG' -> $DEST"

# --- 1. database ------------------------------------------------------------
# -Fc (custom format) rather than plain SQL: it is compressed, and pg_restore
# can then be selective and parallel on the way back in.
# --no-owner / --no-acl: privileges are re-applied from
# scripts/lib/database-baseline.sql on restore, so the dump never carries a
# stale grant for a role that may have been renamed or rotated.
log "[1/5] pg_dump (custom format)"
dc exec -T postgres pg_dump \
    -U "$POSTGRES_USER" -d "$DB" \
    --format=custom --compress=9 --no-owner --no-acl \
    > "$DEST/database.dump"

[ -s "$DEST/database.dump" ] || die "pg_dump produced an empty file."

# --- 2. filestore -----------------------------------------------------------
# Streamed as a tar over stdout: no temporary file inside the container, so a
# large filestore cannot fill the container's writable layer.
# `|| true` on the tar is deliberate for the empty case only — a brand new
# database has no filestore directory at all, and that is not an error.
log "[2/5] filestore tar"
if dc exec -T odoo test -d "/var/lib/odoo/filestore/$DB" 2>/dev/null; then
    dc exec -T odoo tar -C /var/lib/odoo/filestore -czf - "$DB" > "$DEST/filestore.tar.gz"
    [ -s "$DEST/filestore.tar.gz" ] || die "filestore tar produced an empty file."
else
    warn "no filestore directory for '$DB' yet (a fresh database has none); writing an empty archive."
    dc exec -T odoo tar -C /var/lib/odoo -czf - --files-from /dev/null > "$DEST/filestore.tar.gz"
fi

# --- 3. manifest ------------------------------------------------------------
# python3, not jq: jq is not installed on the target host and never will be a
# dependency of this repository.
log "[3/5] manifest"
python3 - "$DEST" "$SLUG" "$DB" "$STAMP" <<'PY'
import hashlib, json, os, subprocess, sys

dest, slug, db, stamp = sys.argv[1:5]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

files = {}
for name in ("database.dump", "filestore.tar.gz"):
    p = os.path.join(dest, name)
    files[name] = {"bytes": os.path.getsize(p), "sha256": sha256(p)}

def git(*args):
    try:
        return subprocess.check_output(("git",) + args, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None

manifest = {
    "schema_version": 1,
    "tenant_slug": slug,
    "database": db,
    "taken_at_utc": stamp,
    "components": ["database", "filestore"],
    "files": files,
    "source": {
        "compose_project": os.environ.get("COMPOSE_PROJECT_NAME"),
        "git_commit": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
    },
    "restore_with": f"scripts/tenant-restore.sh {slug} {dest}",
}

with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")

with open(os.path.join(dest, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as fh:
    for name, meta in sorted(files.items()):
        fh.write(f"{meta['sha256']}  {name}\n")

total = sum(m["bytes"] for m in files.values())
print(f"    manifest written; {total / 1024 / 1024:.1f} MiB total", file=sys.stderr)
PY

# --- 4. prune ---------------------------------------------------------------
log "[4/5] retention"
if [ "${KEEP_DAYS:-0}" -gt 0 ] 2>/dev/null; then
    # -mindepth/-maxdepth 1 so this can only ever match this tenant's dated
    # directories, never the tenant directory itself and never anything above
    # it. Deleting backups is the one operation here with no undo.
    pruned=0
    while IFS= read -r old; do
        [ -n "$old" ] || continue
        info "pruning $(basename "$old") (older than ${KEEP_DAYS}d)"
        rm -rf -- "$old"
        pruned=$((pruned + 1))
    done < <(find "$OUT_ROOT/$SLUG" -mindepth 1 -maxdepth 1 -type d -mtime "+$KEEP_DAYS" 2>/dev/null || true)
    info "pruned $pruned old backup(s); keeping ${KEEP_DAYS} days"
else
    info "retention disabled (--keep-days 0)"
fi

# --- 5. record in the registry ----------------------------------------------
# WITHOUT THIS STEP THE WHOLE BACKUP SURFACE IS A FACADE, and it was one.
# `tenant_registry.backups` has existed since 40-tenant-registry.sql created it,
# the orchestrator reads it, `tenant.backup` mirrors it, and the console lists
# it -- and NOTHING IN THIS REPOSITORY HAS EVER WRITTEN A ROW TO IT. Measured
# 2026-09-05: zero rows, no writer anywhere, and a grep for an INSERT finding
# only the CREATE TABLE. Every read above that table was reading an emptiness
# that no amount of running backups was ever going to fill.
#
# The backup on disk is the valuable artefact and it already exists by the time
# we get here, so a registry failure must not delete it. But it must not be
# swallowed either: a backup the console cannot see is, from the console's point
# of view, a backup that did not happen -- which is precisely the state this step
# exists to end. So the files stay, and the script exits 3 saying exactly that.
log "[5/5] registry"
# THROUGH `dc exec postgres psql`, THE SAME WAY EVERY OTHER STEP HERE TALKS TO
# THE DATABASE. The first version of this step used python3 + psycopg2 against
# ORCHESTRATOR_REGISTRY_DSN, and neither half was available: psycopg2 is not
# installed on the host, and that DSN names `host=postgres`, a Docker network
# alias the host cannot resolve. It would have exited 3 on every run on the very
# machine it was written for.
#
# The row goes into the CONTROL-PLANE database, not the tenant's. That is where
# tenant_registry lives.
#
# Values are passed as psql variables and interpolated with :'name', so psql
# does the quoting. The slug reaches this script from the command line.
RECORD_RC=0
_ADMIN_DB="${ATHERA_ADMIN_DB:-athera_admin}"
_TOTAL_BYTES="$(python3 - "$DEST" <<'SIZEPY'
import json, sys
m = json.load(open(sys.argv[1] + "/manifest.json", encoding="utf-8"))
print(sum(f["bytes"] for f in m["files"].values()))
SIZEPY
)"
# The DATABASE dump's sum, not a combined one. A restore cannot proceed without
# that half, and the filestore's own sum stays in SHA256SUMS beside it rather
# than being averaged into a number that verifies nothing.
_DB_SHA="$(awk '$2 == "database.dump" { print $1 }' "$DEST/SHA256SUMS")"

# THE SQL ARRIVES ON STDIN, NOT VIA -c. psql performs :'variable' interpolation
# in its own lexer, and a string handed to -c is passed to the server without
# going through it -- measured here as `syntax error at or near ":"`, with the
# backup already on disk and the operator correctly told the row was not written.
# Reading from stdin puts the lexer back in the path.
_SQL=$(cat <<'SQL'
INSERT INTO tenant_registry.backups
    (tenant_id, tenant_slug, kind, started_at, finished_at,
     size_bytes, path, checksum_sha256, outcome)
SELECT t.id, t.slug, 'manual',
       to_timestamp(:'stamp', 'YYYYMMDD"T"HH24MISS"Z"'), now(),
       :'total'::bigint, :'path', :'sha', 'success'
  FROM tenant_registry.tenants t
 WHERE t.slug = :'slug'
RETURNING id;
SQL
)

if _ROW_ID="$(printf '%s\n' "$_SQL" | dc exec -T postgres psql \
        -U "$POSTGRES_USER" -d "$_ADMIN_DB" -tAq -v ON_ERROR_STOP=1 \
        -v slug="$SLUG" -v stamp="$STAMP" -v path="$DEST" \
        -v total="${_TOTAL_BYTES:-0}" -v sha="${_DB_SHA:-}" 2>&1)" \
        && [ -n "$_ROW_ID" ]; then
    info "recorded in tenant_registry.backups as row $_ROW_ID"
else
    warn "registry insert did not return a row id: ${_ROW_ID:-<no output>}"
    RECORD_RC=3
fi

log "backup complete: $DEST"
ls -la "$DEST" >&2

if [ "$RECORD_RC" -ne 0 ]; then
    warn "The backup IS on disk at $DEST and is complete."
    warn "It was NOT recorded in tenant_registry.backups, so the super-admin"
    warn "console will not list it. Fix the registry connection and re-run, or"
    warn "record it by hand; do not delete this directory."
    exit 3
fi
