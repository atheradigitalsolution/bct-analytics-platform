# -*- coding: utf-8 -*-
"""Default Harga pelanggan (pasal 14).

Requirement menyebut "Default Harga" sebagai atribut pelanggan bernomor 1-9,
sementara Odoo menyimpannya sebagai relasi ke ``product.pricelist``. Dua bentuk
untuk satu fakta, jadi keduanya harus dijaga tetap sama. Arah kebenarannya:
angka yang ditulis pengguna -> pricelist yang dipakai mesin harga. Sebaliknya,
kalau pricelist diubah langsung, angkanya ikut menyesuaikan supaya laporan
pelanggan tidak berbohong.

``property_product_pricelist`` adalah compute dengan inverse ke
``specific_property_product_pricelist``; menulis ke sana adalah cara yang
didukung, bukan akal-akalan.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = "res.partner"

    ndi_default_hj_level = fields.Integer(
        string="Default Harga (1-9)",
        index="btree_not_null",
        help="Tingkat harga yang otomatis dipakai POS dan Sales untuk pelanggan ini.",
    )

    _ndi_default_hj_level_range = models.Constraint(
        "CHECK (ndi_default_hj_level IS NULL OR ndi_default_hj_level = 0 "
        "OR (ndi_default_hj_level >= 1 AND ndi_default_hj_level <= 9))",
        "Default Harga pelanggan harus antara 1 dan 9.",
    )

    def _ndi_apply_default_hj_level(self):
        """Sinkronkan angka -> pricelist."""
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        for partner in self:
            level = partner.ndi_default_hj_level
            if not level:
                continue
            pricelist = levels.get(level)
            if not pricelist:
                raise ValidationError(
                    self.env._(
                        "Belum ada pricelist untuk Harga %(level)s, jadi Default Harga "
                        "pelanggan %(partner)s tidak dapat diterapkan.",
                        level=level,
                        partner=partner.display_name,
                    )
                )
            if partner.property_product_pricelist != pricelist:
                partner.property_product_pricelist = pricelist

    @api.onchange("ndi_default_hj_level")
    def _onchange_ndi_default_hj_level(self):
        self._ndi_apply_default_hj_level()

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners.filtered("ndi_default_hj_level")._ndi_apply_default_hj_level()
        return partners

    def write(self, vals):
        result = super().write(vals)
        if "ndi_default_hj_level" in vals:
            self.filtered("ndi_default_hj_level")._ndi_apply_default_hj_level()
        elif "specific_property_product_pricelist" in vals:
            for partner in self:
                level = partner.property_product_pricelist.ndi_hj_level
                if level and partner.ndi_default_hj_level != level:
                    super(ResPartner, partner).write({"ndi_default_hj_level": level})
        return result
