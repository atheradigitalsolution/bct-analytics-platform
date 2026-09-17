# -*- coding: utf-8 -*-
"""The monthly run that stops permanent labour vanishing from job cost.

A daily worker's wage reaches COGS the moment their shift is logged. A permanent
worker's salary does not, and if nothing charges it, every job they touched looks
cheaper than it was -- most of all the jobs they touched most.

So at period close this divides the permanent *direct* payroll by the shifts those
people actually worked, and books the result to each SPK in proportion to the shifts
it received. Indirect staff are excluded: a supervisor's cost is overhead no matter
how many workshops they walked through.

Why shifts and not direct cost: spreading the salary across each job's direct cost
is one query cheaper and systematically wrong in the same direction -- it flatters
jobs staffed by permanent workers and penalises jobs that leaned on daily labour.
Recording the shift costs the supervisor nothing extra, because the box was already
ticked for attendance.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomSpkLaborAllocation(models.Model):
    _name = "custom.spk.labor.allocation"
    _description = "Alokasi Gaji Pekerja Tetap ke SPK"
    _inherit = ["mail.thread"]
    _order = "period_year desc, period_month desc, id desc"

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda s: _("New"))
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    period_year = fields.Integer(required=True, default=lambda s: fields.Date.today().year)
    period_month = fields.Selection(
        [(str(i), "%02d" % i) for i in range(1, 13)],
        required=True, default=lambda s: str(fields.Date.today().month),
    )
    state = fields.Selection(
        [("draft", "Draft"), ("computed", "Computed"), ("posted", "Posted")],
        default="draft", required=True, tracking=True,
    )

    payroll_total = fields.Monetary(
        string="Payroll Pekerja Tetap Direct",
        currency_field="currency_id", readonly=True,
        groups="custom_spk.group_spk_cost_viewer",
    )
    total_shifts = fields.Float(string="Total Shift", readonly=True)
    rate_per_shift = fields.Monetary(
        string="Tarif Alokasi / Shift",
        currency_field="currency_id", readonly=True,
        groups="custom_spk.group_spk_cost_viewer",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
        groups="custom_spk.group_spk_cost_viewer",
    )
    line_ids = fields.One2many("custom.spk.labor.allocation.line", "allocation_id")

    _uniq_period = models.Constraint(
        "unique(company_id, period_year, period_month)",
        "One allocation per company per period; a second would double-charge.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "custom.spk.labor.allocation") or _("New")
        return super().create(vals_list)

    def _period_bounds(self):
        self.ensure_one()
        start = fields.Date.to_date("%04d-%02d-01" % (self.period_year, int(self.period_month)))
        month = int(self.period_month)
        if month == 12:
            end = fields.Date.to_date("%04d-01-01" % (self.period_year + 1))
        else:
            end = fields.Date.to_date("%04d-%02d-01" % (self.period_year, month + 1))
        return start, end

    def action_compute(self):
        for rec in self:
            rec.line_ids.unlink()
            start, end = rec._period_bounds()

            # The driver: shifts worked by permanent DIRECT staff, already recorded as
            # part of attendance. is_allocation_basis carries exactly that meaning.
            logs = self.env["custom.spk.work.log"].sudo().search([
                ("date", ">=", start),
                ("date", "<", end),
                ("is_allocation_basis", "=", True),
                ("attendance_id.state", "=", "approved"),
            ])
            total_shifts = sum(logs.mapped("shift_portion"))

            employees = logs.mapped("employee_id")
            payroll_total = 0.0
            if employees:
                slips = self.env["hr.payslip"].sudo().search([
                    ("employee_id", "in", employees.ids),
                    ("period_year", "=", rec.period_year),
                    ("period_month", "=", rec.period_month),
                    ("state", "in", ("approved", "paid")),
                    ("is_thr", "=", False),
                ])
                payroll_total = sum(
                    (s.gross_salary or 0.0) + (s.tunjangan_jabatan or 0.0)
                    + (s.tunjangan_lain or 0.0) for s in slips
                )

            if total_shifts <= 0:
                raise UserError(
                    _("No approved shifts from permanent direct staff in %(period)s, so "
                      "there is nothing to allocate across. Approve the attendance for "
                      "that month first.", period="%s-%s" % (rec.period_year, rec.period_month))
                )
            if payroll_total <= 0:
                raise UserError(
                    _("Shifts were worked in %(period)s but no approved payslip covers "
                      "them, so the amount to allocate is unknown. Run payroll for that "
                      "month before allocating — allocating zero would silently declare "
                      "those jobs free.",
                      period="%s-%s" % (rec.period_year, rec.period_month))
                )

            rate = payroll_total / total_shifts
            by_spk = {}
            for log in logs.filtered(lambda l: l.target == "spk" and l.spk_id):
                by_spk.setdefault(log.spk_id, 0.0)
                by_spk[log.spk_id] += log.shift_portion

            rec.write({
                "payroll_total": payroll_total,
                "total_shifts": total_shifts,
                "rate_per_shift": rate,
                "state": "computed",
                "line_ids": [
                    (0, 0, {"spk_id": spk.id, "shifts": shifts, "amount": shifts * rate})
                    for spk, shifts in by_spk.items()
                ],
            })
        return True

    def action_post(self):
        """Book the allocation as analytic lines, one per SPK.

        Posted rather than computed-and-read, because a margin report that reads a
        wizard's output is a report nobody can reproduce six months later.
        """
        AnalyticLine = self.env["account.analytic.line"].sudo()
        for rec in self:
            if rec.state != "computed":
                raise UserError(_("Compute the allocation before posting it."))
            start, _end = rec._period_bounds()
            for line in rec.line_ids:
                if not line.spk_id.analytic_account_id:
                    raise UserError(
                        _("%(spk)s has no analytic account, so its allocation has "
                          "nowhere to go.", spk=line.spk_id.name)
                    )
                AnalyticLine.create({
                    "name": _("Alokasi gaji pekerja tetap %(period)s (%(shifts).2f shift)",
                              period="%s-%s" % (rec.period_year, rec.period_month),
                              shifts=line.shifts),
                    "date": start,
                    "account_id": line.spk_id.analytic_account_id.id,
                    "amount": -abs(line.amount),
                    "company_id": rec.company_id.id,
                })
            rec.state = "posted"
        return True


class CustomSpkLaborAllocationLine(models.Model):
    _name = "custom.spk.labor.allocation.line"
    _description = "Baris Alokasi Gaji per SPK"
    _order = "amount desc"

    allocation_id = fields.Many2one(
        "custom.spk.labor.allocation", required=True, ondelete="cascade")
    spk_id = fields.Many2one("custom.spk", required=True, ondelete="restrict")
    shifts = fields.Float(string="Shift", digits=(10, 3))
    amount = fields.Monetary(
        currency_field="currency_id", groups="custom_spk.group_spk_cost_viewer")
    currency_id = fields.Many2one(
        related="allocation_id.currency_id", groups="custom_spk.group_spk_cost_viewer")
