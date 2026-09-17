# -*- coding: utf-8 -*-
"""Dunning as data, and the credit check that closes the loop."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CustomSpkFollowupLevel(models.Model):
    _name = "custom.spk.followup.level"
    _description = "Level Follow-up Penagihan"
    _order = "days_overdue asc"

    name = fields.Char(required=True)
    days_overdue = fields.Integer(
        required=True,
        help="Negative for a reminder BEFORE the due date. Sending one three days early "
        "costs nothing and prevents a whole class of 'we never received it'.",
    )
    action = fields.Selection(
        [
            ("email", "Email"),
            ("call", "Telepon"),
            ("whatsapp", "WhatsApp"),
            ("escalate", "Eskalasi ke Owner"),
        ],
        default="email", required=True,
    )
    mail_template_id = fields.Many2one("mail.template", string="Template")
    active = fields.Boolean(default=True)

    _uniq_days = models.Constraint(
        "unique(days_overdue)",
        "Two levels at the same age would both fire on the same day.",
    )


class AccountMove(models.Model):
    _inherit = "account.move"

    x_spk_followup_level_id = fields.Many2one(
        "custom.spk.followup.level", string="Level Follow-up", readonly=True, copy=False)
    x_spk_followup_date = fields.Date(string="Follow-up Terakhir", readonly=True, copy=False)

    @api.model
    def _cron_spk_followup(self):
        """Walk unpaid customer invoices and fire the level their age has reached.

        One pass a day, and a level fires once: the level is stamped on the invoice, so
        a client is not emailed twice for crossing the same threshold. The sequence ends
        at the owner rather than looping politely forever.
        """
        Level = self.env["custom.spk.followup.level"].sudo()
        levels = Level.search([], order="days_overdue desc")
        if not levels:
            return 0
        today = fields.Date.context_today(self)
        invoices = self.sudo().search([
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("payment_state", "not in", ("paid", "in_payment", "reversed")),
            ("invoice_date_due", "!=", False),
        ])
        acted = 0
        for invoice in invoices:
            age = (today - invoice.invoice_date_due).days
            # Highest threshold the invoice has reached, since levels are sorted desc.
            reached = next((lv for lv in levels if age >= lv.days_overdue), None)
            if not reached:
                continue
            if invoice.x_spk_followup_level_id == reached:
                continue
            invoice.write({
                "x_spk_followup_level_id": reached.id,
                "x_spk_followup_date": today,
            })
            if reached.action == "email" and reached.mail_template_id:
                reached.mail_template_id.sudo().send_mail(invoice.id, force_send=False)
            else:
                invoice.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("Follow-up penagihan: %(level)s", level=reached.name),
                    note=_("%(inv)s jatuh tempo %(days)s hari. Tindakan: %(action)s.",
                           inv=invoice.name or "?", days=age, action=reached.action),
                )
            acted += 1
        return acted


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_spk_overdue_amount = fields.Monetary(
        string="Piutang Jatuh Tempo",
        compute="_compute_spk_overdue",
        currency_field="currency_id",
        groups="custom_spk.group_spk_price_viewer",
    )
    x_spk_overdue_days = fields.Integer(
        string="Umur Piutang Tertua",
        compute="_compute_spk_overdue",
        groups="custom_spk.group_spk_price_viewer",
    )

    def _compute_spk_overdue(self):
        today = fields.Date.context_today(self)
        Move = self.env["account.move"].sudo()
        for rec in self:
            invoices = Move.search([
                ("partner_id", "=", rec.id),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "not in", ("paid", "in_payment", "reversed")),
                ("invoice_date_due", "<", today),
            ])
            rec.x_spk_overdue_amount = sum(invoices.mapped("amount_residual"))
            ages = [(today - inv.invoice_date_due).days for inv in invoices]
            rec.x_spk_overdue_days = max(ages) if ages else 0

    def spk_credit_warning(self):
        """A warning, not a block.

        Repeat orders arrive fast in event work, and it is easy to take a second job
        from a client who has not paid for the first. Whether to do it anyway is the
        owner's call, and they may well have a reason -- so this returns text rather
        than raising.
        """
        self.ensure_one()
        threshold = self.env.company.x_spk_credit_hold_days or 0
        if not threshold or self.x_spk_overdue_days < threshold:
            return ""
        return _(
            "%(partner)s has %(amount)s overdue, the oldest by %(days)s days. Taking "
            "another job adds exposure to a client who has not settled the last one.",
            partner=self.display_name,
            amount=self.x_spk_overdue_amount,
            days=self.x_spk_overdue_days,
        )
