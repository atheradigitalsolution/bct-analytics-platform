# -*- coding: utf-8 -*-
"""Konfigurasi NLE / INSW.

Berbeda dari CEISA, NLE memakai API key statis pada header `beacukai-api-key` —
tidak ada alur OAuth dan tidak ada token yang perlu disegarkan. Yang justru tidak
boleh dilupakan adalah `id_platform`: ia diperoleh lewat registrasi, dan request
tanpa itu ditolak dengan pesan yang tidak menyebutkan penyebabnya.
"""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    lgx_nle_enabled = fields.Boolean("NLE / INSW Aktif", default=False)
    lgx_nle_base_url = fields.Char(
        "Base URL NLE", default="http://lgx-mock:4020",
        help="Produksi: https://api.beacukai.go.id — development DJBC memakai host "
             "dan port yang berbeda. Arahkan ke http://lgx-mock:4020 saat pengembangan.",
    )
    lgx_nle_api_key = fields.Char("API Key (header beacukai-api-key)")
    lgx_nle_id_platform = fields.Char(
        "ID Platform",
        help="Diperoleh lewat registrasi ke NLE. Request tanpa ini ditolak, dan "
             "penolakannya tidak menyebutkan penyebabnya.",
    )
