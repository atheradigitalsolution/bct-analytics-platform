# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lgx_ceisa_enabled = fields.Boolean(related="company_id.lgx_ceisa_enabled", readonly=False)
    lgx_ceisa_base_url = fields.Char(related="company_id.lgx_ceisa_base_url", readonly=False)
    lgx_ceisa_client_id = fields.Char(related="company_id.lgx_ceisa_client_id", readonly=False)
    lgx_ceisa_client_secret = fields.Char(related="company_id.lgx_ceisa_client_secret",
                                          readonly=False)
    lgx_ceisa_token_leeway = fields.Integer(
        "Margin Perbarui Token (detik)",
        config_parameter="lgx.ceisa_token_leeway", default=15,
        help="Token diperbarui sebelum benar-benar mati sebanyak margin ini. "
             "Nol berarti menunggu sampai mati — dan menunggu sampai mati berarti "
             "sebagian request berangkat dengan token yang baru saja kedaluwarsa.",
    )

    def action_lgx_ceisa_test_connection(self):
        self.ensure_one()
        return self.env["lgx.ceisa.client"].action_test_connection(self.company_id)
