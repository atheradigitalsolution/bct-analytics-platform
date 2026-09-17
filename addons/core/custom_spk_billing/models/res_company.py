# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    x_spk_credit_hold_days = fields.Integer(
        string="Umur Piutang untuk Peringatan Kredit",
        default=60,
        help="Debt older than this raises a warning when a new estimate is raised for "
        "that client. Zero disables the check.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    x_spk_credit_hold_days = fields.Integer(
        related="company_id.x_spk_credit_hold_days", readonly=False)
