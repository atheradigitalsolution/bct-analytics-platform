# -*- coding: utf-8 -*-
"""Layer 1: was this person here. Drives pay, not cost."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ATTENDANCE_STATUS = [
    ("hadir", "Hadir"),
    ("izin", "Izin"),
    ("sakit", "Sakit"),
    ("alpha", "Alpha"),
    ("libur", "Libur"),
]

# Only a shift actually worked can be split across jobs.
WORKED = "hadir"


class CustomSpkAttendance(models.Model):
    _name = "custom.spk.attendance"
    _description = "Absensi Shift"
    _inherit = ["pdp.audited.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "date desc, employee_id"

    employee_id = fields.Many2one("hr.employee", required=True, index=True, tracking=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True, tracking=True)
    shift_id = fields.Many2one("custom.spk.shift", required=True, index=True, tracking=True)
    supervisor_id = fields.Many2one(
        "res.users", string="Dicatat oleh", default=lambda self: self.env.user,
        help="Who ticked the box. With one roving supervisor this is nearly always the "
        "same person, which is exactly why it is recorded rather than assumed.",
    )
    attendance_status = fields.Selection(
        ATTENDANCE_STATUS, default=WORKED, required=True, tracking=True)
    overtime_hours = fields.Float(string="Lembur (jam)", default=0.0)

    # Derived from the payroll classification, never entered twice.
    is_daily = fields.Boolean(related="employee_id.x_spk_is_daily", store=True, index=True)
    labor_category = fields.Selection(
        related="employee_id.x_spk_labor_category", store=True, index=True)

    work_log_ids = fields.One2many("custom.spk.work.log", "attendance_id", string="Work Log")
    portion_total = fields.Float(
        string="Total Porsi", compute="_compute_portion_total", store=True,
        help="Must reach exactly 1.0 before a worked shift can be approved. Anything "
        "less is labour cost that never lands on a job.",
    )

    shift_cost = fields.Monetary(
        string="Biaya Shift",
        currency_field="currency_id",
        compute="_compute_shift_cost",
        store=True,
        groups="custom_spk.group_spk_cost_viewer",
        help="Filled for daily workers only. A permanent employee's shift carries no "
        "money here; it is charged by the monthly allocation instead.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id,
        groups="custom_spk.group_spk_cost_viewer",
    )

    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved")],
        default="draft", required=True, tracking=True, index=True,
    )

    _uniq_employee_shift = models.Constraint(
        "unique(employee_id, date, shift_id)",
        "One attendance per person per shift per day.",
    )

    @api.depends("employee_id", "date", "shift_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s / %s / %s" % (
                rec.employee_id.name or "?",
                rec.date or "?",
                rec.shift_id.code or rec.shift_id.name or "?",
            )

    @api.depends("work_log_ids.shift_portion")
    def _compute_portion_total(self):
        for rec in self:
            rec.portion_total = sum(rec.work_log_ids.mapped("shift_portion"))

    @api.depends("is_daily", "attendance_status", "shift_id.rate_multiplier",
                 "employee_id.x_spk_shift_rate")
    def _compute_shift_cost(self):
        for rec in self:
            if not rec.is_daily or rec.attendance_status != WORKED:
                rec.shift_cost = 0.0
                continue
            rec.shift_cost = (
                (rec.employee_id.x_spk_shift_rate or 0.0)
                * (rec.shift_id.rate_multiplier or 1.0)
            )

    @api.constrains("overtime_hours")
    def _check_overtime(self):
        for rec in self:
            if rec.overtime_hours < 0:
                raise ValidationError(_("Overtime cannot be negative."))

    def action_submit(self):
        self.write({"state": "submitted"})
        return True

    def action_approve(self):
        """The gate that keeps labour cost from leaking out of the system.

        A daily worker's wage is real money leaving the company this week. If the
        shift is not mapped to something, that money is spent and no job carries it,
        and nobody finds out until the margin report disagrees with the bank. So the
        approval refuses.

        A permanent worker's shift is allowed through unmapped: their pay does not
        depend on it, and the monthly allocation can only use what it is given. It is
        still worth mapping, and the daily reminder cron says so.
        """
        for rec in self:
            if rec.attendance_status != WORKED:
                rec.state = "approved"
                continue
            if rec.is_daily and float_is_zero_total(rec.portion_total):
                raise UserError(
                    _("%(who)s worked shift %(shift)s on %(date)s and is paid per shift, "
                      "so the shift has to land on something. Add a work log before "
                      "approving — an SPK, or idle/internal work if there was nothing "
                      "to build.",
                      who=rec.employee_id.name or "?",
                      shift=rec.shift_id.code or rec.shift_id.name or "?",
                      date=rec.date or "?")
                )
            if rec.work_log_ids and abs(rec.portion_total - 1.0) > 0.001:
                raise UserError(
                    _("Work log portions for %(who)s on %(date)s total %(total).3f, not "
                      "1.0. A shift cannot be more or less than a shift.",
                      who=rec.employee_id.name or "?", date=rec.date or "?",
                      total=rec.portion_total)
                )
            rec.state = "approved"
        return True

    @api.model
    def _cron_warn_unmapped(self):
        """Daily nudge on paid shifts that have not landed anywhere.

        Runs daily and not weekly on purpose: daily workers are paid weekly, so a
        shift found on Friday is a correction, and one found the next Monday is a
        write-off.
        """
        unmapped = self.search([
            ("is_daily", "=", True),
            ("attendance_status", "=", WORKED),
            ("state", "!=", "approved"),
            ("work_log_ids", "=", False),
        ])
        for rec in unmapped:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=(rec.supervisor_id or self.env.user).id,
                summary=_("Shift belum di-mapping ke SPK"),
                note=_("%(who)s, %(date)s. Upah sudah jalan; biayanya belum mendarat di mana pun.",
                       who=rec.employee_id.name or "?", date=rec.date or "?"),
            )
        return len(unmapped)


def float_is_zero_total(value: float) -> bool:
    """Portions are entered by hand in tenths; 1e-3 is well inside the noise."""
    return abs(value) < 0.001
