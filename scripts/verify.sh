#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run every Phase 1 acceptance check and print the evidence, verbatim.
#
#     make verify
#
# This exists so the Lead's review (PLAN.md, "Lead review duty": no claim is
# accepted on assertion) is a single command that either exits 0 or shows
# exactly which criterion failed. It re-runs the commands from the brief's
# "Evidence required" block, in order, and adds the checks that block does not
# cover.
# ---------------------------------------------------------------------------
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

require_docker
load_env

PASS=0
FAIL=0
RESULTS=()

step() { printf '\n\033[1m=== %s ===\033[0m\n' "$*"; }

check() {
    local label="$1"; shift
    if "$@"; then
        RESULTS+=("PASS  $label")
        PASS=$((PASS + 1))
    else
        RESULTS+=("FAIL  $label")
        FAIL=$((FAIL + 1))
    fi
}

# 1 -------------------------------------------------------------------------
step "1. compose config validates"
check "compose config -q exits 0" \
    bash -c 'docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q && echo CONFIG_OK'

# 2 -------------------------------------------------------------------------
step "2. services healthy"
dc ps
check "postgres healthy" bash -c "[ \"\$(docker inspect -f '{{.State.Health.Status}}' ${COMPOSE_PROJECT_NAME}-postgres)\" = healthy ]"
check "redis healthy"    bash -c "[ \"\$(docker inspect -f '{{.State.Health.Status}}' ${COMPOSE_PROJECT_NAME}-redis)\"    = healthy ]"
check "odoo healthy"     bash -c "[ \"\$(docker inspect -f '{{.State.Health.Status}}' ${COMPOSE_PROJECT_NAME}-odoo)\"     = healthy ]"

# 3 and 4 -------------------------------------------------------------------
step "3+4. postgres logical decoding settings"
dc exec -T postgres psql -U odoo -tAc \
    "show wal_level; show max_replication_slots; show max_wal_senders; show max_slot_wal_keep_size;"
check "wal_level = logical" bash -c \
    "[ \"\$(docker compose -p $COMPOSE_PROJECT_NAME -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U odoo -tAc 'show wal_level')\" = logical ]"
check "max_slot_wal_keep_size is bounded (not -1)" bash -c \
    "v=\$(docker compose -p $COMPOSE_PROJECT_NAME -f docker-compose.yml -f docker-compose.dev.yml exec -T postgres psql -U odoo -tAc 'show max_slot_wal_keep_size'); echo \"  value=\$v\"; [ \"\$v\" != '-1' ] && [ -n \"\$v\" ]"

# 5 -------------------------------------------------------------------------
step "5. /web/login returns 200"
URL="http://${BIND_ADDRESS:-127.0.0.1}:${ODOO_HOST_HTTP_PORT:-38069}/web/login"
curl -s -o /dev/null -w "login=%{http_code}\n" "$URL"
check "/web/login = 200" bash -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' '$URL')\" = 200 ]"

# 6 -------------------------------------------------------------------------
step "6. odoo runs as a non-root uid"
dc exec -T odoo id
check "odoo uid != 0" bash -c \
    "[ \"\$(docker compose -p $COMPOSE_PROJECT_NAME -f docker-compose.yml -f docker-compose.dev.yml exec -T odoo id -u | tr -d '\r')\" != 0 ]"

# 7 -------------------------------------------------------------------------
step "7. no setuid/setgid binaries in the odoo image"
suid="$(dc exec -T odoo find / -xdev -perm /6000 -type f 2>/dev/null | tr -d '\r' || true)"
if [ -n "$suid" ]; then printf '%s\n' "$suid"; else echo "(none)"; fi
check "no SUID/SGID files" bash -c "[ -z \"$suid\" ]"

# 8 -------------------------------------------------------------------------
step "8. warehouse_reader is read-only by construction"
check "warehouse-reader-check.sh" bash "$REPO_ROOT/scripts/warehouse-reader-check.sh"

# 9 -------------------------------------------------------------------------
step "9. no real secret in tracked files"
check "scan-secrets" python3 "$REPO_ROOT/scripts/scan-secrets.py"

# 10 ------------------------------------------------------------------------
step "10. make help documents every target"
# `make help` colourises target names, so the raw output starts each line with
# an ANSI escape, not the target. Strip escapes before comparing, or every
# single target reads as undocumented.
help_targets="$(make -s -C "$REPO_ROOT" help 2>/dev/null \
                | sed 's/\x1b\[[0-9;]*m//g' \
                | grep -E '^ {4}[a-zA-Z0-9_-]+ ' \
                | awk '{print $1}' | sort -u)"
phony_targets="$(grep -Eo '^\.PHONY: [a-zA-Z0-9_-]+' "$REPO_ROOT/Makefile" \
                | awk '{print $2}' | sort -u)"
undocumented="$(comm -23 <(printf '%s\n' "$phony_targets") <(printf '%s\n' "$help_targets"))"
if [ -n "$undocumented" ]; then echo "undocumented targets:"; printf '  %s\n' $undocumented; else echo "every .PHONY target appears in 'make help'"; fi
check "no undocumented targets" bash -c "[ -z \"$undocumented\" ]"

# 11 ------------------------------------------------------------------------
step "11. other stacks on this host are untouched"
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'odoo19-(platform|analytics)' | head
check "odoo19-platform-odoo still up" bash -c \
    "docker ps --format '{{.Names}}\t{{.Status}}' | grep -q 'odoo19-platform-odoo.*Up'"
check "odoo19-analytics-odoo still up" bash -c \
    "docker ps --format '{{.Names}}\t{{.Status}}' | grep -q 'odoo19-analytics-odoo.*Up'"

# 12 ------------------------------------------------------------------------
step "12. .gitignore does not silently drop a file that must ship"
check "gitignore guard" python3 "$REPO_ROOT/scripts/check-gitignore.py"

# 13 ------------------------------------------------------------------------
step "13. the alerting path is armed, not merely syntactically valid"
check "alerting armed" python3 "$REPO_ROOT/scripts/check-alerting.py"

# 14 ------------------------------------------------------------------------
step "14. the dev login credential is applied, and Odoo's default is refused"
# PLAN.md instance 10. The half of this that matters is the NEGATIVE: a check
# that only asserts "$BCT_DEV_USER_PASSWORD logs in" is green on a stack that
# accepts BOTH passwords, which is precisely the defective state. So
# --check requires authenticate('bct','admin','admin') to be False.
check "dev password applied, default rejected" \
    bash "$REPO_ROOT/scripts/set-dev-passwords.sh" --check

# base-stack footprint ------------------------------------------------------
step "base stack memory (constraint: idle under 4 GiB)"
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}' \
    "${COMPOSE_PROJECT_NAME}-postgres" "${COMPOSE_PROJECT_NAME}-redis" "${COMPOSE_PROJECT_NAME}-odoo"
total_mib="$(docker stats --no-stream --format '{{.MemUsage}}' \
    "${COMPOSE_PROJECT_NAME}-postgres" "${COMPOSE_PROJECT_NAME}-redis" "${COMPOSE_PROJECT_NAME}-odoo" \
    | awk '{print $1}' | python3 -c '
import sys
total = 0.0
for line in sys.stdin:
    v = line.strip()
    if not v: continue
    n = float("".join(c for c in v if c.isdigit() or c == "."))
    if v.upper().endswith("GIB"): n *= 1024
    elif v.upper().endswith("KIB"): n /= 1024
    elif v.upper().endswith("B") and not v.upper().endswith(("MIB","GIB","KIB")): n /= 1024*1024
    total += n
print(f"{total:.1f}")')"
echo "  base stack total: ${total_mib} MiB (limit 4096 MiB)"
check "base stack idles under 4 GiB" bash -c "python3 -c \"import sys; sys.exit(0 if $total_mib < 4096 else 1)\""

# --- summary ---------------------------------------------------------------
printf '\n\033[1m=== summary ===\033[0m\n'
printf '%s\n' "${RESULTS[@]}"
printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
