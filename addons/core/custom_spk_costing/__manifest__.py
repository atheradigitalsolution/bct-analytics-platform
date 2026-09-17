# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Costing",
    "summary": "Estimate versus actual per job, including the waste variance that tells "
    "you whether the problem is the workshop or the drawing",
    "description": """
Custom SPK Costing
==================

The report the owner actually reads: what a job was estimated to cost, what it did
cost, and where the two parted company.

Why this is its own model
-------------------------

``custom.spk`` carries no monetary field by design, and a test asserts the absence so
that nobody adds one later. That rule is what makes the SPK safe to show an Account
Executive — and it also means the cost summary cannot live there. So it lives here,
one record per job, behind cost visibility.

The constraint turned out to be the right architecture: the AE-facing record and the
costing record have different readers, different lifetimes, and different refresh
behaviour, and joining them would have made the fence depend on remembering to hide
fields.

Actual cost is read, not accumulated
------------------------------------

Every figure comes from ``account.analytic.line`` on the job's analytic account,
which is where material issues, labour logs, allocations, subcontract bills and
delivery costs all already land. Nothing re-posts, nothing double-counts, and a
figure that looks wrong can be drilled to the transaction that produced it.

The waste variance
------------------

Material variance on its own says a job cost more than planned. The waste line says
why. A job that used its material but twice its waste allowance was not run badly in
the workshop — it was drawn without reference to standard sheet sizes, and the fix is
upstream of everyone who gets blamed for it.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_spk", "custom_spk_estimation", "analytic"],
    # custom_spk_workforce and custom_spk_material stamp x_spk_cost_category when
    # present, but neither is required: a job costed from stock alone still reports.
    "capability_tags": ["job-costing", "variance", "margin", "reporting"],
    "data": [
        "security/ir.model.access.csv",
        "views/custom_spk_cost_summary_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
