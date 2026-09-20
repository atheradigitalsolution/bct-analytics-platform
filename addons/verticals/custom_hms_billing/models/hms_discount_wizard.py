# -*- coding: utf-8 -*-
"""Discount request / application screen for the cashier."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsDiscountWizard(models.TransientModel):
    _name = "hms.discount.wizard"
    _description = "Diskon Tagihan"

    bill_id = fields.Many2one("hms.bill", required=True)
    currency_id = fields.Many2one(related="bill_id.currency_id", readonly=True)
    amount_total = fields.Monetary(related="bill_id.amount_total", readonly=True)
    percent = fields.Float("Diskon (%)", required=True)
    reason = fields.Text("Alasan", required=True)
    needs_authorization = fields.Boolean(compute="_compute_needs_authorization")
    threshold = fields.Float("Batas Tanpa Otorisasi", compute="_compute_needs_authorization")
    has_approval = fields.Boolean(compute="_compute_needs_authorization")

    @api.depends("percent", "bill_id")
    def _compute_needs_authorization(self):
        for wiz in self:
            settings = self.env["hms.settings"].get_settings()
            wiz.threshold = settings.discount_auth_percent or 0.0
            wiz.needs_authorization = wiz.bill_id and wiz.bill_id.discount_needs_authorization(
                wiz.percent
            )
            wiz.has_approval = bool(wiz.bill_id.authorization_ids.filtered(
                lambda a: a.action == "discount" and a.state == "approved"
                and a.percent >= wiz.percent
            ))

    def action_request(self):
        """Ask a supervisor. Deliberately a plain return, never an exception."""
        self.ensure_one()
        request = self.bill_id.request_discount_authorization(self.percent, self.reason)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Permintaan otorisasi dibuat"),
                "message": _("Otorisasi #%(id)s menunggu persetujuan supervisor kasir.")
                % {"id": request.id},
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_apply(self):
        self.ensure_one()
        self.bill_id.apply_discount(self.percent, self.reason)
        return {"type": "ir.actions.act_window_close"}
