# -*- coding: utf-8 -*-
"""Supervisor authorisations for discounts, voids and refunds."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsBillingAuthorization(models.Model):
    _name = "hms.billing.authorization"
    _description = "Otorisasi Kasir"
    _order = "id desc"

    bill_id = fields.Many2one("hms.bill", required=True, ondelete="cascade", index=True)
    action = fields.Selection(
        [("discount", "Diskon"), ("void_line", "Batal Baris"), ("void_payment", "Batal Pembayaran"),
         ("refund", "Refund"), ("delete_deposit", "Hapus Deposit"), ("reopen", "Buka Tagihan")],
        required=True,
    )
    amount = fields.Monetary("Nilai", currency_field="currency_id")
    percent = fields.Float("Persentase")
    currency_id = fields.Many2one(related="bill_id.currency_id", readonly=True)
    reason = fields.Text("Alasan", required=True)
    requested_by_id = fields.Many2one("res.users", "Diminta Oleh", required=True,
                                      default=lambda s: s.env.user)
    authorized_by_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True)
    authorized_at = fields.Datetime(readonly=True)
    state = fields.Selection(
        [("pending", "Menunggu"), ("approved", "Disetujui"), ("rejected", "Ditolak")],
        default="pending", required=True,
    )

    def action_approve(self):
        """Approval must come from a supervisor other than the requester."""
        for auth in self:
            if not self.env.user.has_group("custom_hms_base.group_hms_billing_supervisor"):
                raise UserError(
                    _("Hanya supervisor kasir yang dapat menyetujui otorisasi.")
                )
            if auth.requested_by_id == self.env.user:
                raise UserError(
                    _("Otorisasi harus disetujui oleh pengguna lain — persetujuan "
                      "sendiri bukan kontrol.")
                )
            auth.write({
                "state": "approved",
                "authorized_by_id": self.env.uid,
                "authorized_at": fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        self.write({"state": "rejected", "authorized_by_id": self.env.uid,
                    "authorized_at": fields.Datetime.now()})
        return True


class HmsBill(models.Model):
    _inherit = "hms.bill"

    def request_discount_authorization(self, percent, reason):
        """Record a pending request for a discount above the limit.

        A separate call from apply_discount on purpose. Odoo aborts the
        transaction when a UserError propagates, so a method that creates the
        request and *then* raises would leave nothing behind — the supervisor
        would never see a queue, and the cashier would be told to wait for an
        approval that was never asked for.
        """
        self.ensure_one()
        if not reason:
            raise UserError(_("Alasan permintaan diskon wajib diisi."))
        return self.env["hms.billing.authorization"].create({
            "bill_id": self.id,
            "action": "discount",
            "percent": percent,
            "amount": self.amount_total * percent / 100.0,
            "reason": reason,
        })

    def discount_needs_authorization(self, percent):
        """True when this percentage is above the configured limit."""
        self.ensure_one()
        threshold = self.env["hms.settings"].get_settings().discount_auth_percent or 0.0
        return percent > threshold

    def apply_discount(self, percent, reason, line_ids=None):
        """Apply a discount, refusing anything not covered by an approval.

        Never creates anything before refusing: see
        request_discount_authorization for why.
        """
        self.ensure_one()
        if self.state == "closed":
            raise UserError(_("Tagihan sudah ditutup; diskon tidak dapat diubah."))
        if self.discount_needs_authorization(percent):
            approved = self.authorization_ids.filtered(
                lambda a: a.action == "discount" and a.state == "approved"
                and a.percent >= percent
            )
            if not approved:
                threshold = self.env["hms.settings"].get_settings().discount_auth_percent
                raise UserError(
                    _("Diskon %(p).1f%% melewati batas %(t).1f%% dan belum memiliki "
                      "persetujuan supervisor kasir. Ajukan otorisasi lebih dulu lewat "
                      "tombol \"Minta Otorisasi Diskon\".")
                    % {"p": percent, "t": threshold}
                )
        lines = self.line_ids.browse(line_ids) if line_ids else self.line_ids.filtered(
            lambda l: l.state == "confirmed"
        )
        lines.write({"discount_percent": percent})
        self.message_post(
            body=_("Diskon %(p).1f%% diterapkan. Alasan: %(r)s") % {"p": percent, "r": reason}
        )
        return True
