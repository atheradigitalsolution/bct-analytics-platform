# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lgx_disbursement_account_id = fields.Many2one(
        related="company_id.lgx_disbursement_account_id", readonly=False)
    lgx_accrual_account_id = fields.Many2one(
        related="company_id.lgx_accrual_account_id", readonly=False)
    lgx_provision_account_id = fields.Many2one(
        related="company_id.lgx_provision_account_id", readonly=False)
    lgx_variance_account_id = fields.Many2one(
        related="company_id.lgx_variance_account_id", readonly=False)
    lgx_accrual_journal_id = fields.Many2one(
        related="company_id.lgx_accrual_journal_id", readonly=False)
    lgx_provision_age_days = fields.Integer(
        "Umur Provisi Dilaporkan (hari)",
        config_parameter="lgx.provision_age_days", default=90,
    )
    lgx_min_margin_pct = fields.Float(
        "Ambang Margin Penawaran (%)",
        config_parameter="lgx.min_margin_pct", default=10.0,
    )
