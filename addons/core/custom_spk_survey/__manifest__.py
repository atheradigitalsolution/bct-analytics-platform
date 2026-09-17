# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Survey",
    "summary": "Site survey before the estimate, because most installation overrun is "
    "a venue condition nobody looked at",
    "description": """
Custom SPK Survey
=================

Cost overrun on installation rarely comes from the build. It comes from the venue:
a ceiling lower than the drawing, a loading dock that cannot take the truck, a lift
that will not take a 3-metre panel, permitted hours that turn a day job into two
nights, and venue charges for power, permits and security that nobody asked about.

None of that is visible from a brief. So the survey is a checklist filled on site and
attached to the job before the estimate is priced, and the estimate gets a real number
for access and venue cost instead of an optimistic one.

Deliberately a checklist, not a questionnaire
---------------------------------------------

Every field here exists because getting it wrong costs money on the day. There is no
free-form "notes" field standing in for the questions that matter -- notes are where
answers go to be forgotten.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_spk"],
    "capability_tags": ["site-survey", "estimation", "risk"],
    "data": [
        "security/ir.model.access.csv",
        "views/custom_spk_survey_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
