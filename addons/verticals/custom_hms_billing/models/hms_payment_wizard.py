# -*- coding: utf-8 -*-
"""Cashier payment screen: several methods against one bill."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

from .hms_deposit import PAYMENT_METHODS


class HmsPaymentWizard(models.TransientModel):
    _name = "hms.payment.wizard"
    _description = "Terima Pembayaran"

    bill_id = fields.Many2one("hms.bill", required=True)
    patient_id = fields.Many2one(related="bill_id.patient_id", readonly=True)
    currency_id = fields.Many2one(related="bill_id.currency_id", readonly=True)
    amount_due = fields.Monetary(related="bill_id.amount_due", readonly=True, string="Sisa Bayar")
    deposit_available = fields.Monetary("Saldo Deposit", compute="_compute_deposit")
    line_ids = fields.One2many("hms.payment.wizard.line", "wizard_id", "Rincian Pembayaran")
    amount_entered = fields.Monetary("Total Dimasukkan", compute="_compute_totals")
    amount_remaining = fields.Monetary("Kurang/Lebih", compute="_compute_totals")
    use_deposit = fields.Boolean("Potong Deposit Dulu", default=True)

    @api.depends("bill_id")
    def _compute_deposit(self):
        for wiz in self:
            deposits = self.env["hms.deposit"].search([
                ("patient_id", "=", wiz.bill_id.patient_id.id), ("state", "=", "open"),
            ])
            wiz.deposit_available = sum(deposits.mapped("balance"))

    @api.depends("line_ids.amount", "amount_due")
    def _compute_totals(self):
        for wiz in self:
            wiz.amount_entered = sum(wiz.line_ids.mapped("amount"))
            wiz.amount_remaining = wiz.amount_due - wiz.amount_entered

    def action_confirm(self):
        """Apply deposit first, then every payment line, in one transaction."""
        self.ensure_one()
        bill = self.bill_id
        if bill.state not in ("open", "paid", "closed"):
            raise UserError(
                _("Tagihan %s belum siap dibayar. Tutup pelayanan terlebih dahulu.") % bill.name
            )
        if not self.line_ids and not self.use_deposit:
            raise UserError(_("Belum ada metode pembayaran yang dimasukkan."))

        if self.use_deposit:
            deposits = self.env["hms.deposit"].search([
                ("patient_id", "=", bill.patient_id.id), ("state", "=", "open"),
            ], order="received_at")
            for deposit in deposits:
                if float_compare(bill.amount_due, 0.0, precision_digits=2) <= 0:
                    break
                deposit.apply_to_bill(bill)

        # Context (including hms_back_office) flows through to the payments.
        Payment = self.env["hms.payment"]
        for line in self.line_ids:
            if float_compare(line.amount, 0.0, precision_digits=2) <= 0:
                continue
            Payment.create({
                "bill_id": bill.id,
                "method": line.method,
                "amount": line.amount,
                "tendered": line.tendered,
                "reference": line.reference,
                "bank": line.bank,
                "approval_code": line.approval_code,
                "journal_id": line.journal_id.id,
            })
        bill._mark_paid_if_settled()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hms.bill",
            "res_id": bill.id,
            "view_mode": "form",
            "target": "current",
        }


class HmsPaymentWizardLine(models.TransientModel):
    _name = "hms.payment.wizard.line"
    _description = "Rincian Pembayaran"

    wizard_id = fields.Many2one("hms.payment.wizard", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="wizard_id.currency_id", readonly=True)
    method = fields.Selection(PAYMENT_METHODS, required=True, default="cash")
    amount = fields.Monetary("Jumlah", required=True)
    tendered = fields.Monetary("Uang Diterima")
    reference = fields.Char("Referensi")
    bank = fields.Char("Bank")
    approval_code = fields.Char("Kode Approval")
    journal_id = fields.Many2one("account.journal", "Jurnal",
                                 domain="[('type', 'in', ('bank', 'cash'))]")

    @api.onchange("method")
    def _onchange_method(self):
        """Pick a sensible journal so the cashier does not have to know accounting."""
        if not self.method:
            return
        journal_type = "cash" if self.method == "cash" else "bank"
        self.journal_id = self.env["account.journal"].search(
            [("type", "=", journal_type)], limit=1
        )
