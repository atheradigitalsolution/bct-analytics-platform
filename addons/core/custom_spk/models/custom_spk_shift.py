# -*- coding: utf-8 -*-
"""Shift master: the unit a daily worker is paid in and a job is costed by."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CustomSpkShift(models.Model):
    _name = "custom.spk.shift"
    _description = "Shift Kerja"
    _order = "sequence, time_start"

    name = fields.Char(required=True, translate=False)
    sequence = fields.Integer(default=10)
    code = fields.Char(help="Short code used on attendance sheets, e.g. S1.")
    time_start = fields.Float(string="Mulai", required=True, help="24h decimal, 7.0 = 07:00")
    time_stop = fields.Float(string="Selesai", required=True, help="24h decimal, 15.0 = 15:00")
    crosses_midnight = fields.Boolean(
        compute="_compute_crosses_midnight",
        store=True,
        help="A night shift ends on the next calendar day. Stored so that anything "
        "summing hours can see it without re-deriving the comparison.",
    )
    rate_multiplier = fields.Float(
        string="Multiplier Upah",
        default=1.0,
        required=True,
        digits=(6, 4),
        help="Applied to the worker's shift rate. This is a ratio, not money, so it "
        "is readable by anyone who schedules shifts.",
    )
    meal_allowance = fields.Monetary(
        string="Tunjangan Makan",
        currency_field="currency_id",
        groups="custom_spk.group_spk_cost_viewer",
        help="Money, therefore fenced. A supervisor schedules shifts without needing "
        "to know what one costs.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        groups="custom_spk.group_spk_cost_viewer",
    )
    active = fields.Boolean(default=True)

    _uniq_code = models.Constraint(
        "unique(code)",
        "Shift codes are what attendance sheets are read against; they cannot repeat.",
    )

    @api.depends("time_start", "time_stop")
    def _compute_crosses_midnight(self):
        for rec in self:
            rec.crosses_midnight = bool(rec.time_stop and rec.time_stop <= rec.time_start)

    @api.constrains("time_start", "time_stop", "rate_multiplier")
    def _check_bounds(self):
        for rec in self:
            for label, value in (("Mulai", rec.time_start), ("Selesai", rec.time_stop)):
                if not 0.0 <= value < 24.0:
                    raise ValidationError(
                        _("%(label)s must be within a day (0 to 23.99), got %(value)s.",
                          label=label, value=value)
                    )
            if rec.rate_multiplier <= 0:
                raise ValidationError(_("A shift multiplier of zero or less pays nothing."))
