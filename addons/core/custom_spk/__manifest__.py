# -*- coding: utf-8 -*-
{
    "name": "Custom SPK",
    "summary": "Surat Perintah Kerja as the golden thread, with the price fence that "
    "keeps selling price and cost away from the people who must not see them",
    "description": """
Custom SPK
==========

Project-based manufacturing (engineer-to-order) runs on one number. A booth, a
display, a stand: every document raised against it -- design task, material
request, shift, delivery, invoice -- has to carry the same reference, or cost per
job cannot be reconstructed afterwards. This module owns that number and the
access model around it.

Two things live here that a BRD would name separately:

* ``custom.spk`` and ``custom.spk.shift``, the record and the shift master.
* The security groups, record rules and field-level fences.

They are not split, because a record rule has nothing to attach to before the
model exists, and because nothing else in the pack can be installed without both.

The price fence
---------------

Hiding a monetary field in a form view is not a fence. A user who can read the
model reads the field through list view, export, ``read_group``, or the ORM over
JSON-RPC. So the fence is built at two levels that the ORM enforces:

1. ``custom.spk`` carries **no monetary field at all**. Not hidden -- absent. The
   Account Executive works on this model and there is nothing on it to leak.
   ``tests/test_price_fence.py`` asserts the absence by introspection, so adding
   one later fails the suite rather than quietly widening the exposure.
2. ``product.template.standard_price`` is gated behind
   ``group_spk_cost_viewer``. Odoo ships that field with no restricting group, so
   anyone who can read a product can read its cost -- and from a bill of quantity,
   cost to price is arithmetic. This was the hole that a view-level fence left open.

``list_price`` is deliberately NOT gated. In engineer-to-order work it is not the
quoted price: the quotation carries the price, and the AE has no access to
``sale.order`` at all. Gating it would cost the website and portal flows a field
they legitimately need, to close a door that is already shut.

``account.analytic.line`` is where all job cost lands. The AE is granted no
accounting group, so the standard ACL already denies it -- but the suite asserts
that rather than trusting it, because the day someone adds the AE to an accounting
group for an unrelated reason, this is what should fail.

One roving supervisor
---------------------

This deployment has a single supervisor covering every workshop, so there is no
per-workshop record rule. Adding one would be a fence around a set of one, and an
invitation to bypass it later. The supervisor group sees every SPK; the AE sees
only their own.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": [
        "custom_core",
        "custom_pdp_audit",
        "mail",
        "project",
        "analytic",
    ],
    "capability_tags": ["spk", "job-costing", "access-control", "audit-trail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/custom_spk_shift_data.xml",
        "views/custom_spk_views.xml",
        "views/custom_spk_shift_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
