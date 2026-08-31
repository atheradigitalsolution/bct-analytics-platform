"""Assert the live Odoo accepts $BCT_DEV_USER_PASSWORD and REJECTS Odoo's default.

RUNTIME: host script. Invoked by `scripts/set-dev-passwords.sh --check` (and so
by `make check-dev-passwords` and `make verify`), which supplies:

    BCT_CHECK_URL    http://127.0.0.1:38069
    BCT_CHECK_DB     bct
    BCT_CHECK_DEMO   comma-separated demo.*@contoh.invalid logins present in the DB
    BCT_DEV_PW_B64   base64 of $BCT_DEV_USER_PASSWORD

It authenticates over XML-RPC from the host, against the published port, because
that is the path a human and the login-gateway actually use. Asserting against
the hash in res_users would prove the row, not the login.

THE NEGATIVE IS THE POINT. PLAN.md standing rule: a check that has never been
observed to fail is not yet known to work. "The documented password logs in" is
green on a stack that accepts BOTH passwords - which is precisely the defective
state instance 10 describes. So `admin`/`admin` MUST be refused for this to pass.
"""
import base64
import os
import sys
import xmlrpc.client

url = os.environ["BCT_CHECK_URL"]
db = os.environ["BCT_CHECK_DB"]
password = base64.b64decode(os.environ["BCT_DEV_PW_B64"]).decode("utf-8")
demo = [x for x in os.environ.get("BCT_CHECK_DEMO", "").split(",") if x]

common = xmlrpc.client.ServerProxy(url + "/xmlrpc/2/common", allow_none=True)


def auth(login, secret):
    """uid on success, False on refusal, the string 'ERROR: ...' on transport failure.

    A transport failure is deliberately NOT the same value as a refusal: a
    refusal is the answer we sometimes want, an unreachable server never is.
    """
    try:
        return common.authenticate(db, login, secret, {})
    except Exception as exc:  # noqa: BLE001 - reported below, never raised
        return "ERROR: %s" % exc


failures = []


def report(ok, text):
    print("  %s  %s" % ("PASS" if ok else "FAIL", text))


# 1. THE NEGATIVE. Odoo's default must be refused. Delete this block and the
#    whole check is green on the defective stack too.
if password == "admin":
    print("  SKIP  negative: BCT_DEV_USER_PASSWORD is literally 'admin'")
else:
    got = auth("admin", "admin")
    ok = got is False
    report(ok, "authenticate(%r, 'admin', 'admin')                -> %r   (want False)" % (db, got))
    if not ok:
        failures.append("Odoo's DEFAULT password still authenticates as uid %r" % (got,))

# 2. The documented credential must work.
got = auth("admin", password)
ok = isinstance(got, int) and got > 0
report(ok, "authenticate(%r, 'admin', $BCT_DEV_USER_PASSWORD) -> %r   (want a uid)" % (db, got))
if not ok:
    failures.append("$BCT_DEV_USER_PASSWORD does not authenticate as 'admin'")

# 3. Every demo user the seed created, if the seed has run at all. Absent is not
#    a failure: `make up-dev` legitimately runs before generate() ever has.
if not demo:
    print("  SKIP  no demo.%@contoh.invalid users in this database "
          "(custom_demo_seed generate() has not run; try `make seed-demo`)")
for login in demo:
    got = auth(login, password)
    ok = isinstance(got, int) and got > 0
    report(ok, "authenticate(%r, %r, $BCT_DEV_USER_PASSWORD) -> %r   (want a uid)"
               % (db, login, got))
    if not ok:
        failures.append("$BCT_DEV_USER_PASSWORD does not authenticate as %r" % login)

if failures:
    print("")
    for failure in failures:
        print("  FAILED: %s" % failure)
    print("  Fix:  make set-dev-passwords")
    sys.exit(1)

print("  dev credential verified, and Odoo's default is rejected.")
