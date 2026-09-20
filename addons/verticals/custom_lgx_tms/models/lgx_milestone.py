# -*- coding: utf-8 -*-
"""Milestone dapat menggantung pada trip."""
from odoo import fields, models


class LgxMilestone(models.Model):
    _inherit = "lgx.milestone"

    trip_id = fields.Many2one("lgx.trip", "Trip", ondelete="cascade", index=True)
