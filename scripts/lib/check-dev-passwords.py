"""Assert EVERY database this Odoo serves refuses Odoo's default and accepts its own credential.

RUNTIME: host script. Invoked by `scripts/set-dev-passwords.sh --check` (and so
by `make check-dev-passwords` and `make verify`), which supplies:

    DEVPW_CHECK_URL       http://127.0.0.1:38069   (the published Odoo port)
    DEVPW_CHECK_DOMAIN    the domain the vhost label is appended to
    DEVPW_CHECK_ROWS      one record per served database, newline-separated,
                          TAB-separated fields:

                              <database>  <role>  <credential state>  <demo logins>  <admin login>

                          role is `tenant` or `control-plane`; credential state
                          is `ok`, `absent` or `placeholder`; demo logins is a
                          comma-separated list, possibly empty.
    DEVPW_PW_TENANT_B64   base64 of $BCT_DEV_USER_PASSWORD
    DEVPW_PW_ADMIN_B64    base64 of $ORCHESTRATOR_ODOO_PASSWORD

Passwords arrive base64-encoded through the ENVIRONMENT, never argv, and are
never printed: every line below names the environment VARIABLE, not its value.

It authenticates over XML-RPC from the host, against the published port, because
that is the path a human and the login-gateway actually use. Asserting against
the hash in res_users would prove the row, not the login.

WHY THE LIST, AND NOT ONE DATABASE
----------------------------------
This file used to take a single database name. Odoo here serves several, and the
one it did not name was the CONTROL PLANE - the registry, billing and super-admin
database. It therefore printed "dev credential verified, and Odoo's default is
rejected" while the control plane accepted `admin`/`admin`. The check's NAME was
wider than its SCOPE, which is the same defect class it was written to close: a
gate that is green because of what it does not look at.

TWO ASSERTIONS PER DATABASE, BOTH REQUIRED
------------------------------------------
  1. the NEGATIVE - `admin`/`admin` must be REFUSED. Without it the gate is green
     on a stack that accepts both passwords, which is the defective state.
  2. the POSITIVE - the credential that is supposed to apply there must be
     ACCEPTED. Without it a database nobody can log into reads as secure, and the
     control-plane hole above would not have been caught either way.

NON-VACUITY
-----------
Checking ZERO databases is a FAILURE, not a pass. "Green because it tested
nothing" is exactly the pattern PLAN.md catalogues, and a gate that cannot fail
only moves the problem. The number of databases checked is printed so a silent
narrowing of scope is visible in the output rather than inferred from it.

ATTEMPT BUDGET
--------------
Odoo throttles repeated failed logins per (login, database). This makes exactly
ONE deliberately-failing attempt per database - the negative - so a full run
stays far below the cooldown threshold even on a stack with many tenants.
"""
import base64
import http.client
import os
import sys
import urllib.parse
import xmlrpc.client

# role -> (the environment variable an operator would look the value up in,
#          the variable this process receives its base64 through)
ROLES = {
    "tenant": ("BCT_DEV_USER_PASSWORD", "DEVPW_PW_TENANT_B64"),
    "control-plane": ("ORCHESTRATOR_ODOO_PASSWORD", "DEVPW_PW_ADMIN_B64"),
}

DEFAULT_LOGIN = "admin"
DEFAULT_PASSWORD = "admin"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Claim one hostname, connect to another address.

    http.client derives the Host header from the CONNECTION's host, not from
    the URL — so overriding either one alone cannot produce "Host says
    <tenant>.athera.localhost, socket goes to 127.0.0.1". This splits them: the
    superclass keeps the virtual host (and therefore emits the right Host),
    and connect() is pointed at the real address.
    """

    def __init__(self, vhost, port, connect_addr, **kwargs):
        super().__init__(vhost, port, **kwargs)
        self._connect_addr = connect_addr

    def connect(self):
        self.sock = self._create_connection(
            self._connect_addr, self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedTransport(xmlrpc.client.Transport):
    """XML-RPC over a connection whose Host names the database.

    Needed since ODOO_DBFILTER became ^%d$ on 2026-09-01. Odoo picks the
    database from the FIRST LABEL of the Host header, and that applies to
    XML-RPC exactly as it applies to a browser. Measured, in order:

      Host: 127.0.0.1:38069            -> 404, authenticate never reaches a db
      Host: ...,<db>.athera.localhost  -> 500, ValueError parsing the port
                                          (setting the header by hand duplicates
                                          the one http.client already sent)
      Host: <db>.athera.localhost      -> 200, uid 2

    Only the third is a working check. The first would report a healthy stack
    as a wrong password, which is worse than not checking at all.

    Since the check now covers several databases, each one needs its OWN
    transport: the vhost label IS the database selector.
    """

    def __init__(self, connect_addr, **kwargs):
        super().__init__(**kwargs)
        self._connect_addr = connect_addr

    def make_connection(self, host):
        if self._connection and host == self._connection[0]:
            return self._connection[1]
        chost, _extra, _x509 = self.get_host_info(host)
        vhost, _, vport = chost.partition(":")
        conn = _PinnedHTTPConnection(
            vhost, int(vport) if vport else None, self._connect_addr)
        self._connection = host, conn
        return conn


def _decode(var):
    """Plaintext of a base64 environment variable. Absent and empty are the same."""
    raw = os.environ.get(var, "")
    if not raw:
        return ""
    return base64.b64decode(raw).decode("utf-8")


def _proxy(database, connect_host, port, domain):
    return xmlrpc.client.ServerProxy(
        "http://%s.%s:%d/xmlrpc/2/common" % (database, domain, port),
        allow_none=True,
        transport=_PinnedTransport((connect_host, port)))


def _parse_rows(raw):
    """Records of (database, role, credential state, demo logins, admin login)."""
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        while len(fields) < 5:
            fields.append("")
        database, role, state, demo, admin_login = fields[:5]
        rows.append((
            database.strip(),
            role.strip() or "tenant",
            state.strip() or "absent",
            [x for x in demo.split(",") if x],
            admin_login.strip() or DEFAULT_LOGIN,
        ))
    return rows


def main():
    url = os.environ["DEVPW_CHECK_URL"]
    domain = os.environ.get("DEVPW_CHECK_DOMAIN") or "athera.localhost"
    rows = _parse_rows(os.environ.get("DEVPW_CHECK_ROWS", ""))

    parsed = urllib.parse.urlsplit(url)
    connect_host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80

    failures = []
    checked = []

    def report(ok, text):
        print("  %s  %s" % ("PASS" if ok else "FAIL", text))

    for database, role, state, demo, admin_login in rows:
        cred_var, b64_var = ROLES.get(role, ROLES["tenant"])
        print("")
        print("  --- %s '%s'  (credential: $%s)" % (role, database, cred_var))

        # A credential that is not declared cannot be asserted, and "cannot
        # assert" must not read as "asserted". This is a FAILURE, deliberately:
        # the gate has no business going green over a database whose expected
        # login nobody can look up.
        if state != "ok":
            report(False, "$%s is %s - nothing to verify against '%s'"
                          % (cred_var, state, database))
            failures.append(
                "$%s is %s, so '%s' could not be verified at all "
                "(fix: make dev-bootstrap)" % (cred_var, state, database))
            continue

        password = _decode(b64_var)
        common = _proxy(database, connect_host, port, domain)

        def auth(login, secret):
            """uid on success, False on refusal, 'ERROR: ...' on transport failure.

            A transport failure is deliberately NOT the same value as a refusal:
            a refusal is the answer we sometimes want, an unreachable server
            never is.
            """
            try:
                return common.authenticate(database, login, secret, {})
            except Exception as exc:  # noqa: BLE001 - reported below, never raised
                return "ERROR: %s" % exc

        # 1. THE NEGATIVE. Odoo's default must be refused. Delete this block and
        #    the whole check is green on the defective stack too.
        if password == DEFAULT_PASSWORD:
            print("  SKIP  negative: $%s is literally '%s'"
                  % (cred_var, DEFAULT_PASSWORD))
        else:
            # Against the RESOLVED administrator, not the literal `admin`. On a
            # database whose administrator carries a different login, testing
            # `admin` proves only that no such account exists -- a pass that
            # examined nothing, which is the failure this gate is here to find.
            got = auth(admin_login, DEFAULT_PASSWORD)
            ok = got is False
            report(ok, "authenticate('%s', '%s', 'admin')  -> %r   (want False)"
                       % (database, admin_login, got))
            if not ok:
                failures.append(
                    "'%s' still accepts Odoo's DEFAULT password, as uid %r"
                    % (database, got))

        # 2. THE POSITIVE. The credential that is supposed to apply here must
        #    work. On its own this catches nothing; without it, a database no
        #    credential opens reads as correctly configured.
        got = auth(admin_login, password)
        ok = isinstance(got, int) and got > 0
        report(ok, "authenticate('%s', '%s', $%s)  -> %r   (want a uid)"
                   % (database, admin_login, cred_var, got))
        if not ok:
            failures.append("$%s does not authenticate as '%s' in '%s'"
                            % (cred_var, admin_login, database))

        # 3. Every demo user the seed created, if the seed has run at all.
        #    Absent is not a failure: `make up-dev` legitimately runs before
        #    generate() ever has.
        if not demo:
            print("  SKIP  no demo.%@contoh.invalid users in this database "
                  "(custom_demo_seed generate() has not run)")
        for login in demo:
            got = auth(login, password)
            ok = isinstance(got, int) and got > 0
            report(ok, "authenticate('%s', %r, $%s)  -> %r   (want a uid)"
                       % (database, login, cred_var, got))
            if not ok:
                failures.append("$%s does not authenticate as %r in '%s'"
                                % (cred_var, login, database))

        checked.append(database)

    print("")

    # THE NON-VACUITY GUARD. A gate that examined nothing has not passed; it has
    # abstained, and abstention printed as green is the whole defect class.
    if not checked:
        print("  FAIL  no served database was verified "
              "(%d record(s) supplied)" % len(rows))
        print("")
        for failure in failures:
            print("  FAILED: %s" % failure)
        print("  FAILED: the gate checked ZERO databases. A check that examines "
              "nothing cannot pass.")
        print("  Fix:  confirm ODOO_DB_NAMES is set in the odoo container, "
              "then `make up-dev`")
        return 1

    print("  checked %d served database(s): %s" % (len(checked), ", ".join(checked)))

    if failures:
        for failure in failures:
            print("  FAILED: %s" % failure)
        print("  Fix:  make set-dev-passwords")
        return 1

    # Phrased off the COUNT, not off the word "every". Saying "every served
    # database" after a --db run that examined one would repeat, in the success
    # line, the exact fault this file was rewritten to remove.
    print("  all %d checked database(s) accept their own credential and refuse "
          "Odoo's default." % len(checked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
