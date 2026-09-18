# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Billing",
    "summary": "Billing plans per job, the reminder for work finished but never invoiced, "
    "and dunning that escalates",
    "description": """
Custom SPK Billing
==================

Three billing shapes, chosen per job
------------------------------------

A small single-venue job bills once. A multi-venue job bills per shipment. A large
one bills against milestones — typically 50% down, 40% on handover, 10% retention
after the event. The shape is a property of the job, not a company-wide setting,
because the same contractor does all three in the same month.

The reminder that recovers the most money
-----------------------------------------

Two kinds of reminder are needed and only one of them is usually built.

The one everybody builds chases the client: the invoice is overdue, escalate.

The one that actually leaks money is internal. The booth is standing, the crew has
moved to the next event, and nobody raised the invoice. Work finished and never billed
does not appear in a receivables report, because there is no receivable — it is simply
missing. So a daily cron looks for jobs with a signed handover and no invoice, and
puts it in front of Finance.

Dunning escalates on a schedule
-------------------------------

Levels are data, not code: days overdue, what to do, which template. The sequence ends
at the owner rather than looping politely forever.

Credit control closes the loop
------------------------------

In event work repeat orders come fast, and it is easy to take a second job from a
client who has not paid for the first. A client with debt past the configured age
raises a warning when a new estimate is raised for them — a warning, not a block: that
call belongs to the owner, who may well have a reason.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_spk", "custom_spk_delivery", "account", "mail"],
    "capability_tags": ["billing", "dunning", "credit-control", "receivables"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        # The template must load before the levels that reference it.
        "data/mail_template_data.xml",
        "data/custom_spk_followup_data.xml",
        "views/custom_spk_billing_views.xml",
        "views/custom_spk_followup_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
