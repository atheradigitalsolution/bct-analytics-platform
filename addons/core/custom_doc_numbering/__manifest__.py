# -*- coding: utf-8 -*-
{
    "name": "Document Numbering",
    "version": "19.0.1.0.0",
    "summary": "Per-company document numbering (SQ/SO/PO/INV/DO/BAST) with monthly reset.",
    "description": """
the tenant Document Numbering
===========================
Applies the tenant's document-number format from the master-data "Document #"
sheet to the two companies in the tenant (PT the tenant, PT the tenant):

  Sales Quotation   SQ/<CO>/YYYY/MM/NNN   (sale.order while draft/sent)
  Sales Order       SO/<CO>/YYYY/MM/NNN   (sale.order, re-numbered on confirm)
  Purchase Order    PO/<CO>/YYYY/MM/NNN   (purchase.order)
  Invoice           INV/<CO>/YYYY/MM/NNN  (account.move, customer invoice)
  Delivery Order    DO/the tenant/YYYY/MM/NNN    (stock.picking, outgoing, the tenant only)
  BAST              BAST/<CO>/YYYY/MM/NNN (custom.bast.document)

<CO> is the company short code (the tenant / the tenant) held on ``res.company.x_doc_code``.
NNN is a 3-digit running number that RESETS every month.

Mechanism
---------
* Per-company ``ir.sequence`` records (``company_id`` set) so each company gets
  its own prefix; ``next_by_code`` automatically picks the active company's one.
* Monthly reset via ``use_date_range`` + a scoped ``ir.sequence`` override that
  creates MONTHLY date ranges (stock Odoo only creates yearly ranges).
* Quotation -> Sales Order re-numbering on confirm; the original SQ number is
  kept on ``sale.order.x_quotation_name`` for audit.
* Customer invoices use a monthly ``_get_starting_sequence`` (gated to companies
  that have ``x_doc_code`` set), so other tenants/companies are untouched.

SCOPE: core tier — any tenant that numbers documents this way. Behaviour is
gated by ``res.company.x_doc_code``, so installing it changes nothing until a
company is given a code; a multi-company database can adopt it per company.
Promoted from ``_tenants/`` once a second client needed the same numbering.
""",
    "author": "Platform",
    "website": "https://example.com/custom-platform",
    "category": "Core/Document Numbering",
    "depends": [
        "sale_management",
        "purchase",
        "stock",
        "account",
        "custom_bast",
        "custom_core",
    ],
    "data": [
        "views/res_company_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "application": False,
    "license": "LGPL-3",
}
