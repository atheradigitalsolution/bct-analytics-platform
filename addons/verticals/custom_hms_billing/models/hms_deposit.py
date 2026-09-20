# -*- coding: utf-8 -*-
"""Inpatient deposits and payments."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare

PAYMENT_METHODS = [
    ("cash", "Tunai"),
    ("edc_debit", "EDC Debit"),
    ("edc_credit", "EDC Kredit"),
    ("transfer", "Transfer Bank"),
    ("qris", "QRIS"),
    ("deposit", "Potong Deposit"),
    ("voucher", "Voucher / Jaminan Perusahaan"),
    ("receivable", "Piutang Pasien"),
]


class HmsDeposit(models.Model):
    _name = "hms.deposit"
    _description = "Deposit Pasien"
    _order = "id desc"

    name = fields.Char("No. Bukti", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"))
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, index=True)
    bill_id = fields.Many2one("hms.bill", "Tagihan", index=True, ondelete="restrict")
    admission_id = fields.Many2one("hms.admission", "Admisi", index=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True, readonly=True,
    )
    amount = fields.Monetary("Jumlah Deposit", required=True)
    used_amount = fields.Monetary("Terpakai", default=0.0, readonly=True)
    refunded_amount = fields.Monetary("Dikembalikan", default=0.0, readonly=True)
    balance = fields.Monetary("Saldo", compute="_compute_balance", store=True)
    method = fields.Selection(PAYMENT_METHODS, "Metode", required=True, default="cash")
    reference = fields.Char("Referensi")
    received_at = fields.Datetime("Diterima", default=fields.Datetime.now, required=True)
    received_by_id = fields.Many2one("res.users", "Diterima Oleh", default=lambda s: s.env.user)
    state = fields.Selection(
        [("open", "Aktif"), ("used", "Habis Terpakai"), ("refunded", "Dikembalikan"),
         ("cancelled", "Dibatalkan")],
        default="open", required=True,
    )
    note = fields.Char()

    _name_uniq = models.Constraint("unique(name)", "Nomor bukti deposit harus unik.")

    @api.depends("amount", "used_amount", "refunded_amount")
    def _compute_balance(self):
        for dep in self:
            dep.balance = dep.amount - dep.used_amount - dep.refunded_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.deposit") or "/"
        deposits = super().create(vals_list)
        for dep in deposits:
            dep.env["hms.event"].emit("deposit.received", {
                "deposit_id": dep.id, "patient_id": dep.patient_id.id, "amount": dep.amount,
            })
        return deposits

    def apply_to_bill(self, bill, amount=None):
        """Consume deposit against an outstanding bill."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Deposit %s tidak aktif.") % self.name)
        take = amount if amount is not None else min(self.balance, bill.amount_due)
        if float_compare(take, self.balance, precision_digits=2) > 0:
            raise UserError(
                _("Saldo deposit %(n)s hanya %(bal)s, tidak cukup untuk %(take)s.")
                % {"n": self.name, "bal": self.balance, "take": take}
            )
        self.write({
            "used_amount": self.used_amount + take,
            "bill_id": bill.id,
        })
        if float_compare(self.balance, 0.0, precision_digits=2) <= 0:
            self.write({"state": "used"})
        bill._mark_paid_if_settled()
        return take

    def action_refund(self):
        for dep in self:
            if float_compare(dep.balance, 0.0, precision_digits=2) <= 0:
                raise UserError(_("Deposit %s tidak memiliki sisa untuk dikembalikan.") % dep.name)
            dep.write({
                "refunded_amount": dep.refunded_amount + dep.balance,
                "state": "refunded",
            })
        return True


class HmsPayment(models.Model):
    _name = "hms.payment"
    _description = "Pembayaran Tagihan"
    _order = "id desc"

    name = fields.Char("No. Kwitansi", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"))
    bill_id = fields.Many2one("hms.bill", required=True, ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="bill_id.patient_id", store=True, index=True)
    currency_id = fields.Many2one(related="bill_id.currency_id", store=True, readonly=True)
    method = fields.Selection(PAYMENT_METHODS, "Metode", required=True, default="cash")
    amount = fields.Monetary("Jumlah", required=True)
    tendered = fields.Monetary("Uang Diterima")
    change = fields.Monetary("Kembalian", compute="_compute_change", store=True)
    reference = fields.Char("Referensi / No. Approval")
    bank = fields.Char("Bank")
    approval_code = fields.Char("Kode Approval EDC")
    mdr_amount = fields.Monetary("Biaya MDR")
    journal_id = fields.Many2one("account.journal", "Jurnal", domain="[('type', 'in', ('bank', 'cash'))]")
    account_payment_id = fields.Many2one("account.payment", "Pembayaran Akuntansi", readonly=True)
    paid_at = fields.Datetime("Waktu Bayar", default=fields.Datetime.now, required=True)
    cashier_id = fields.Many2one("res.users", "Kasir", default=lambda s: s.env.user)
    state = fields.Selection(
        [("draft", "Draf"), ("done", "Selesai"), ("void", "Dibatalkan")],
        default="done", required=True, index=True,
    )
    void_reason = fields.Char("Alasan Pembatalan")
    printed_count = fields.Integer("Jumlah Cetak", default=0)

    _name_uniq = models.Constraint("unique(name)", "Nomor kwitansi harus unik.")

    @api.depends("tendered", "amount")
    def _compute_change(self):
        for pay in self:
            pay.change = max((pay.tendered or 0.0) - pay.amount, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.payment") or "/"
        payments = super().create(vals_list)
        for pay in payments:
            pay._post_to_accounting()
            pay.bill_id._mark_paid_if_settled()
            pay.env["hms.event"].emit("payment.done", {
                "payment_id": pay.id, "bill_id": pay.bill_id.id,
                "amount": pay.amount, "method": pay.method,
            })
        return payments

    def _post_to_accounting(self):
        """Mirror the payment into account.payment on the method's journal.

        Only once the bill has an invoice: a payment against a bill that has
        not been closed has nothing to reconcile against, and creating an
        orphan account.payment is worse than creating none.
        """
        self.ensure_one()
        if self.method in ("deposit", "receivable") or not self.journal_id:
            return False
        if not self.bill_id.move_ids.filtered(lambda m: m.state == "posted"):
            return False
        payment = self.env["account.payment"].create({
            "payment_type": "inbound",
            "partner_type": "customer",
            "partner_id": self.patient_id.partner_id.id,
            "amount": self.amount,
            "journal_id": self.journal_id.id,
            "memo": f"{self.bill_id.name} / {self.name}",
        })
        payment.action_post()
        self.write({"account_payment_id": payment.id})
        return payment

    def action_void(self):
        for pay in self:
            if pay.state == "void":
                raise UserError(_("Pembayaran sudah dibatalkan."))
            if not pay.void_reason:
                raise UserError(_("Alasan pembatalan pembayaran wajib dicatat."))
            pay.write({"state": "void"})
            pay.env["hms.event"].emit("payment.void", {
                "payment_id": pay.id, "bill_id": pay.bill_id.id,
            })
        return True
