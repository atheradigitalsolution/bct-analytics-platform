# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lgx_nle_enabled = fields.Boolean(related="company_id.lgx_nle_enabled", readonly=False)
    lgx_nle_base_url = fields.Char(related="company_id.lgx_nle_base_url", readonly=False)
    lgx_nle_api_key = fields.Char(related="company_id.lgx_nle_api_key", readonly=False)
    lgx_nle_id_platform = fields.Char(related="company_id.lgx_nle_id_platform", readonly=False)
