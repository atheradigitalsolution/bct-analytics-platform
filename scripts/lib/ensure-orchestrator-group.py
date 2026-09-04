"""Give the orchestrator's Odoo login the group the provisioner demands.

`athera.provisioner._check_caller()` authorises the ODOO USER the orchestrator
authenticates as. That is a different question from the HMAC signature, which
authorises the CALLER, and both have to pass. Nothing in the bring-up ever
granted the group, so a platform that was configured correctly in every other
respect still answered "Access Denied" on the first real provisioning call --
found by making one, not by reading the code.

Idempotent. Written through the ORM rather than as an INSERT into the relation,
because Odoo materialises implied groups on write and a direct INSERT would
leave the row set inconsistent with what `has_group` expects.

`odoo shell` rolls back when stdin closes, so the commit is load-bearing; the
result is re-read afterwards and only then does this print ORCHGRP_OK.
"""
import os

LOGIN = os.environ.get("ORCH_ODOO_LOGIN") or "admin"
GROUP_XMLID = "custom_super_admin.group_super_admin"

Users = env["res.users"].with_context(active_test=False)  # noqa: F821
user = Users.search([("login", "=", LOGIN)], limit=1)
group = env.ref(GROUP_XMLID, raise_if_not_found=False)  # noqa: F821


def holds(record, grp):
    # Odoo 19 renamed the aggregate field; support both rather than pin a version.
    field = record.all_group_ids if hasattr(record, "all_group_ids") else record.group_ids
    return grp in field


if not user:
    print("ORCHGRP_ABSENT login=%s" % LOGIN)
elif not group:
    print("ORCHGRP_NOGROUP %s" % GROUP_XMLID)
elif holds(user, group):
    print("ORCHGRP_ALREADY login=%s" % LOGIN)
    print("ORCHGRP_OK")
else:
    user.write({"group_ids": [(4, group.id)]})
    env.cr.commit()  # noqa: F821
    if holds(Users.browse(user.id), group):
        print("ORCHGRP_GRANTED login=%s" % LOGIN)
        print("ORCHGRP_OK")
    else:
        print("ORCHGRP_FAILED login=%s" % LOGIN)
