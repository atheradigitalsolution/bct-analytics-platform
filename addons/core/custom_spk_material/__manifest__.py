# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Material",
    "summary": "Material requests with supervisor approval, over-estimate escalation, "
    "and an offcut policy that stops one job paying for the next one's material",
    "description": """
Custom SPK Material
===================

Material classes, because one rule does not fit
-----------------------------------------------

The tempting simplification is "charge the whole sheet to whoever opened it". It
makes the year's profit correct and every individual job's margin wrong: the first
job pays for material three later jobs will use. So material is classified and
treated accordingly:

* **A — stock item** (hollow, plywood, ACP, acrylic): charged as used; the offcut
  comes back.
* **B — consumable** (paint, thinner, glue, abrasives): charged at a standard rate,
  because nobody is going to weigh the thinner. The gap between standard and actual
  is an overhead variance, not a job's problem.
* **C — fixed unit** (lamps, hinges, castors): charged per unit; leftovers return
  whole.
* **D — made to order** (printed banner at one size, laser-cut acrylic): charged
  entirely to the job, because no other job can use it.

The offcut policy
-----------------

A returned remnant is either worth keeping or it is waste, and a threshold decides
which. Above it, the piece re-enters stock as its own product at a discount — it is
genuinely worth less, because its size constrains what it can become — and the
originating job is credited. Below it, the job carries it as waste.

Two details make or break this in practice. The discount has to be real, or the
offcut rack becomes a way to move cost off jobs rather than a stock of usable
material. And the warehouse has to issue offcut before opening new stock, or the
rack fills up and turns into rubbish that was capitalised.

Over-estimate escalation
------------------------

A request that would push a job's cumulative take past what was estimated does not
fail; it escalates to the project manager and records why. The supervisor approves
day-to-day material. Nobody quietly approves the third extra sheet.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_spk", "custom_spk_estimation", "stock", "analytic"],
    "capability_tags": ["material-request", "offcut", "waste", "job-costing", "approval-workflow"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/product_views.xml",
        "views/custom_spk_material_request_views.xml",
        "views/custom_spk_material_return_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
