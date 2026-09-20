# -*- coding: utf-8 -*-
"""Patient receivables and instalments."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class HmsPatientReceivable(models.Model):
    _name = "hms.patient.receivable"
    _description = "Piutang Pasien"
    _order = "id desc"

    patient_id = fields.Many2one("hms.patient", required=True, index=True)
    bill_id = fields.Many2one("hms.bill", required=True, ondelete="restrict", index=True)
    currency_id = fields.Many2one(related="bill_id.currency_id", readonly=True)
    amount = fields.Monetary("Jumlah Piutang", required=True)
    paid_amount = fields.Monetary("Sudah Dibayar", compute="_compute_paid", store=True)
    balance = fields.Monetary("Sisa", compute="_compute_paid", store=True)
    installment_ids = fields.One2many("hms.receivable.installment", "receivable_id", "Cicilan")
    due_date = fields.Date("Jatuh Tempo")
    aging_days = fields.Integer("Umur (hari)", compute="_compute_aging")
    state = fields.Selection(
        [("open", "Terbuka"), ("partial", "Sebagian"), ("settled", "Lunas"),
         ("written_off", "Dihapusbukukan")],
        default="open", required=True, index=True,
    )
    approved_by_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True)
    note = fields.Text()

    @api.depends("installment_ids.amount", "installment_ids.state", "amount")
    def _compute_paid(self):
        for rec in self:
            paid = sum(
                rec.installment_ids.filtered(lambda i: i.state == "paid").mapped("amount")
            )
            rec.paid_amount = paid
            rec.balance = rec.amount - paid

    def _compute_aging(self):
        today = fields.Date.context_today(self)
        for rec in self:
            base = rec.due_date or (rec.create_date.date() if rec.create_date else today)
            rec.aging_days = (today - base).days

    @api.model
    def create_from_bill(self, bill, amount, note=None):
        """Let a patient leave owing money — as a recorded, approved decision."""
        if not self.env.user.has_group("custom_hms_base.group_hms_billing_supervisor"):
            raise UserError(
                _("Hanya supervisor kasir yang dapat menyetujui pasien pulang dengan "
                  "sisa tagihan.")
            )
        if float_compare(amount, bill.amount_due, precision_digits=2) > 0:
            raise UserError(_("Piutang tidak boleh melebihi sisa tagihan."))
        receivable = self.create({
            "patient_id": bill.patient_id.id,
            "bill_id": bill.id,
            "amount": amount,
            "due_date": fields.Date.add(fields.Date.context_today(self), days=30),
            "approved_by_id": self.env.uid,
            "note": note,
        })
        self.env["hms.payment"].with_context(hms_skip_session=True).create({
            "bill_id": bill.id,
            "method": "receivable",
            "amount": amount,
            "reference": receivable.display_name,
        })
        return receivable

    def action_settle(self):
        for rec in self:
            if float_compare(rec.balance, 0.0, precision_digits=2) > 0:
                raise UserError(_("Masih ada sisa piutang %s.") % rec.balance)
            rec.write({"state": "settled"})
        return True


class HmsReceivableInstallment(models.Model):
    _name = "hms.receivable.installment"
    _description = "Cicilan Piutang Pasien"
    _order = "due_date"

    receivable_id = fields.Many2one("hms.patient.receivable", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="receivable_id.currency_id", readonly=True)
    sequence = fields.Integer(default=10)
    amount = fields.Monetary("Jumlah", required=True)
    due_date = fields.Date("Jatuh Tempo", required=True)
    paid_at = fields.Datetime(readonly=True)
    state = fields.Selection(
        [("pending", "Belum Dibayar"), ("paid", "Dibayar"), ("overdue", "Terlambat")],
        default="pending", required=True,
    )

    def action_pay(self):
        for rec in self:
            rec.write({"state": "paid", "paid_at": fields.Datetime.now()})
            if float_compare(rec.receivable_id.balance, 0.0, precision_digits=2) <= 0:
                rec.receivable_id.write({"state": "settled"})
            else:
                rec.receivable_id.write({"state": "partial"})
        return True
