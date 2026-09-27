# -*- coding: utf-8 -*-
"""Rename the PMO industry pack onto identifiers that carry no customer name.

The seed record's xmlid and ``code`` column used to be prefixed with a
customer's product name. Those are identifiers, not prose, so a text scrub
leaves them behind in every database that installed the old seed; this
re-points the existing row instead of letting the renamed seed create a
duplicate beside it.

The old values are matched by SHAPE rather than spelled out -- writing them
here would put the name straight back into the tree this rename exists to
clear. Exactly one pack ends in ``_pmo``, so the match is unambiguous; the
UPDATEs are no-ops on a database where it never existed.

``code`` is only read by the provisioning wizard, which forwards it as
``features.industry_pack`` to the orchestrator; no other system keys off it.

Idempotent: once renamed, nothing matches the old shape any more.
"""

MODULE = "custom_hub_console"
NEW_XMLID = "pack_pmo"
NEW_CODE = "pmo"


def migrate(cr, version):
    # Bail out if the target already exists: renaming onto it would violate the
    # unique index, and the only way it exists is a rerun.
    cr.execute(
        "SELECT 1 FROM ir_model_data WHERE module = %s AND name = %s",
        (MODULE, NEW_XMLID),
    )
    if cr.fetchone():
        return

    cr.execute(
        """
        UPDATE ir_model_data
           SET name = %s
         WHERE module = %s
           AND model = 'custom.hub.industry.pack'
           AND name LIKE %s
           AND name <> %s
        """,
        (NEW_XMLID, MODULE, "pack\\_%\\_pmo", NEW_XMLID),
    )
    cr.execute(
        "UPDATE custom_hub_industry_pack SET code = %s WHERE code LIKE %s AND code <> %s",
        (NEW_CODE, "%\\_pmo", NEW_CODE),
    )
