# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Change Order",
    "summary": "Scope changes after the job is approved, priced and signed before the "
    "workshop touches them",
    "description": """
Custom SPK Change Order
=======================

The largest avoidable loss in this business is not waste or idle time. It is work done
because the client asked verbally, and then argued about when the invoice arrived.

So a change after the SPK is approved is its own record, with its own number the client
quotes back, and three things a task does not have:

* **Cost and price impact**, priced before anybody agrees to it.
* **Schedule impact in days**, because the event date does not move and a change that
  costs three days may be impossible rather than expensive.
* **Client approval**, captured, dated, and required before the workshop is allowed to
  work differently.

Why not reuse `custom_project_cr`
---------------------------------

`custom_project_cr` in ``ee_gap`` models exactly this shape -- a change request with
tiered approval, impact analysis and an official number -- and it was the first
candidate. It depends on ``custom_project_portfolio``, a client-coupled PMO module
whose stage set and sprint semantics have nothing to do with a booth. Reusing it meant
either dragging that in or decoupling it first, and decoupling somebody else's tenant
module is a larger and riskier change than the 200 lines here.

The design free revision limit
------------------------------

Two revisions are included. The third caused by a change of the client's mind is a
change order rather than goodwill. Without that line, revisions are unbounded, and they
consume margin and the schedule at the same time.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_object_storage", "custom_spk", "custom_spk_estimation"],
    "capability_tags": ["change-order", "scope-control", "approval-workflow"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/custom_spk_change_order_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
