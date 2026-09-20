# -*- coding: utf-8 -*-
"""Doctor fee accrual and periodic settlement."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero


class HmsMedicalFeeRule(models.Model):
    _name = "hms.medical.fee.rule"
    _description = "Aturan Jasa Medis"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    tariff_id = fields.Many2one("hms.tariff", "Item Tarif")
    category_id = fields.Many2one("hms.tariff.category", "Kategori Tarif")
    practitioner_id = fields.Many2one("hms.practitioner", "Khusus Dokter")
    payer_id = fields.Many2one("hms.payer", "Khusus Penjamin")
    percent = fields.Float(
        "Persentase dari Jasa Medis", default=100.0,
        help="Berapa persen dari komponen jasa medis yang menjadi hak praktisi.",
    )
    fixed_amount = fields.Monetary("Nominal Tetap", currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    valid_from = fields.Date()
    valid_to = fields.Date()
    active = fields.Boolean(default=True)

    @api.model
    def resolve(self, bill_line):
        """Most specific rule wins; absent any rule, the doctor gets it all."""
        date = bill_line.service_date
        domain = [
            "|", ("valid_from", "=", False), ("valid_from", "<=", date),
            "|", ("valid_to", "=", False), ("valid_to", ">=", date),
        ]
        rules = self.search(domain, order="sequence")

        def matches(rule, tariff, practitioner, payer):
            if rule.tariff_id and rule.tariff_id != tariff:
                return False
            if rule.category_id and rule.category_id != tariff.category_id:
                return False
            if rule.practitioner_id and rule.practitioner_id != practitioner:
                return False
            if rule.payer_id and rule.payer_id != payer:
                return False
            return True

        candidates = [
            r for r in rules
            if matches(r, bill_line.tariff_id, bill_line.practitioner_id,
                       bill_line.bill_id.payer_id)
        ]
        if not candidates:
            return None
        # Specificity = how many dimensions the rule pins down.
        return max(candidates, key=lambda r: sum(
            bool(x) for x in (r.tariff_id, r.category_id, r.practitioner_id, r.payer_id)
        ))


class HmsMedicalFee(models.Model):
    _name = "hms.medical.fee"
    _description = "Jasa Medis Praktisi"
    _order = "date desc, id desc"

    bill_line_id = fields.Many2one("hms.bill.line", required=True, ondelete="cascade", index=True)
    bill_id = fields.Many2one(related="bill_line_id.bill_id", store=True, index=True)
    practitioner_id = fields.Many2one("hms.practitioner", required=True, index=True)
    unit_id = fields.Many2one("hms.unit", index=True)
    encounter_id = fields.Many2one(related="bill_line_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="bill_line_id.patient_id", store=True)
    date = fields.Date(required=True, index=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    gross_amount = fields.Monetary("Komponen Jasa Medis")
    amount = fields.Monetary("Hak Praktisi", required=True)
    fee_rule_id = fields.Many2one("hms.medical.fee.rule", "Aturan")
    state = fields.Selection(
        [("accrued", "Diakui"), ("batched", "Masuk Batch"), ("paid", "Dibayar"),
         ("cancelled", "Dibatalkan")],
        default="accrued", required=True, index=True,
    )
    batch_id = fields.Many2one("hms.medical.fee.batch", "Batch Pembayaran", index=True)

    _line_uniq = models.Constraint(
        "unique(bill_line_id, practitioner_id)",
        "Jasa medis untuk baris tagihan dan praktisi ini sudah dicatat.",
    )

    @api.model
    def accrue_for_bill(self, bill):
        """Record what each doctor earned on this bill, once."""
        created = self.browse()
        for line in bill.line_ids.filtered(lambda l: l.state != "cancelled"):
            if float_is_zero(line.amount_medical, precision_digits=2):
                continue
            if not line.practitioner_id:
                continue
            if self.search_count([
                ("bill_line_id", "=", line.id),
                ("practitioner_id", "=", line.practitioner_id.id),
            ]):
                continue
            rule = self.env["hms.medical.fee.rule"].resolve(line)
            if rule and rule.fixed_amount:
                amount = rule.fixed_amount
            elif rule:
                amount = line.amount_medical * rule.percent / 100.0
            else:
                amount = line.amount_medical
            created |= self.create({
                "bill_line_id": line.id,
                "practitioner_id": line.practitioner_id.id,
                "unit_id": line.unit_id.id,
                "date": line.service_date,
                "gross_amount": line.amount_medical,
                "amount": amount,
                "fee_rule_id": rule.id if rule else False,
            })
        return created


class HmsMedicalFeeBatch(models.Model):
    _name = "hms.medical.fee.batch"
    _description = "Batch Pembayaran Jasa Medis"
    _order = "period desc"

    name = fields.Char(required=True)
    period = fields.Char("Periode", required=True, help="Format YYYY-MM.")
    practitioner_id = fields.Many2one("hms.practitioner", "Praktisi", index=True)
    fee_ids = fields.One2many("hms.medical.fee", "batch_id", "Rincian")
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    total = fields.Monetary(compute="_compute_total", store=True)
    move_id = fields.Many2one("account.move", "Jurnal", readonly=True)
    state = fields.Selection(
        [("draft", "Draf"), ("confirmed", "Dikonfirmasi"), ("paid", "Dibayar")],
        default="draft", required=True,
    )

    @api.depends("fee_ids.amount")
    def _compute_total(self):
        for batch in self:
            batch.total = sum(batch.fee_ids.mapped("amount"))

    @api.model
    def build(self, period, practitioner=None):
        """Collect accrued fees for a period into a payable batch."""
        domain = [("state", "=", "accrued"), ("date", ">=", f"{period}-01")]
        year, month = (int(p) for p in period.split("-"))
        end_month = f"{year + 1}-01-01" if month == 12 else f"{year}-{month + 1:02d}-01"
        domain.append(("date", "<", end_month))
        if practitioner:
            domain.append(("practitioner_id", "=", practitioner.id))
        fees = self.env["hms.medical.fee"].search(domain)
        if not fees:
            raise UserError(_("Tidak ada jasa medis yang diakui pada periode %s.") % period)
        batch = self.create({
            "name": _("Jasa Medis %(p)s%(d)s") % {
                "p": period,
                "d": f" — {practitioner.display_name}" if practitioner else "",
            },
            "period": period,
            "practitioner_id": practitioner.id if practitioner else False,
        })
        fees.write({"batch_id": batch.id, "state": "batched"})
        return batch

    def action_confirm(self):
        for batch in self:
            if not batch.fee_ids:
                raise UserError(_("Batch kosong."))
            batch.write({"state": "confirmed"})
        return True

    def action_mark_paid(self):
        for batch in self:
            batch.fee_ids.write({"state": "paid"})
            batch.write({"state": "paid"})
        return True


class HmsBill(models.Model):
    _inherit = "hms.bill"

    medical_fee_ids = fields.One2many(
        "hms.medical.fee", "bill_id", "Jasa Medis", readonly=True,
    )

    def action_close(self):
        """Closing the bill is what makes the doctor's fee earned."""
        res = super().action_close()
        for bill in self:
            self.env["hms.medical.fee"].accrue_for_bill(bill)
        return res
