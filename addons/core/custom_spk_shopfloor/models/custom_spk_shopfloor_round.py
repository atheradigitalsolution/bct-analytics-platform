# -*- coding: utf-8 -*-
"""A round of the workshops: the unit the supervisor actually works in."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CustomSpkShopfloorRound(models.Model):
    """One walk of the workshops on one shift.

    The model exists because the supervisor's unit of work is a round, not a person. It
    holds what was entered together so a half-finished round is visible as such, rather
    than appearing as a scatter of attendance records that may or may not be complete.
    """

    _name = "custom.spk.shopfloor.round"
    _description = "Ronde Shopfloor"
    _inherit = ["mail.thread"]
    _order = "date desc, shift_id"

    name = fields.Char(compute="_compute_name", store=True)
    date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    shift_id = fields.Many2one("custom.spk.shift", required=True, index=True)
    supervisor_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user)
    attendance_ids = fields.One2many(
        "custom.spk.attendance", "shopfloor_round_id", string="Absensi")
    attendance_count = fields.Integer(compute="_compute_counts", store=True)
    unmapped_count = fields.Integer(
        compute="_compute_counts", store=True,
        help="Paid shifts in this round that have not landed on anything yet. The number "
        "the supervisor has to get to zero before the week closes.",
    )
    state = fields.Selection(
        [("open", "Berjalan"), ("submitted", "Submitted"), ("approved", "Approved")],
        default="open", required=True, tracking=True,
    )

    _uniq_round = models.Constraint(
        "unique(date, shift_id, supervisor_id)",
        "One round per supervisor per shift per day.",
    )

    @api.depends("date", "shift_id")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s / %s" % (
                rec.date or "?", rec.shift_id.code or rec.shift_id.name or "?")

    @api.depends("attendance_ids", "attendance_ids.portion_total",
                 "attendance_ids.is_daily", "attendance_ids.attendance_status")
    def _compute_counts(self):
        for rec in self:
            rec.attendance_count = len(rec.attendance_ids)
            rec.unmapped_count = len(rec.attendance_ids.filtered(
                lambda a: a.is_daily and a.attendance_status == "hadir"
                and a.portion_total < 0.999
            ))

    def action_submit_round(self):
        """Submit everything entered in this round at once."""
        for rec in self:
            if not rec.attendance_ids:
                raise UserError(_("%(name)s has nobody in it yet.", name=rec.name))
            rec.attendance_ids.filtered(lambda a: a.state == "draft").action_submit()
            rec.state = "submitted"
        return True

    def action_approve_round(self):
        """Approve the round, which approves each attendance through its own gate.

        Deliberately not a bulk write: the per-record gate is what refuses a paid shift
        that has not landed anywhere, and bypassing it here would defeat the control by
        offering a faster button.
        """
        for rec in self:
            if rec.unmapped_count:
                raise UserError(
                    _("%(count)s paid shift(s) in %(name)s have not landed on anything. "
                      "Map them first — the wage has already gone out.",
                      count=rec.unmapped_count, name=rec.name)
                )
            rec.attendance_ids.action_approve()
            rec.state = "approved"
        return True

    @api.model
    def get_or_open(self, date, shift_id, user_id=None):
        """Find today's round for this shift or start one. Used by the mobile endpoint."""
        user_id = user_id or self.env.user.id
        existing = self.search([
            ("date", "=", date), ("shift_id", "=", shift_id),
            ("supervisor_id", "=", user_id),
        ], limit=1)
        if existing:
            return existing
        return self.create({
            "date": date, "shift_id": shift_id, "supervisor_id": user_id})


class CustomSpkAttendance(models.Model):
    _inherit = "custom.spk.attendance"

    shopfloor_round_id = fields.Many2one(
        "custom.spk.shopfloor.round", index=True, ondelete="set null",
        help="Which walk of the workshops this was entered in. Optional: attendance "
        "typed straight into the back office has no round, and that is fine.",
    )
