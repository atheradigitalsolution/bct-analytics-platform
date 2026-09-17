# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Estimation",
    "summary": "Bill of quantity, waste allowance, and a quoted price derived by margin "
    "rather than markup",
    "description": """
Custom SPK Estimation
=====================

Every job here is unique, so the price is built rather than looked up. This owns
that build: a bill of quantity in four categories (material, labour, subcontract,
delivery), an overhead rate, a contingency, and a target margin.

Margin, not markup
------------------

The quoted price is ``cost / (1 - margin)``, not ``cost * (1 + margin)``. The second
is the common mistake and it is always short: mark a 100 up by 30% and you get 130,
whose margin is 23%, not 30%. Over a year of quoting that gap is the difference
between the margin a business thinks it runs on and the one it actually does.
``test_margin_is_not_markup`` pins it.

Waste is estimated, then measured
---------------------------------

Each material line carries a waste allowance, because a sheet is not consumed in
the shape a booth needs. Estimating it makes two things possible that a single
"material cost" number does not: the quote covers the offcut it will really
produce, and the finished job can be compared against it. A job that used twice its
allowance is not bad luck, it is usually a design drawn without reference to
standard sheet sizes -- which is the cheapest cost saving available here, and
invisible without this line.

Who sees what
-------------

Cost is visible to whoever estimates; the selling price and the margin are not.
That split is why estimation is a separate model from the quotation: an estimator
needs to price the work without learning what the client is charged.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_spk", "product", "uom"],
    "capability_tags": ["estimation", "boq", "job-costing", "margin"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/custom_spk_estimation_views.xml",
        "views/custom_spk_estimation_template_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
