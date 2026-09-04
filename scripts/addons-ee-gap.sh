#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Put the ee_gap addon tree at addons/ee_gap/ and keep it there.
#
#     make addons-ee-gap          clone if absent, fast-forward if present
#     make addons-ee-gap CHECK=1  assert only; change nothing, fail if wrong
#
# WHY THIS EXISTS
#
# The 101 ee_gap modules moved to their own repository on 2026-09-04. They are
# product inventory, not dead code: eight of them are `installed` in the live
# databases, and seven of those eight are the dependency closure of the ATHERA
# control plane (custom_brd_analyzer, custom_hub_console,
# custom_onboarding_journey). The split was about CI cost -- 2 112 files through
# every lint and scan run -- and nothing else.
#
# So the RUNTIME path did not move. `odoo/odoo.conf` still lists
# /mnt/extra-addons/ee_gap in addons_path, and compose still bind-mounts
# ../addons. The only change is who fills the directory: this script, instead of
# the platform repo's own checkout.
#
# THE FAILURE THIS PREVENTS, precisely: Odoo records module state in the
# DATABASE (ir_module_module.state). Deleting code from addons_path does not
# change that row. The registry loads fine until the next restart, at which
# point Odoo cannot find a module it believes is installed and the database will
# not load. That is a stopped platform, not a degraded one -- which is why the
# check below is a hard failure and not a warning.
#
# NOT A SUBMODULE, deliberately. .pre-commit-config.yaml runs `forbid-submodules`
# with the note that a submodule is an unpinned third-party dependency no scanner
# in this repo inspects. Honouring that hook rather than exempting it is the
# whole reason this script exists at all.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="$REPO_ROOT/addons/ee_gap"
ORIGIN_URL="${EE_GAP_REPO_URL:-https://github.com/atheradigitalsolution/athera-odoo-ee-gap.git}"
BRANCH="${EE_GAP_REPO_BRANCH:-main}"
CHECK="${CHECK:-}"

log()  { printf '  %s\n' "$*"; }
die()  { printf 'addons-ee-gap: FAIL - %s\n' "$*" >&2; exit 1; }

# The eight modules that are installed in production. Named here rather than
# derived, so that losing one is a diff and not a silence.
INSTALLED_IN_PROD=(
    custom_ai_features custom_approval_engine custom_coretax_pajakku
    custom_documents custom_field_service custom_helpdesk
    custom_hr_payroll_id l10n_id_psak_custom
)

assert_population() {
    local missing=()
    for m in "${INSTALLED_IN_PROD[@]}"; do
        [ -f "$TARGET/$m/__manifest__.py" ] || missing+=("$m")
    done
    if [ ${#missing[@]} -gt 0 ]; then
        die "addons/ee_gap/ is present but incomplete. Missing modules that are
  INSTALLED in production: ${missing[*]}
  Odoo will refuse to load a database that names an installed module it cannot find."
    fi
    local n
    n="$(find "$TARGET" -mindepth 2 -maxdepth 2 -name __manifest__.py | wc -l)"
    log "addons/ee_gap: $n modules, all 8 production-installed ones present"
}

if [ -n "$CHECK" ]; then
    [ -d "$TARGET" ]      || die "addons/ee_gap/ is missing. Run: make addons-ee-gap"
    [ -e "$TARGET/.git" ] || die "addons/ee_gap/ exists but is not a clone of $ORIGIN_URL.
  A hand-copied tree passes every on-disk test and then does not exist on the next host."
    assert_population
    log "addons/ee_gap: at $(git -C "$TARGET" rev-parse --short HEAD) on $(git -C "$TARGET" rev-parse --abbrev-ref HEAD)"
    echo "ADDONS_EE_GAP_OK"
    exit 0
fi

if [ ! -d "$TARGET" ]; then
    log "cloning $ORIGIN_URL -> addons/ee_gap"
    git clone --branch "$BRANCH" "$ORIGIN_URL" "$TARGET"
elif [ ! -e "$TARGET/.git" ]; then
    die "addons/ee_gap/ exists but is not a git clone.
  Refusing to overwrite it: it may hold uncommitted work. Move it aside, then
  re-run. Expected origin: $ORIGIN_URL"
else
    local_url="$(git -C "$TARGET" remote get-url origin 2>/dev/null || true)"
    if [ "$local_url" != "$ORIGIN_URL" ]; then
        die "addons/ee_gap/ points at '$local_url', expected '$ORIGIN_URL'."
    fi
    if [ -n "$(git -C "$TARGET" status --porcelain)" ]; then
        die "addons/ee_gap/ has uncommitted changes. Commit or push them to
  $ORIGIN_URL before syncing; this script will not discard local edits."
    fi
    log "fast-forwarding addons/ee_gap"
    git -C "$TARGET" fetch --quiet origin "$BRANCH"
    git -C "$TARGET" merge --quiet --ff-only "origin/$BRANCH"
fi

assert_population
log "addons/ee_gap: at $(git -C "$TARGET" rev-parse --short HEAD) on $BRANCH"
echo "ADDONS_EE_GAP_OK"
