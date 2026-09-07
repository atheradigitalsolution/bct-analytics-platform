# -*- coding: utf-8 -*-
"""Tingkat HJ pada ``product.pricelist``.

Field ini memikul dua beban sekaligus:

1. **Kunci ``ir.rule``** yang membatasi kasir ke Harga 1-3 (keputusan D6). Batas
   itu diletakkan di pricelist, bukan di ``pos.config``, karena
   ``pos.config.available_pricelist_ids`` berlaku per terminal sedangkan
   requirement pasal 22 berbicara tentang peran orang.
2. **Sumbu pengelompokan laporan** pasal 24.

Integer, bukan Selection, supaya bisa dipakai apa adanya sebagai kolom numerik di
warehouse dan dibandingkan dengan operator ``<=`` di domain.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ProductPricelist(models.Model):
    _inherit = "product.pricelist"

    ndi_hj_level = fields.Integer(
        string="Tingkat Harga NDI",
        index="btree_not_null",
        help="1 = Harga 1 (HET, tertinggi) sampai 9 = Harga 9 (HPP dasar). "
             "Kosong berarti pricelist ini bukan bagian dari matriks NDI.",
    )

    _ndi_hj_level_range = models.Constraint(
        "CHECK (ndi_hj_level IS NULL OR (ndi_hj_level >= 1 AND ndi_hj_level <= 9))",
        "Tingkat Harga NDI harus antara 1 dan 9.",
    )

    @api.constrains("ndi_hj_level")
    def _check_ndi_hj_level_unique(self):
        for pricelist in self:
            if not pricelist.ndi_hj_level:
                continue
            duplicate = self.search(
                [
                    ("ndi_hj_level", "=", pricelist.ndi_hj_level),
                    ("id", "!=", pricelist.id),
                    ("company_id", "in", [pricelist.company_id.id, False]),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    self.env._(
                        "Tingkat Harga %(level)s sudah dipakai oleh pricelist %(other)s. "
                        "Satu tingkat hanya boleh punya satu pricelist, kalau tidak "
                        "ir.rule pembatas kasir jadi ambigu.",
                        level=pricelist.ndi_hj_level,
                        other=duplicate.display_name,
                    )
                )

    @api.model
    def _ndi_pricelist_by_level(self):
        """``{tingkat -> product.pricelist}`` untuk sembilan tingkat NDI."""
        pricelists = self.sudo().search([("ndi_hj_level", ">=", 1), ("ndi_hj_level", "<=", 9)])
        return {pricelist.ndi_hj_level: pricelist for pricelist in pricelists}
