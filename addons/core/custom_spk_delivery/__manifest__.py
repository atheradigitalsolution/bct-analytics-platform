# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Delivery",
    "summary": "One job, several venues, each with its own loading window, crew and "
    "handover — and the dismantle that gets forgotten until it is billed",
    "description": """
Custom SPK Delivery
===================

A job does not ship once
------------------------

One SPK routinely lands in more than one place: the main booth at a convention
centre, display tables at a mall, a backdrop back at the first venue. Odoo's sales
order carries a single shipping address, which is why the delivery schedule lives
here instead of on order lines: each shipment has its own venue, its own loading
window, its own crew, and its own handover document.

The loading window is not a preference
--------------------------------------

Venues dictate when goods may enter — often between 22:00 and 06:00 — and a schedule
that treats that as a soft date produces a crew standing outside a locked dock. So
``loading_in`` is required on a shipment that has a venue, and the dismantle window
is captured with it.

Handover reuses BAST
--------------------

``custom.bast.document`` in ``core`` already does dual signature, GPS, timestamp and
an audit trail. It is linked through its ``reference`` field rather than copied. The
delivery moves to ``bast_signed`` only when the client side has actually signed,
because that state is what billing waits on: without a signed handover, a client's
finance department routinely declines the invoice.

Dismantle is a cost, not a revenue
----------------------------------

The client for this build does not rent booths out, so nothing comes back to be
re-let. The dismantle still happens, still needs a crew, a truck and a venue slot,
and is still routinely left out of the estimate — so it is scheduled here and its cost
lands on the job like any other.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_object_storage", "custom_spk", "custom_bast", "stock", "analytic"],
    "capability_tags": ["delivery", "installation", "bast", "handover", "job-costing"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/custom_spk_delivery_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
