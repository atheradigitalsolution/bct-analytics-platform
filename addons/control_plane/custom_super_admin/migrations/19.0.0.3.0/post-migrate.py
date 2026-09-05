# -*- coding: utf-8 -*-
"""Turn off the two backup crons that call routes which cannot do the work.

WHY A MIGRATION AND NOT JUST THE XML. Both records live in a `noupdate="1"`
file, which is what protects an operator's own on/off decision from being
reverted by the next module upgrade. The cost of that protection is that
flipping `active` in the XML changes NEW installs only; a database that already
carries the records keeps the old value forever. Measured after the upgrade that
introduced the change: both crons still `active = t`.

So the XML sets the state a fresh install starts in, and this script moves the
databases that already exist. Neither alone is enough, and doing only the XML is
the more dangerous half -- it looks done.

WHAT THEY WERE DOING. `_cron_scheduled_backup` POSTed every fifteen minutes to a
route that answers 501 by design; `_cron_enforce_retention` POSTed every day to a
route that did not exist at all. Both failed into a WARNING nobody reads. Backups
themselves are real and run from `scripts/tenant-backup.sh` on the host.

WHY `active = false` AND NOT A DELETE. When backup execution moves inside Odoo --
where the filestore already is -- these are the records to switch back on. A
deleted cron is one the next person writes again from scratch, without the note
in ir_cron_backup.xml explaining why it was off.
"""

import logging

_logger = logging.getLogger(__name__)

#: xml_ids, not names. A name is translatable and can be edited in the UI.
CRONS_TO_DISABLE = (
    "custom_super_admin.ir_cron_scheduled_backup",
    "custom_super_admin.ir_cron_enforce_retention",
)


def migrate(cr, version):
    if not version:
        # Fresh install: the XML already carries active="False".
        return

    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    for xmlid in CRONS_TO_DISABLE:
        cron = env.ref(xmlid, raise_if_not_found=False)
        if not cron:
            continue
        if not cron.active:
            continue
        cron.active = False
        _logger.info(
            "%s disabled: it called an orchestrator route that answers 501; "
            "backups run from scripts/tenant-backup.sh on the host", xmlid
        )
