# -*- coding: utf-8 -*-
"""Bill lines: frozen prices and the payer/patient split."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsBillLine(models.Model):
    _name = "hms.bill.line"
    _description = "Baris Tagihan"
    _order = "bill_id, report_section, id"

    bill_id = fields.Many2one("hms.bill", required=True, ondelete="cascade", index=True)
    encounter_id = fields.Many2one(related="bill_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="bill_id.patient_id", store=True, index=True)

    source_model = fields.Char("Model Sumber", index=True)
    source_id = fields.Integer("ID Sumber", index=True)
    tariff_id = fields.Many2one("hms.tariff", "Item Tarif", required=True)
    category_id = fields.Many2one(related="tariff_id.category_id", store=True)
    report_section = fields.Selection(related="tariff_id.report_section", store=True)
    name = fields.Char("Deskripsi", required=True)
    unit_id = fields.Many2one("hms.unit", "Unit Pelaksana", index=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Praktisi")
    service_date = fields.Date("Tanggal Layanan", required=True,
                               default=lambda s: fields.Date.context_today(s), index=True)

    currency_id = fields.Many2one(related="bill_id.currency_id", store=True, readonly=True)
    qty = fields.Float("Jumlah", default=1.0, required=True)
    unit_price = fields.Monetary("Harga Satuan", required=True)
    price_subtotal = fields.Monetary("Subtotal", compute="_compute_amounts", store=True)

    # The service-component split, frozen at charge time. Doctor fees are paid
    # from amount_medical, so this must survive any later tariff revision.
    amount_facility = fields.Monetary("Jasa Sarana")
    amount_medical = fields.Monetary("Jasa Medis")
    amount_consumable = fields.Monetary("BHP")
    amount_other = fields.Monetary("Komponen Lain")

    discount_percent = fields.Float("Diskon (%)")
    discount_amount = fields.Monetary("Nilai Diskon", compute="_compute_amounts", store=True)
    coverage_percent = fields.Float("Ditanggung Penjamin (%)", default=0.0)
    amount_payer = fields.Monetary("Porsi Penjamin", compute="_compute_amounts", store=True)
    amount_patient = fields.Monetary("Porsi Pasien", compute="_compute_amounts", store=True)
    coverage_note = fields.Char("Dasar Penjaminan")

    state = fields.Selection(
        [("draft", "Draf"), ("confirmed", "Terbebankan"), ("cancelled", "Dibatalkan")],
        default="confirmed", required=True, index=True,
    )
    price_missing = fields.Boolean(
        "Tarif Belum Ditetapkan", index=True,
        help="Layanan sudah diberikan tetapi belum ada harga yang berlaku untuk "
             "kombinasi kelas/penjamin pada tanggal itu.",
    )
    cancel_reason = fields.Char("Alasan Pembatalan")

    _source_uniq = models.UniqueIndex(
        "(source_model, source_id) WHERE source_model IS NOT NULL AND state != 'cancelled'",
    )

    @api.depends("qty", "unit_price", "discount_percent", "coverage_percent", "state")
    def _compute_amounts(self):
        for line in self:
            subtotal = line.qty * line.unit_price
            line.price_subtotal = subtotal
            line.discount_amount = subtotal * (line.discount_percent or 0.0) / 100.0
            net = subtotal - line.discount_amount
            line.amount_payer = net * (line.coverage_percent or 0.0) / 100.0
            line.amount_patient = net - line.amount_payer

    @api.model
    def charge(self, bill, tariff, qty=1.0, source=None, unit=None, practitioner=None,
               service_date=None, name=None, cito=False, class_override=None, note=None):
        """Create one charge, resolving price and coverage once.

        Every module that bills goes through here so the price resolution and
        the coverage rules exist in exactly one place.
        """
        encounter = bill.encounter_id
        service_date = service_date or fields.Date.context_today(bill)
        charge_class = class_override or encounter.class_id
        price_missing = False
        try:
            price = tariff.resolve_price(
                class_id=charge_class.id if charge_class else None,
                payer_id=encounter.payer_id.id,
                date=service_date,
                cito=cito,
            )
            amounts = price.effective_amounts(qty=qty)
        except ValidationError:
            # A missing tariff price is an administrative gap, not a clinical
            # one. Refusing here would stop a doctor from verifying a lab
            # result because nobody priced the test — so the charge is raised
            # at zero and flagged instead. hms.bill.action_open() then refuses
            # to take payment until the gap is closed, which is where the
            # money actually moves.
            price_missing = True
            amounts = {
                "unit_price": 0.0, "price_subtotal": 0.0, "amount_facility": 0.0,
                "amount_medical": 0.0, "amount_consumable": 0.0, "amount_other": 0.0,
            }
        coverage, reason = self._resolve_coverage(encounter, tariff)
        if price_missing:
            reason = _("TARIF BELUM DITETAPKAN — baris ini belum dapat ditagihkan")
            coverage = 0.0
        vals = {
            "bill_id": bill.id,
            "tariff_id": tariff.id,
            "name": name or tariff.name,
            "qty": qty,
            "unit_id": (unit or tariff.unit_id or encounter.unit_id).id,
            "practitioner_id": practitioner.id if practitioner else False,
            "service_date": service_date,
            "unit_price": amounts["unit_price"],
            "amount_facility": amounts["amount_facility"],
            "amount_medical": amounts["amount_medical"],
            "amount_consumable": amounts["amount_consumable"],
            "amount_other": amounts["amount_other"],
            "coverage_percent": coverage,
            "coverage_note": reason,
            "price_missing": price_missing,
        }
        if source is not None:
            vals["source_model"] = source._name
            vals["source_id"] = source.id
        if note:
            vals["coverage_note"] = f"{reason} · {note}" if reason else note
        return self.create(vals)

    @api.model
    def _resolve_coverage(self, encounter, tariff):
        """How much of this item the guarantor pays, and why.

        Returns the percentage plus a human-readable reason, because the first
        question at the cashier desk is never "how much" — it is "why".
        """
        plan = encounter.payer_plan_id
        payer = encounter.payer_id
        if not payer or payer.type == "self":
            return 0.0, _("Pasien umum")
        if not plan:
            # A guarantor without a plan on the encounter covers nothing until
            # someone picks one; defaulting to full cover would invoice a payer
            # for terms nobody agreed.
            return 0.0, _("Plan penjamin belum dipilih")
        if tariff.category_id in plan.excluded_category_ids:
            return 0.0, _("Kategori %s dikecualikan plan %s") % (
                tariff.category_id.name, plan.name
            )
        if payer.requires_sep and not encounter.sep_no:
            return 0.0, _("SEP belum terbit")
        return plan.coverage_percent, _("Plan %s menanggung %.0f%%") % (
            plan.name, plan.coverage_percent
        )

    def _prepare_move_line_vals(self, portion):
        """Turn a bill line into an invoice line for one counterparty."""
        self.ensure_one()
        amount = self.amount_payer if portion == "payer" else self.amount_patient
        product = self.tariff_id.product_id or self.category_id.product_id
        label = self.name
        if portion == "payer":
            label = _("%s (porsi penjamin)") % label
        elif self.coverage_percent:
            label = _("%s (porsi pasien)") % label
        vals = {
            "name": label,
            "quantity": 1.0,
            "price_unit": amount,
        }
        if product:
            vals["product_id"] = product.id
        return vals

    def action_cancel_line(self, reason=None):
        for line in self:
            if line.bill_id.state in ("closed", "cancelled"):
                raise UserError(
                    _("Tagihan %s sudah ditutup; baris tidak dapat dibatalkan.") % line.bill_id.name
                )
            if not (reason or line.cancel_reason):
                raise UserError(_("Alasan pembatalan baris wajib dicatat."))
            line.write({"state": "cancelled", "cancel_reason": reason or line.cancel_reason})
        return True

    def write(self, vals):
        """A closed bill is an accounting document, not a worksheet."""
        if not self.env.context.get("hms_billing_internal"):
            locked = self.filtered(lambda l: l.bill_id.state == "closed")
            if locked and set(vals) - {"state"}:
                raise UserError(
                    _("Baris pada tagihan yang sudah ditutup tidak dapat diubah.")
                )
        return super().write(vals)
