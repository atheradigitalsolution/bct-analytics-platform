# -*- coding: utf-8 -*-
"""Penanda tingkat kemasan pada ``uom.uom``.

Odoo 19 tidak lagi punya ``uom.category`` maupun ``product.packaging``; pohon
``uom.uom`` (``relative_uom_id`` / ``relative_factor`` / ``factor``) adalah
satu-satunya struktur yang tersisa. Pohon itu tidak menyimpan *peran* sebuah
satuan — apakah ia satuan dasar timbang atau satuan kemasan jual. Dokumen surat
jalan pasal 18 ("Isi Sak", "Isi Dus") membutuhkan peran itu, jadi ditandai di sini.

``ndi_tier`` sengaja Integer bebas, bukan Selection 1/2/3: NDI hari ini memakai
tiga tingkat (KG -> SAK -> TON) tetapi tidak ada di Odoo yang membatasi kedalaman
pohon, dan mengunci ke tiga akan memaksa migrasi saat tingkat keempat muncul.
"""

from odoo import api, fields, models


class UomUom(models.Model):
    _inherit = "uom.uom"

    ndi_is_packaging = fields.Boolean(
        string="Satuan Kemasan NDI",
        help="Satuan ini mewakili kemasan jual (sak, dus, bal, drum), bukan satuan dasar timbang.",
    )
    ndi_tier = fields.Integer(
        string="Tingkat UoM NDI",
        compute="_compute_ndi_tier",
        store=True,
        recursive=True,
        help="Kedalaman satuan pada pohon UoM: 1 untuk akar, 2 untuk anak langsung, dan seterusnya.",
    )

    @api.depends("relative_uom_id", "relative_uom_id.ndi_tier")
    def _compute_ndi_tier(self):
        for uom in self:
            uom.ndi_tier = (uom.relative_uom_id.ndi_tier + 1) if uom.relative_uom_id else 1
