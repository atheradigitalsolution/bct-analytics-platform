# -*- coding: utf-8 -*-
"""Install-time wiring that XML cannot express."""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Give pharmacy roles the Odoo stock rights their work requires.

    Done in code rather than as a data record because the groups are defined
    by custom_hms_base inside a `noupdate="1"` block. That flag lives on the
    record's ir.model.data row, not on the writing module, so an XML record
    here is silently skipped on every install and update — the permission
    looks granted in the source and is not granted in the database.

    Pharmacy staff genuinely operate inventory: they receive purchase orders,
    transfer between depots and dispense against lots. Granting the real right
    is more honest than wrapping every stock write in sudo() and leaving the
    permission model describing something untrue.
    """
    pairs = [
        ("custom_hms_base.group_hms_pharmacy_tech", ["stock.group_stock_user"]),
        ("custom_hms_base.group_hms_pharmacist",
         ["stock.group_stock_user", "stock.group_production_lot"]),
    ]
    for group_xmlid, implied_xmlids in pairs:
        group = env.ref(group_xmlid, raise_if_not_found=False)
        if not group:
            continue
        to_add = []
        for xmlid in implied_xmlids:
            implied = env.ref(xmlid, raise_if_not_found=False)
            if implied and implied not in group.implied_ids:
                to_add.append((4, implied.id))
        if to_add:
            group.write({"implied_ids": to_add})
            _logger.info("SIMRS: hak stok ditambahkan ke %s", group_xmlid)
