# -*- coding: utf-8 -*-
"""Layer 2: which job the time landed on. Drives cost, not pay."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

TARGETS = [
    ("spk", "SPK"),
    ("idle", "Idle Workshop"),
    ("internal", "Pekerjaan Internal"),
]


class CustomSpkWorkLog(models.Model):
    _name = "custom.spk.work.log"
    _description = "Work Log per SPK"
    _order = "date desc, id desc"

    attendance_id = fields.Many2one(
        "custom.spk.attendance", required=True, ondelete="cascade", index=True)

    # Copied down from the parent and stored, because every report groups by these and
    # walking up the attendance for each row turns a month's costing into a join storm.
    employee_id = fields.Many2one(
        related="attendance_id.employee_id", store=True, index=True)
    date = fields.Date(related="attendance_id.date", store=True, index=True)
    shift_id = fields.Many2one(related="attendance_id.shift_id", store=True)
    is_daily = fields.Boolean(related="attendance_id.is_daily", store=True, index=True)
    labor_category = fields.Selection(
        related="attendance_id.labor_category", store=True, index=True)

    target = fields.Selection(
        TARGETS, required=True, default="spk",
        help="What absorbed the shift. Idle and internal exist so that a paid shift "
        "with no job never has to be pushed onto one that did not incur it.",
    )
    spk_id = fields.Many2one("custom.spk", string="SPK", index=True, ondelete="restrict")
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        compute="_compute_analytic_account",
        store=True,
        index=True,
        help="Resolved from the target, never picked by hand: a work log that points "
        "somewhere other than its own SPK is a costing error waiting to be believed.",
    )

    shift_portion = fields.Float(
        string="Porsi Shift", default=1.0, required=True, digits=(6, 3),
        help="1.0 is the whole shift. Split only when the worker genuinely moved "
        "between jobs; the parent refuses to approve unless the parts make a whole.",
    )

    labor_cost = fields.Monetary(
        string="Biaya Tenaga Kerja",
        currency_field="currency_id",
        compute="_compute_labor_cost",
        store=True,
        groups="custom_spk.group_spk_cost_viewer",
        help="Actual money for a daily worker. Zero for a permanent one, who is "
        "charged by the monthly allocation instead.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
        groups="custom_spk.group_spk_cost_viewer",
    )
    is_allocation_basis = fields.Boolean(
        compute="_compute_labor_cost",
        store=True,
        index=True,
        help="True for permanent direct labour. Carries no money, but is the driver "
        "the monthly allocation divides the payroll across.",
    )

    @api.depends("target", "spk_id.analytic_account_id")
    def _compute_analytic_account(self):
        for rec in self:
            company = rec.company_resolved()
            if rec.target == "spk":
                rec.analytic_account_id = rec.spk_id.analytic_account_id
            elif rec.target == "idle":
                rec.analytic_account_id = company.x_spk_idle_analytic_id
            else:
                rec.analytic_account_id = company.x_spk_internal_analytic_id

    def company_resolved(self):
        """The employee's company where known, the active one otherwise."""
        self.ensure_one()
        return self.employee_id.company_id or self.env.company

    @api.depends("is_daily", "labor_category", "shift_portion",
                 "attendance_id.shift_cost")
    def _compute_labor_cost(self):
        for rec in self:
            if rec.is_daily:
                rec.labor_cost = (rec.attendance_id.shift_cost or 0.0) * (rec.shift_portion or 0.0)
                rec.is_allocation_basis = False
            else:
                # A permanent worker's shift is recorded, not priced. Pricing it here
                # would double-charge once the monthly allocation runs.
                rec.labor_cost = 0.0
                rec.is_allocation_basis = rec.labor_category == "direct"

    @api.constrains("shift_portion")
    def _check_portion(self):
        for rec in self:
            if not 0.0 < rec.shift_portion <= 1.0:
                raise ValidationError(
                    _("A shift portion is more than nothing and at most one whole "
                      "shift; got %(value)s.", value=rec.shift_portion)
                )

    @api.constrains("target", "spk_id", "analytic_account_id")
    def _check_target_resolves(self):
        for rec in self:
            if rec.target == "spk" and not rec.spk_id:
                raise ValidationError(_("Pick the SPK this shift worked on."))
            if not rec.analytic_account_id:
                if rec.target == "spk":
                    raise ValidationError(
                        _("%(spk)s has no analytic account yet. Approve the SPK first — "
                          "that is what creates somewhere for its cost to land.",
                          spk=rec.spk_id.name or "?")
                    )
                raise ValidationError(
                    _("No analytic account is configured for %(target)s. Set it in "
                      "Settings before recording shifts against it.", target=rec.target)
                )
