# -*- coding: utf-8 -*-
"""How a job bills, and the reminder for work finished but never invoiced."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PRICE_GROUP = "custom_spk.group_spk_price_viewer"

MODES = [
    ("single", "1 SPK = 1 Invoice"),
    ("per_delivery", "1 Invoice per Pengiriman"),
    ("milestone", "Per Termin"),
]


class CustomSpkBillingPlan(models.Model):
    _name = "custom.spk.billing.plan"
    _description = "Rencana Penagihan per SPK"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="cascade", tracking=True)
    partner_id = fields.Many2one(related="spk_id.partner_id", store=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=PRICE_GROUP)
    mode = fields.Selection(
        MODES, default="single", required=True, tracking=True,
        help="A property of the job, not a company setting: the same contractor bills "
        "all three ways in the same month.",
    )
    contract_amount = fields.Monetary(
        string="Nilai SPK", currency_field="currency_id", groups=PRICE_GROUP)
    milestone_ids = fields.One2many("custom.spk.billing.milestone", "plan_id")
    milestone_total_pct = fields.Float(
        compute="_compute_milestone_total", store=True, groups=PRICE_GROUP)
    block_production_until_dp = fields.Boolean(
        string="Tahan Produksi Sampai DP Masuk",
        default=True,
        help="Buying a client's material before they have paid anything is how a "
        "contractor finances someone else's event. Overridable, because sometimes the "
        "relationship earns it.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("active", "Aktif"), ("closed", "Closed")],
        default="draft", required=True, tracking=True,
    )

    _uniq_spk = models.Constraint(
        "unique(spk_id)", "One billing plan per job; two would disagree about what is due.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "custom.spk.billing.plan") or _("New")
        return super().create(vals_list)

    @api.depends("milestone_ids.percentage")
    def _compute_milestone_total(self):
        for rec in self:
            rec.milestone_total_pct = sum(rec.milestone_ids.mapped("percentage"))

    @api.constrains("mode", "milestone_ids", "milestone_total_pct")
    def _check_milestones(self):
        for rec in self:
            if rec.mode != "milestone":
                continue
            if not rec.milestone_ids:
                raise ValidationError(
                    _("%(name)s bills by milestone but has none defined.", name=rec.name))
            if abs(rec.milestone_total_pct - 100.0) > 0.01:
                raise ValidationError(
                    _("Milestones total %(total).2f%%, not 100%%. A plan that does not add "
                      "up either leaves money uninvoiced or bills it twice.",
                      total=rec.milestone_total_pct)
                )

    def action_activate(self):
        for rec in self:
            rec.state = "active"
        return True

    def can_release_to_workshop(self):
        """Whether production may start, given what has been paid.

        Returns a (bool, reason) pair rather than raising, so the caller decides
        whether this is a block or a warning. The default is to hold: buying material
        before any money has arrived means financing the client's event.
        """
        self.ensure_one()
        if not self.block_production_until_dp:
            return True, ""
        dp = self.milestone_ids.filtered(lambda m: m.is_down_payment)
        if not dp:
            return True, ""
        unpaid = dp.filtered(lambda m: not m.is_paid)
        if unpaid:
            return False, _(
                "Down payment for %(spk)s has not arrived. Releasing material now means "
                "financing the client's event out of working capital.",
                spk=self.spk_id.name,
            )
        return True, ""

    @api.model
    def _cron_warn_uninvoiced(self):
        """Work finished, handover signed, nothing billed.

        This is the reminder that recovers the most money and the one usually left out,
        because unbilled work does not appear in a receivables report -- there is no
        receivable, the amount is simply absent. Three days is long enough to be a real
        omission rather than paperwork in flight.
        """
        cutoff = fields.Date.subtract(fields.Date.context_today(self), days=3)
        Delivery = self.env["custom.spk.delivery"].sudo()
        handed_over = Delivery.search([
            ("state", "in", ("bast_signed", "dismantled")),
            ("bast_signed", "=", True),
        ])
        flagged = self.env["custom.spk.delivery"]
        for delivery in handed_over:
            bast_date = delivery.bast_id.party_to_signed_at
            if bast_date and bast_date.date() > cutoff:
                continue
            invoices = self.env["account.move"].sudo().search_count([
                ("move_type", "=", "out_invoice"),
                ("state", "!=", "cancel"),
                ("invoice_origin", "like", delivery.spk_id.name),
            ])
            if invoices:
                continue
            delivery.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Pekerjaan selesai, belum ditagih"),
                note=_("%(name)s sudah BAST dan belum ada invoice. Pekerjaan yang tidak "
                       "ditagih tidak muncul di laporan piutang — ia cuma hilang.",
                       name=delivery.name),
            )
            flagged |= delivery
        return len(flagged)


class CustomSpkBillingMilestone(models.Model):
    _name = "custom.spk.billing.milestone"
    _description = "Termin Penagihan"
    _order = "plan_id, sequence, id"

    plan_id = fields.Many2one(
        "custom.spk.billing.plan", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="plan_id.currency_id", groups=PRICE_GROUP)
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    percentage = fields.Float(string="%", required=True)
    amount = fields.Monetary(
        compute="_compute_amount", store=True, currency_field="currency_id", groups=PRICE_GROUP)
    is_down_payment = fields.Boolean(
        string="Uang Muka",
        help="Marks the milestone that gates production. Usually the first, but not "
        "always: some clients pay a deposit and a separate mobilisation fee.",
    )
    trigger = fields.Selection(
        [
            ("on_confirm", "Saat SPK disetujui"),
            ("on_handover", "Setelah BAST"),
            ("after_event", "Setelah event selesai"),
        ],
        default="on_confirm", required=True,
    )
    invoice_id = fields.Many2one("account.move", readonly=True, copy=False)
    is_paid = fields.Boolean(compute="_compute_is_paid", store=True)

    @api.depends("percentage", "plan_id.contract_amount")
    def _compute_amount(self):
        for rec in self:
            rec.amount = (rec.plan_id.contract_amount or 0.0) * ((rec.percentage or 0.0) / 100.0)

    @api.depends("invoice_id.payment_state", "invoice_id.state")
    def _compute_is_paid(self):
        for rec in self:
            rec.is_paid = bool(
                rec.invoice_id
                and rec.invoice_id.state == "posted"
                and rec.invoice_id.payment_state in ("paid", "in_payment", "reversed")
            )

    @api.constrains("percentage")
    def _check_percentage(self):
        for rec in self:
            if not 0.0 < rec.percentage <= 100.0:
                raise ValidationError(
                    _("A milestone of %(pct)s%% is not a share of the contract.",
                      pct=rec.percentage)
                )
