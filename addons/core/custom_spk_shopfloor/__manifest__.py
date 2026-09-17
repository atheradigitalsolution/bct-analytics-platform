# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Shopfloor",
    "summary": "One round of the workshop, entered in under a minute on a phone, and "
    "queued when there is no signal",
    "description": """
Custom SPK Shopfloor
====================

The requirements document ends with the sharpest risk assessment in it: adoption on the
workshop floor, not technology, is what decides whether any of this works, and if input
takes more than sixty seconds on a phone the supervisor goes back to a notebook and the
entire costing chain collapses.

That risk is now concentrated in one person, because this deployment has a single
supervisor covering every workshop. So the input path gets its own module rather than
being left to the standard form views.

What it actually needs
----------------------

* **One screen per round, not per person.** The supervisor walks the workshops once and
  ticks who is present. A form per worker per shift would not be filled in.
* **Workshop switching inside one session**, because one person covers all of them in a
  single pass.
* **Offline tolerance.** Welding and paint bays have poor signal, and a form that fails
  to submit is a form that stops being used in week two.

Built on custom_hht_bridge
--------------------------

``custom_hht_bridge`` in ``core`` already carries the expensive part: a PWA shell with a
service worker, a FIFO sync queue for events raised while offline, device enrolment with
HMAC, and GPS capture. This module adds the endpoints those screens post to. Writing a
second offline queue would have been the largest avoidable piece of work in the project.

The queue-and-presign trap
--------------------------

Photographs are held outside the filestore as links, and the upload URL is pre-signed
with a short life. A URL requested when a photo enters the offline queue is expired by
the time the signal returns two hours later, and the upload fails silently. So the photo
is queued and the URL is requested **at flush time**, never at enqueue time.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": [
        "custom_spk",
        "custom_spk_workforce",
        "custom_spk_material",
        "custom_core",
    ],
    "capability_tags": ["shopfloor", "mobile", "offline", "attendance", "hht"],
    "data": [
        "security/ir.model.access.csv",
        "views/custom_spk_shopfloor_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
