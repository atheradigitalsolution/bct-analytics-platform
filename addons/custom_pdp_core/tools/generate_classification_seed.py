#!/usr/bin/env python3
"""Regenerate ``data/pdp.field.classification.csv`` from a live Odoo 19 database.

This is a DEVELOPMENT tool. It is deliberately *not* imported by the module (no entry in any
``__init__.py``), so it never runs inside Odoo. Its output is committed to git; the module never
needs a database to install.

Why it exists
-------------
Contract 01 makes an unclassified column a hard failure in the CDC loader. Hand-maintaining a
classification for ~670 physical columns is exactly the sort of list that silently rots. So the
list of columns is machine-generated from ``information_schema.columns`` (the real Postgres
columns, not ``ir.model.fields`` - one2many and many2many "fields" have no column and never reach
the warehouse), and only the *decisions* are hand-written, in ``OVERRIDES`` below.

Usage
-----
    python3 generate_classification_seed.py \
        --dsn "postgresql://odoo:changeme@127.0.0.1:35432/erp_dev" \
        --out ../data/pdp.field.classification.csv

Anything not named in ``OVERRIDES`` or matched by ``SUFFIX_RULES`` falls back to ``internal``.
``internal`` is the safe default here because it is *not* published and *not* dropped: it simply
means "business data, no personal content". A column that is actually personal and is left at the
default is a classification bug, which is what the module's coverage + spot-check tests exist to
catch.
"""

import argparse
import csv
import re
import sys

# --------------------------------------------------------------------------------------
# The models the warehouse reads. Extending the platform means extending this list AND
# re-running this generator.
# --------------------------------------------------------------------------------------
MODELS = [
    ("res.partner", "res_partner"),
    ("res.users", "res_users"),
    ("res.company", "res_company"),
    ("product.template", "product_template"),
    ("product.product", "product_product"),
    ("sale.order", "sale_order"),
    ("sale.order.line", "sale_order_line"),
    ("account.move", "account_move"),
    ("account.move.line", "account_move_line"),
    ("stock.move", "stock_move"),
    ("stock.picking", "stock_picking"),
    ("pos.order", "pos_order"),
    ("pos.order.line", "pos_order_line"),
]

ART_42 = "UU 27/2022 Art. 4(2) - data pribadi umum"
ART_43 = "UU 27/2022 Art. 4(3) - data pribadi spesifik"
ART_43_G = "UU 27/2022 Art. 4(3) huruf g - data pribadi lainnya"
SECRET_BASIS = "UU 27/2022 Art. 35 - kewajiban pelindungan; credential material"
INTERNAL_BASIS = "Not personal data - business record"
PUBLIC_BASIS = "Not personal data - published to counterparties"

# (pdp_class, drop_to_null, legal_basis, notes)
PERSONAL = ("personal", False, ART_42, "Direct identifier of a natural person; hashed at load so joins survive.")
SENSITIVE = ("sensitive", False, ART_43, "Specific personal data; hashed at load, never revealed.")
FREETEXT = ("sensitive", True, ART_43, "Free text - may contain any category of personal data; dropped to NULL at load.")
SECRET = ("secret", False, SECRET_BASIS, "Credential or key material; never named in the extraction SELECT list.")
INTERNAL = ("internal", False, INTERNAL_BASIS, "")
PUBLIC = ("public", False, PUBLIC_BASIS, "")

GEO = ("sensitive", True, ART_43_G, "Precise geolocation of a natural person; dropped to NULL - a digest of a coordinate has no analytic value.")

# --------------------------------------------------------------------------------------
# Hand-written decisions. Keyed "model.column".
# --------------------------------------------------------------------------------------
OVERRIDES = {
    # ---------------- res.partner : the canonical personal-data table ----------------
    "res.partner.name": PERSONAL,
    "res.partner.complete_name": PERSONAL,
    "res.partner.commercial_company_name": PERSONAL,
    "res.partner.company_name": PERSONAL,
    "res.partner.email": PERSONAL,
    "res.partner.email_normalized": PERSONAL,
    "res.partner.phone": PERSONAL,
    "res.partner.phone_sanitized": PERSONAL,
    "res.partner.street": PERSONAL,
    "res.partner.street2": PERSONAL,
    "res.partner.city": PERSONAL,
    "res.partner.zip": PERSONAL,
    "res.partner.function": PERSONAL,
    "res.partner.ref": PERSONAL,
    "res.partner.barcode": PERSONAL,
    "res.partner.website": PERSONAL,
    "res.partner.company_registry": PERSONAL,
    "res.partner.global_location_number": PERSONAL,
    "res.partner.peppol_endpoint": PERSONAL,
    "res.partner.signup_type": PERSONAL,
    # vat carries NPWP for a badan and NIK for a perorangan under Coretax - Art. 4(3).
    "res.partner.vat": ("sensitive", False, ART_43, "Indonesian NPWP / NIK. Art. 4(3) specific personal data. Hashed at load."),
    "res.partner.comment": FREETEXT,
    "res.partner.picking_warn_msg": FREETEXT,
    "res.partner.sale_warn_msg": FREETEXT,
    "res.partner.properties": ("sensitive", True, ART_43, "User-defined JSON properties - arbitrary content; dropped to NULL at load."),
    "res.partner.partner_latitude": GEO,
    "res.partner.partner_longitude": GEO,
    # Financial standing of an individual partner. Contract 01 classifies transaction amounts as
    # `internal` (its own example: sale.order.amount_total), so partner-level credit config stays
    # internal for consistency; only the free-text and identifier columns move up.
    "res.partner.credit_limit": INTERNAL,
    # lang and tz reveal locale and rough timezone, which is weakly identifying, but they are
    # dimension keys the warehouse groups by and they are not Art. 4(2) identifiers on their own.
    "res.partner.lang": INTERNAL,
    "res.partner.tz": INTERNAL,

    # ---------------- res.users ----------------
    "res.users.login": PERSONAL,
    "res.users.password": SECRET,
    "res.users.totp_secret": SECRET,
    "res.users.signature": FREETEXT,
    "res.users.out_of_office_message": FREETEXT,

    # ---------------- res.company : a legal entity, not a natural person ----------------
    "res.company.name": PUBLIC,
    "res.company.email": PUBLIC,
    "res.company.phone": PUBLIC,
    "res.company.company_details": PUBLIC,
    "res.company.report_header": PUBLIC,
    "res.company.report_footer": PUBLIC,
    "res.company.invoice_terms": PUBLIC,
    "res.company.invoice_terms_html": PUBLIC,
    "res.company.bank_account_code_prefix": INTERNAL,
    "res.company.cash_account_code_prefix": INTERNAL,
    "res.company.transfer_account_code_prefix": INTERNAL,

    # ---------------- product catalogue : publishable ----------------
    "product.template.name": PUBLIC,
    "product.template.default_code": PUBLIC,
    "product.template.barcode": PUBLIC,
    "product.template.description": PUBLIC,
    "product.template.description_sale": PUBLIC,
    "product.template.public_description": PUBLIC,
    "product.template.list_price": PUBLIC,
    "product.template.uom_name": PUBLIC,
    "product.product.default_code": PUBLIC,
    "product.product.barcode": PUBLIC,
    "product.product.name": PUBLIC,
    # Cost is not published.
    "product.template.standard_price": INTERNAL,

    # ---------------- sale ----------------
    "sale.order.access_token": SECRET,
    "sale.order.signed_by": PERSONAL,
    "sale.order.note": FREETEXT,
    "sale.order.client_order_ref": PERSONAL,
    "sale.order.reference": INTERNAL,
    # NOTE: sale.order.signature and stock.picking.signature are fields.Image with
    # attachment=True, so they have NO column on their own table - the bytes live in
    # ir_attachment. They are therefore not classifiable here. The CDC loader does not
    # extract ir_attachment at all; see MODULE_KNOWLEDGE.md, "Scope boundaries".

    # ---------------- account ----------------
    "account.move.access_token": SECRET,
    "account.move.inalterable_hash": SECRET,
    "account.move.narration": FREETEXT,
    "account.move.invoice_source_email": PERSONAL,
    "account.move.invoice_partner_display_name": PERSONAL,
    "account.move.partner_credit_warning": FREETEXT,
    # account.move.line.name / sale.order.line.name are document *labels*, defaulted from the
    # product name and edited to things like "Paket Data 10GB - Sept 2026". Contract 01 puts
    # document business data at `internal` (its own example: sale.order.amount_total), and the
    # warehouse needs the label for line-level reporting. Kept internal deliberately; the
    # genuinely narrative columns (narration, note, comment, *_customer_note) stay sensitive.

    # ---------------- stock ----------------
    "stock.picking.note": FREETEXT,
    "stock.move.description_picking_manual": FREETEXT,

    # ---------------- point of sale ----------------
    "pos.order.access_token": SECRET,
    "pos.order.ticket_code": SECRET,
    "pos.order.email": PERSONAL,
    "pos.order.mobile": PERSONAL,
    "pos.order.floating_order_name": PERSONAL,
    "pos.order.tracking_number": INTERNAL,
    "pos.order.general_customer_note": FREETEXT,
    "pos.order.internal_note": FREETEXT,
    "pos.order.last_order_preparation_change": INTERNAL,
    "pos.order.line.customer_note": FREETEXT,
    "pos.order.line.note": FREETEXT,
    "pos.order.line.notice": FREETEXT,
}

# --------------------------------------------------------------------------------------
# Pattern rules applied when no explicit override matched. Ordered; first match wins.
# --------------------------------------------------------------------------------------
SUFFIX_RULES = [
    (re.compile(r"(^|_)(access_token|secret|token|api_key|private_key|passwd|password)$"), SECRET),
]

# --------------------------------------------------------------------------------------
# Models the registry classifies but which live in custom modules. Their columns are listed
# explicitly because they may not exist in the database this generator is pointed at.
# --------------------------------------------------------------------------------------
CUSTOM_ROWS = [
    # (model, field, class, drop_to_null, legal_basis, notes)
    ("ppob.transaction", "id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "create_date", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "create_uid", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "write_date", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "write_uid", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "name", "internal", False, INTERNAL_BASIS, "System-generated transaction reference."),
    ("ppob.transaction", "partner_id", "internal", False, INTERNAL_BASIS, "FK to res.partner; the partner's own columns carry the personal classes."),
    ("ppob.transaction", "biller_id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "product_id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "company_id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "currency_id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "amount", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "admin_fee", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "commission", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "total_amount", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "customer_ref", "sensitive", False, ART_43,
     "Subscriber / meter number. Identifies a household and its consumption; treated as Art. 4(3) "
     "specific personal data. Hashed at load - the digest still supports repeat-customer counts."),
    ("ppob.transaction", "customer_name", "personal", False, ART_42,
     "Name returned by the biller inquiry for the subscriber."),
    ("ppob.transaction", "state", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "requested_at", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "settled_at", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "sla_seconds", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.transaction", "failure_reason", "sensitive", True, ART_43,
     "Free text from the biller; may echo subscriber details. Dropped to NULL at load."),
    ("ppob.transaction", "biller_reference", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "id", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "create_date", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "create_uid", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "write_date", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "write_uid", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "name", "public", False, PUBLIC_BASIS, ""),
    ("ppob.biller", "code", "public", False, PUBLIC_BASIS, ""),
    ("ppob.biller", "active", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "sla_target_seconds", "internal", False, INTERNAL_BASIS, ""),
    ("ppob.biller", "category", "public", False, PUBLIC_BASIS, ""),
    ("ppob.biller", "company_id", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "id", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "create_date", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "create_uid", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "write_date", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "write_uid", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "name", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "code", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "complete_name", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "company_id", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "parent_id", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "parent_path", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "active", "internal", False, INTERNAL_BASIS, ""),
    ("operating.unit", "manager_id", "internal", False, INTERNAL_BASIS, ""),
    # operating_unit_id is injected by custom_operating_unit into stock models.
    ("sale.order", "operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
    ("account.move", "operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
    ("stock.picking", "operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
    ("pos.order", "operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
    ("res.users", "default_operating_unit_id", "internal", False, INTERNAL_BASIS, ""),
]


def xmlid(model, field):
    return "pdp_%s__%s" % (model.replace(".", "_"), field)


def classify(model, column):
    key = "%s.%s" % (model, column)
    if key in OVERRIDES:
        return OVERRIDES[key]
    for pattern, decision in SUFFIX_RULES:
        if pattern.search(column):
            return decision
    return INTERNAL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True, help="libpq connection string to a live Odoo DB")
    parser.add_argument("--out", required=True, help="path of the CSV to write")
    args = parser.parse_args()

    import psycopg2  # noqa: PLC0415 - dev-only dependency

    rows = []
    seen = set()
    with psycopg2.connect(args.dsn) as conn, conn.cursor() as cur:
        for model, table in MODELS:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY column_name",
                (table,),
            )
            columns = [r[0] for r in cur.fetchall()]
            if not columns:
                print("WARNING: table %s not found - model %s skipped" % (table, model),
                      file=sys.stderr)
                continue
            for column in columns:
                pdp_class, drop, basis, notes = classify(model, column)
                rows.append((xmlid(model, column), model, column, pdp_class, basis, notes,
                             "True" if drop else "False"))
                seen.add((model, column))

    for model, field, pdp_class, drop, basis, notes in CUSTOM_ROWS:
        if (model, field) in seen:
            continue
        seen.add((model, field))
        rows.append((xmlid(model, field), model, field, pdp_class, basis, notes,
                     "True" if drop else "False"))

    rows.sort(key=lambda r: (r[1], r[2]))
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["id", "model_name", "field_name", "pdp_class", "legal_basis", "notes",
                         "drop_to_null"])
        writer.writerows(rows)
    print("wrote %d rows to %s" % (len(rows), args.out))


if __name__ == "__main__":
    main()
