# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    x_object_storage_config_id = fields.Many2one(
        "custom.adapter.config",
        string="Object Storage",
        domain="[('adapter_type', '=', 's3_compatible')]",
        help="Which bucket this company's photographs and design files live in. Left "
        "empty, the first active S3 configuration is used, which is right for a "
        "single-company database and wrong the moment there are two.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    x_object_storage_config_id = fields.Many2one(
        related="company_id.x_object_storage_config_id", readonly=False)
