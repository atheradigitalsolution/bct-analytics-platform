# -*- coding: utf-8 -*-
"""Tautan job ke penawaran dan kontrak.

Dideklarasikan di modul pricing, bukan di custom_lgx_job, supaya job tetap bisa
berdiri tanpa lapisan komersial — klien yang hanya membeli modul operasional
tidak perlu memasang rate card untuk bisa membuat job.
"""
from odoo import fields, models


class LgxJob(models.Model):
    _inherit = "lgx.job"

    quote_id = fields.Many2one("lgx.quote", "Penawaran Asal", readonly=True, index=True)
    contract_id = fields.Many2one("lgx.contract", "Kontrak", index=True,
                                  domain="[('partner_id','=',customer_id)]")
