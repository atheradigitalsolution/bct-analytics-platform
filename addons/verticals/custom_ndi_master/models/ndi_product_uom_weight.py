# -*- coding: utf-8 -*-
"""Berat gross per tingkat UoM (requirement pasal 17 dan 18).

``product.template.weight`` adalah satu Float pada base unit, dan
``stock.picking`` menghitung berat sebagai ``sum(qty_base x product.weight)``.
Itu berat **netto isi**. Surat jalan NDI ("BERAT T. BARANG") meminta berat
**gross** pada satuan yang benar-benar ditransaksikan: satu sak 50 kg pakan
menimbang 50,148 kg karena karung dan benang jahitnya ikut. Selisih 0,148 kg per
sak menjadi ~3 kg per ton, dan itulah angka yang ditagih ke ekspedisi.

Karena itu berat tidak bisa diturunkan dari ``factor`` UoM — ia harus data
tersendiri per (produk, UoM).
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class NdiProductUomWeight(models.Model):
    _name = "ndi.product.uom.weight"
    _description = "NDI Berat Gross per Tingkat UoM"
    _order = "product_tmpl_id, uom_id"
    _rec_names_search = ["product_tmpl_id", "uom_id"]

    product_tmpl_id = fields.Many2one(
        "product.template", string="Produk", required=True, ondelete="cascade", index=True
    )
    uom_id = fields.Many2one("uom.uom", string="Satuan", required=True, ondelete="restrict", index=True)
    gross_weight = fields.Float(
        string="Berat Gross (kg)",
        # Tiga desimal, bukan presisi "Stock Weight" (2 desimal) bawaan. Satu sak
        # pakan 50 kg menimbang 50,148 kg; dibulatkan ke 50,15 selisihnya 2 gram
        # per sak, 40 gram per ton, dan itu tagihan ekspedisi yang salah.
        digits=(16, 3),
        required=True,
        help="Berat kotor dalam kilogram untuk 1 satuan UoM ini, termasuk kemasan.",
    )
    net_weight = fields.Float(
        string="Berat Netto (kg)",
        compute="_compute_net_weight",
        digits=(16, 3),
        help="Berat isi menurut master produk, untuk pembanding. Tidak disimpan.",
    )
    tare_weight = fields.Float(
        string="Berat Kemasan (kg)", compute="_compute_net_weight", digits=(16, 3)
    )

    _product_uom_uniq = models.Constraint(
        "UNIQUE (product_tmpl_id, uom_id)",
        "Berat gross untuk kombinasi produk dan satuan ini sudah ada.",
    )
    _gross_weight_positive = models.Constraint(
        "CHECK (gross_weight >= 0)",
        "Berat gross tidak boleh negatif.",
    )

    @api.depends("product_tmpl_id", "uom_id", "gross_weight")
    def _compute_net_weight(self):
        for record in self:
            template = record.product_tmpl_id
            net = 0.0
            if template and record.uom_id and template.uom_id:
                if record.uom_id._has_common_reference(template.uom_id):
                    qty_base = record.uom_id._compute_quantity(1.0, template.uom_id, round=False)
                    net = qty_base * template.weight
            record.net_weight = net
            record.tare_weight = record.gross_weight - net

    @api.constrains("product_tmpl_id", "uom_id")
    def _check_uom_belongs_to_product(self):
        for record in self:
            template = record.product_tmpl_id
            allowed = template.uom_id | template.uom_ids
            if record.uom_id not in allowed:
                raise ValidationError(
                    self.env._(
                        "Satuan %(uom)s bukan satuan dasar maupun satuan kemasan produk %(product)s. "
                        "Tambahkan dulu satuan itu pada tab Satuan produk.",
                        uom=record.uom_id.display_name,
                        product=template.display_name,
                    )
                )
