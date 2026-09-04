#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Apply the correct dev login credential to EVERY database this Odoo serves.
#
#     make set-dev-passwords          apply
#     make check-dev-passwords        assert the live state, change nothing
#     scripts/set-dev-passwords.sh [--db NAME] [--check]
#
# WHY THIS FILE EXISTS
# --------------------
# PLAN.md defect-pattern instance 10. The operator chose "set a local dev
# password". That decision was carried out by hand, once, in a live shell, and
# never became repo: BCT_DEV_USER_PASSWORD appeared only in the untracked .env,
# no target consumed it, and after the documented `make up-dev`
# authenticate(<tenant>,'admin','admin') returned uid 2 - Odoo's DEFAULT - while
# .env advertised a 20-character random string that nothing applied.
#
# That is worse than skipping the step, because the file looks like the step was
# done. So the rule this script enforces is not "set a good password"; it is:
#
#     the running database always agrees with .env, and Odoo's default `admin`
#     is never left standing.
#
# WHY IT IS A LIST AND NOT ONE NAME
# ---------------------------------
# The same defect, one layer up, and it survived for months. This script used to
# resolve exactly ONE database - `DB="${DB:-$ODOO_DB_NAME}"` - while Odoo serves
# several. The database it never named was the CONTROL PLANE: the tenant
# registry, billing, and the super-admin console. That database accepted
# `admin`/`admin` the entire time, and `make verify` printed
# "PASS dev password applied, default rejected" over the top of it, because the
# check's NAME was wider than its SCOPE.
#
# So the list of databases is READ, never assumed, and it comes from the same
# place Odoo itself is configured from - see served_databases() below.
#
# WHICH CREDENTIAL GOES WHERE
# ---------------------------
#   * every TENANT database  -> $BCT_DEV_USER_PASSWORD
#   * the CONTROL PLANE      -> $ORCHESTRATOR_ODOO_PASSWORD
#
# The control plane's is not a style choice. tenant-orchestrator authenticates
# to Odoo with $ORCHESTRATOR_ODOO_PASSWORD (tenant-orchestrator/app/config.py),
# against $ATHERA_ADMIN_DB as login `admin`. Any other value there would be a
# credential the platform's own service cannot use.
#
# WHAT IT TOUCHES
# ---------------
#   * `admin`
#   * every `demo.%@contoh.invalid` account - the users custom_demo_seed creates
#     in generate(). That module deliberately ships them WITHOUT a password
#     ("the accounts cannot be logged into until an administrator sets one"), so
#     setting one here is the administrator step the addon is waiting for, done
#     in a file instead of in someone's scrollback. addons/** is not ours; this
#     operates on the database after the seed has run.
#
# The `demo.` prefix plus the RFC 2606 reserved `@contoh.invalid` domain cannot
# collide with a real account.
#
# ORDERING
# --------
# The demo users exist only after `demo.seed.generator.generate()` has been
# called, which is NOT part of `make up-dev` (custom_demo_seed generates nothing
# at install time, by design). So this script must be, and is:
#
#   * tolerant    - a missing account, a database that is listed but not yet
#                   created, or a credential that is not declared is REPORTED
#                   and skipped, never fatal. A fresh clone's first `make up-dev`
#                   finds `admin` alone.
#   * re-runnable - run it again after seeding and it picks the demo users up,
#                   leaving `admin` untouched.
#
# HASHING
# -------
# It never writes a hash it constructed. It assigns to the ORM field, so Odoo's
# own res.users password setter hashes with the live crypt context; and it tests
# "already correct" with that same context's verify(). A hand-built hash is the
# thing that passes a SQL check and then fails a login.
#
# SECRECY
# -------
# No password value is ever printed, and none ever reaches argv. Values move as
# base64 through a process ENVIRONMENT (python3) or through STDIN (odoo shell).
# Every message below names the environment VARIABLE, never its contents.
# ---------------------------------------------------------------------------
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

DB=""
MODE="apply"

usage() {
    cat >&2 <<'USAGE'
usage: scripts/set-dev-passwords.sh [options]

  --db NAME    Operate on this database ALONE. Default: every database Odoo
               serves, read from $ODOO_DB_NAMES in the odoo container.
  --check      Do not write. Assert, over XML-RPC as a client would, that for
               EVERY served database the credential that should apply there
               logs in AND that Odoo's default `admin` password is REJECTED.
               Exits non-zero if either is untrue anywhere - or if it ends up
               with no database to check at all.
  -h, --help   This message.

Credential mapping (see the header): tenant databases use
$BCT_DEV_USER_PASSWORD; $ATHERA_ADMIN_DB, the control plane, uses
$ORCHESTRATOR_ODOO_PASSWORD, because that is what tenant-orchestrator
authenticates with.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --db) DB="${2:?--db needs a value}"; shift 2 ;;
        --db=*) DB="${1#*=}"; shift ;;
        --check) MODE="check"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown argument: $1 (try --help)" ;;
    esac
done

require_docker
load_env

CONTROL_PLANE_DB="${ATHERA_ADMIN_DB:-athera_admin}"

# ---------------------------------------------------------------------------
# The served database list.
#
# Read from the odoo container's own environment, because that is the process
# whose behaviour is in question: a list kept anywhere else can drift from what
# Odoo actually answers for, and a stale list is how a database escapes this
# script in the first place. .env is the fallback for the case where the
# container cannot be read; a single $ODOO_DB_NAME is the last resort so an
# older .env still gets the old behaviour rather than nothing.
#
# Nothing here is hard-coded. Adding a tenant to $ODOO_DB_NAMES is all it takes
# for both the apply path and the gate to cover it.
# ---------------------------------------------------------------------------
served_databases() {
    local raw=""
    raw="$(dc exec -T odoo printenv ODOO_DB_NAMES 2>/dev/null | tr -d '\r' || true)"
    if [ -z "$raw" ] && [ -n "${ODOO_DB_NAMES:-}" ]; then
        warn "could not read ODOO_DB_NAMES from the odoo container; using the .env value."
        raw="$ODOO_DB_NAMES"
    fi
    if [ -z "$raw" ] && [ -n "${ODOO_DB_NAME:-}" ]; then
        warn "ODOO_DB_NAMES is not declared anywhere; falling back to the single \$ODOO_DB_NAME."
        raw="$ODOO_DB_NAME"
    fi
    # Whitespace is stripped per FIELD, not from the stream: `tr -d '[:space:]'`
    # over the whole pipe would eat the newlines that separate the names and
    # hand back one concatenated word.
    printf '%s\n' "$raw" | tr ',' '\n' \
        | awk '{ gsub(/[[:space:]]/, ""); if ($0 != "" && !seen[$0]++) print }'
}

role_of() {
    if [ "$1" = "$CONTROL_PLANE_DB" ]; then printf 'control-plane'; else printf 'tenant'; fi
}

credential_var_of() {
    if [ "$1" = "control-plane" ]; then
        printf 'ORCHESTRATOR_ODOO_PASSWORD'
    else
        printf 'BCT_DEV_USER_PASSWORD'
    fi
}

# ok | absent | placeholder — never the value itself.
state_of() {
    case "$1" in
        "")       printf 'absent' ;;
        changeme) printf 'placeholder' ;;
        *)        printf 'ok' ;;
    esac
}

# The password reaches every other process base64-encoded and through an
# ENVIRONMENT variable: never in argv (visible in `ps` on the host and in the
# container) and never interpolated into Python source, where a quote or a
# backslash in the value would be a syntax error rather than a wrong password.
# Host python3 is already a hard dependency of dev-bootstrap; `base64 -w0` is
# not portable, this is.
pw_b64_of() {
    DEVPW_PLAINTEXT="$1" python3 -c \
        'import base64,os;print(base64.b64encode(os.environ["DEVPW_PLAINTEXT"].encode("utf-8")).decode("ascii"))'
}

TENANT_PW="${BCT_DEV_USER_PASSWORD:-}"
ADMIN_PW="${ORCHESTRATOR_ODOO_PASSWORD:-}"
TENANT_STATE="$(state_of "$TENANT_PW")"
ADMIN_STATE="$(state_of "$ADMIN_PW")"
TENANT_PW_B64="$(pw_b64_of "$TENANT_PW")"
ADMIN_PW_B64="$(pw_b64_of "$ADMIN_PW")"

# ---------------------------------------------------------------------------
# The one state nothing here can repair: a key is absent from .env entirely (an
# .env generated before the variable existed). There is no value to apply and
# inventing one would produce a credential nobody can look up. Report it - never
# silently - and name the command that fixes it. `make dev-bootstrap` merges new
# keys from .env.example into an existing .env without rotating anything else.
#
# APPLY skips loudly and keeps going: a bring-up must not die over a dev
# convenience, and the other databases still deserve their credential.
# CHECK does NOT skip: an unverifiable database is reported as a FAILURE by
# check-dev-passwords.py, because "could not assert" must never read as green.
# ---------------------------------------------------------------------------
TENANT_APPLICABLE=1
ADMIN_APPLICABLE=1

if [ "$TENANT_STATE" = "absent" ]; then
    TENANT_APPLICABLE=0
    warn "BCT_DEV_USER_PASSWORD is not set in .env - no tenant credential to apply."
    warn "  'admin' therefore keeps whatever password it already has, and on a"
    warn "  fresh database that is Odoo's default, 'admin'."
    warn "  Fix:  make dev-bootstrap    (merges the key in, generates a value)"
elif [ "$TENANT_STATE" = "placeholder" ]; then
    # Applied anyway, and only here. A placeholder you can look up beats Odoo's
    # default, which is the state this script exists to end.
    warn "BCT_DEV_USER_PASSWORD is still the literal placeholder 'changeme'."
    warn "  Applying it to the tenant databases anyway: a placeholder you can"
    warn "  look up beats Odoo's default 'admin'."
    warn "  Fix:  make dev-bootstrap    (generates a real random value)"
fi

# The control plane gets no placeholder concession. Unlike the tenant dev
# password this value is a SERVICE credential - tenant-orchestrator signs in
# with it - so writing 'changeme' onto the registry/billing database would not
# be a convenience, it would be a published password on the one database that
# holds every tenant. Report and skip; the gate then goes red, which is the
# honest outcome.
if [ "$ADMIN_STATE" != "ok" ]; then
    ADMIN_APPLICABLE=0
    warn "ORCHESTRATOR_ODOO_PASSWORD is $ADMIN_STATE - the control plane database"
    warn "  '$CONTROL_PLANE_DB' will be SKIPPED, and it keeps whatever password it"
    warn "  already has. On a fresh database that is Odoo's default, 'admin', on the"
    warn "  database that holds the tenant registry, billing and the super-admin"
    warn "  console. tenant-orchestrator authenticates with this value, so it must"
    warn "  be a real one."
    warn "  Fix:  make dev-bootstrap    (generates a real random value)"
fi

require_healthy postgres odoo

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
TARGETS=()
if [ -n "$DB" ]; then
    TARGETS=("$DB")
    # Captured first, then matched against a here-string. `served_databases |
    # grep -q` would look right and be wrong: grep -q exits on the first match,
    # the upstream awk takes SIGPIPE, and `set -o pipefail` then reports the
    # whole pipeline as failed for a name that WAS found.
    _served="$(served_databases)"
    if ! grep -qx -- "$DB" <<<"$_served"; then
        warn "'$DB' is not in \$ODOO_DB_NAMES. Proceeding because --db was explicit,"
        warn "  but a database Odoo does not serve is not covered by 'make verify'."
    fi
else
    while IFS= read -r _name; do
        if [ -n "$_name" ]; then TARGETS+=("$_name"); fi
    done < <(served_databases)
fi

if [ "${#TARGETS[@]}" -eq 0 ]; then
    warn "no database to operate on: neither ODOO_DB_NAMES nor ODOO_DB_NAME is set."
    [ "$MODE" = "check" ] && die "cannot verify a stack whose served databases are undeclared."
    exit 0
fi

# A database that is listed but has no Odoo schema is reported and dropped, not
# fatal: ODOO_DB_NAMES legitimately names a tenant before it has been created.
# Dropping it silently is what this whole script is against, so it is named.
LIVE=()
for _name in "${TARGETS[@]}"; do
    if ! db_exists "$_name"; then
        warn "database '$_name' does not exist in the cluster - skipped."
        continue
    fi
    if ! db_initialised "$_name"; then
        warn "database '$_name' has no Odoo schema yet - skipped. Run 'make up-dev'."
        continue
    fi
    LIVE+=("$_name")
done

# ===========================================================================
# --check : assert, do not write.
#
# Runs over XML-RPC from the HOST, against the published port, because that is
# the path a human and the login-gateway actually use. Asserting against the
# hash in the table would prove the row, not the login.
#
# It carries a NEGATIVE. PLAN.md standing rule: a check that has never been
# observed to fail is not yet known to work - and "the good password works" is
# green on a stack that accepts BOTH passwords, which is exactly the broken
# state. So `admin`/`admin` MUST be refused, in every served database, for this
# to pass. An empty database list is a FAILURE there, not a pass.
# ===========================================================================
if [ "$MODE" = "check" ]; then
    ROWS=""
    for _name in "${LIVE[@]}"; do
        _role="$(role_of "$_name")"
        if [ "$_role" = "control-plane" ]; then
            _state="$ADMIN_STATE"
        else
            # 'changeme' IS applied to tenants above, so it is verifiable here.
            _state="$TENANT_STATE"
            if [ "$_state" = "placeholder" ]; then _state="ok"; fi
        fi
        _demo="$(psql_super "$_name" -tAc \
            "SELECT login FROM res_users WHERE login LIKE 'demo.%@contoh.invalid' ORDER BY login" \
            2>/dev/null | tr -d '\r' | tr '\n' ',' || true)"
        ROWS="${ROWS}${_name}"$'\t'"${_role}"$'\t'"${_state}"$'\t'"${_demo}"$'\n'
    done

    DEVPW_CHECK_URL="http://${BIND_ADDRESS:-127.0.0.1}:${ODOO_HOST_HTTP_PORT:-38069}" \
    DEVPW_CHECK_DOMAIN="${ATHERA_DOMAIN:-athera.localhost}" \
    DEVPW_CHECK_ROWS="$ROWS" \
    DEVPW_PW_TENANT_B64="$TENANT_PW_B64" \
    DEVPW_PW_ADMIN_B64="$ADMIN_PW_B64" \
    python3 "$REPO_ROOT/scripts/lib/check-dev-passwords.py"
    exit $?
fi

# ===========================================================================
# apply
# ===========================================================================
APPLIED=0
SKIPPED=0

for _name in "${LIVE[@]}"; do
    _role="$(role_of "$_name")"
    _var="$(credential_var_of "$_role")"
    if [ "$_role" = "control-plane" ]; then
        _pw_b64="$ADMIN_PW_B64"; _applicable="$ADMIN_APPLICABLE"
    else
        _pw_b64="$TENANT_PW_B64"; _applicable="$TENANT_APPLICABLE"
    fi

    if [ "$_applicable" != "1" ]; then
        warn "'$_name' ($_role) skipped: \$$_var is not usable - see above."
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    log "applying \$$_var to admin and demo.%@contoh.invalid in '$_name' ($_role)"

    # `odoo shell` against the LIVE container, not `docker compose run`: other
    # agents are using this stack. There is no DDL here - res_users row updates
    # only - so the registry deadlock that forces init-db.sh to stop the server
    # does not apply.
    #
    # `odoo shell` ROLLS BACK when stdin closes. The commit in the program below
    # is not optional and its absence would be SILENT: every line would print
    # "set" and nothing would be written. That is the same shape as the defect
    # being fixed, so the program re-reads the committed rows and only then
    # prints DEVPW_OK.
    set +e
    out="$(
        {
            printf '_PW_B64 = "%s"\n' "$_pw_b64"
            cat "$REPO_ROOT/scripts/lib/set-dev-passwords.py"
        } | dc exec -T odoo odoo shell -d "$_name" --no-http
    )"
    rc=$?
    set -e

    printf '%s\n' "$out" | grep -E '^DEVPW' | sed "s/^/    $_name: /" >&2 || true

    # Assert the OUTCOME, not the exit code: `odoo shell` exits 0 for a program
    # that raised nothing but also did nothing.
    if ! printf '%s\n' "$out" | grep -q '^DEVPW_OK$'; then
        printf '%s\n' "$out" >&2
        die "odoo shell exited $rc for '$_name' without DEVPW_OK - no password was verified as applied."
    fi
    APPLIED=$((APPLIED + 1))
done

if [ "$APPLIED" -eq 0 ]; then
    warn "no database was updated. Odoo's default 'admin' may still be standing."
else
    log "done. Odoo's default 'admin' password is no longer accepted in $APPLIED database(s)."
fi
if [ "$SKIPPED" -gt 0 ]; then
    warn "$SKIPPED served database(s) were skipped for want of a credential - see above."
fi
info "verify:  make check-dev-passwords"
