# -*- coding: utf-8 -*-
"""Konfigurasi dan cache token CEISA 4.0, di tingkat perusahaan.

Token disimpan DI DATABASE dan bukan di memori proses, karena Odoo berjalan
multi-worker: cache di memori berarti setiap worker meminta tokennya sendiri,
dan dengan masa berlaku sependek yang dipakai CEISA itu menjadi badai permintaan
token yang tidak perlu — lalu pembatasan laju di sisi mereka.
"""
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    lgx_ceisa_enabled = fields.Boolean(
        "CEISA 4.0 Aktif", default=False,
        help="Selama mati, deklarasi hanya dapat dikerjakan lewat mode manual.",
    )
    lgx_ceisa_base_url = fields.Char(
        "Base URL CEISA", default="http://lgx-mock:4020",
        help="Arahkan ke mock saat pengembangan. Ganti ke endpoint DJBC setelah "
             "kredensial produksi terbit — dan itu perubahan konfigurasi, bukan rilis.",
    )
    lgx_ceisa_client_id = fields.Char("Client ID")
    lgx_ceisa_client_secret = fields.Char("Client Secret")
    lgx_ceisa_token = fields.Char("Access Token (cache)", copy=False, groups="base.group_system")
    lgx_ceisa_token_expiry = fields.Datetime("Token Kedaluwarsa", copy=False,
                                             groups="base.group_system")
