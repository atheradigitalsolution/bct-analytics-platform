# -*- coding: utf-8 -*-
"""Milestone dapat menggantung pada shipment, bukan hanya pada job.

Pada konsolidasi, satu job house punya milestone sendiri sementara keberangkatan
kapal adalah kejadian pada master. Tanpa tautan ke shipment, keberangkatan itu
harus disalin ke setiap house — dan salinan yang harus dijaga tetap sama adalah
salinan yang akan berbeda.
"""
from odoo import fields, models


class LgxMilestone(models.Model):
    _inherit = "lgx.milestone"

    shipment_id = fields.Many2one("lgx.shipment", "Shipment", ondelete="cascade", index=True)
