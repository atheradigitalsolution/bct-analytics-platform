# -*- coding: utf-8 -*-
"""Master produk NDI: klasifikasi, stok min/maks, dan komponen pembentuk HJ.

Sembilan field komponen (pasal 13) hidup di ``product.template`` dan bukan di
model terpisah karena requirement menyebut secara eksplisit "nilai setiap HJ dan
komponen pembentuknya disimpan pada Master Produk". ``ndi.price.matrix`` di
``custom_ndi_pricing`` membacanya lewat field ``related`` — satu arah, satu
sumber kebenaran.

``ndi_hj1``..``ndi_hj9`` adalah compute **stored**. Stored karena laporan pasal 24
dan dashboard pasal 4 mengelompokkan dan mengurutkan per tingkat harga, dan itu
mustahil di atas field non-stored. Perhitungannya di
:func:`~odoo.addons.custom_ndi_master.models.ndi_waterfall.compute_hj_waterfall`.
"""

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .ndi_waterfall import COMPONENT_KEYS, compute_hj_waterfall

JENIS_PRODUK = [
    ("bahan_baku", "Bahan Baku"),
    ("kemasan", "Kemasan"),
    ("produk_jadi", "Produk Jadi"),
    ("barang_dagangan", "Barang Dagangan"),
]

#: Field komponen pada ``product.template``, urut sesuai pasal 13.
COMPONENT_FIELDS = tuple("ndi_%s" % key for key in COMPONENT_KEYS)

#: Field hasil waterfall, HJ1 (termahal) .. HJ9 (= HPP dasar).
HJ_FIELDS = tuple("ndi_hj%d" % level for level in range(1, 10))


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # --- Klasifikasi master (pasal 5) --------------------------------------
    ndi_jenis_produk = fields.Selection(
        JENIS_PRODUK,
        string="Jenis Produk NDI",
        index=True,
        help="Mencabangkan perilaku HPP, BOM dan laporan. Berbeda dari `type` bawaan Odoo "
             "yang hanya mengenal barang/jasa/kombo.",
    )
    ndi_divisi_id = fields.Many2one("ndi.division", string="Divisi NDI", index=True, ondelete="restrict")
    ndi_kategori_id = fields.Many2one(
        "ndi.product.category",
        string="Kategori NDI",
        index=True,
        ondelete="restrict",
        domain="[('division_id', '=?', ndi_divisi_id)]",
    )
    ndi_stok_min = fields.Float(
        string="Stok Minimum", digits="Product Unit", help="Batas bawah dalam satuan dasar produk."
    )
    ndi_stok_maks = fields.Float(
        string="Stok Maksimum", digits="Product Unit", help="Batas atas dalam satuan dasar produk."
    )

    # --- Berat gross per tingkat UoM (pasal 17/18) -------------------------
    ndi_uom_weight_ids = fields.One2many(
        "ndi.product.uom.weight", "product_tmpl_id", string="Berat Gross per Satuan"
    )

    # --- Komponen pembentuk harga (pasal 13) -------------------------------
    ndi_hpp_dasar = fields.Float(string="HPP Dasar", digits="Product Price")
    ndi_profit_pct = fields.Float(string="Profit (%)", digits=(16, 4))
    ndi_risiko_pct = fields.Float(string="Risiko (%)", digits=(16, 4))
    ndi_pajak_pct = fields.Float(string="Pajak (%)", digits=(16, 4))
    ndi_ongkir_rp = fields.Float(string="Ongkir (Rp)", digits="Product Price")
    ndi_pembulatan_rp = fields.Float(
        string="Pembulatan (Rp)",
        digits="Product Price",
        help="Nominal yang DITAMBAHKAN pada HJ5, bukan kelipatan pembulatan. "
             "Semantik ini dikunci di dokumen keputusan D1.",
    )
    ndi_insentif_kwartal_rp = fields.Float(string="Insentif Kwartal (Rp)", digits="Product Price")
    ndi_insentif_bulanan_rp = fields.Float(string="Insentif Bulanan (Rp)", digits="Product Price")
    ndi_margin_het_rp = fields.Float(string="Margin HET (Rp)", digits="Product Price")

    # --- Hasil waterfall ---------------------------------------------------
    ndi_hj9 = fields.Float(string="Harga 9 (HPP Dasar)", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj8 = fields.Float(string="Harga 8", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj7 = fields.Float(string="Harga 7", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj6 = fields.Float(string="Harga 6", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj5 = fields.Float(string="Harga 5", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj4 = fields.Float(string="Harga 4", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj3 = fields.Float(string="Harga 3", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj2 = fields.Float(string="Harga 2", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)
    ndi_hj1 = fields.Float(string="Harga 1 (HET)", digits="Product Price",
                           compute="_compute_ndi_hj", store=True, readonly=True)

    @api.depends(*COMPONENT_FIELDS)
    def _compute_ndi_hj(self):
        for template in self:
            values = compute_hj_waterfall(template._ndi_price_components())
            for level in range(1, 10):
                template["ndi_hj%d" % level] = values["hj%d" % level]

    def _ndi_price_components(self):
        """Komponen pembentuk harga sebagai dict polos, siap dipakai waterfall."""
        self.ensure_one()
        return {key: self["ndi_%s" % key] for key in COMPONENT_KEYS}

    def _ndi_hj_values(self):
        """HJ1..HJ9 tersimpan sebagai dict ``{level:int -> harga:float}``."""
        self.ensure_one()
        return {level: self["ndi_hj%d" % level] for level in range(1, 10)}

    @api.constrains("ndi_stok_min", "ndi_stok_maks")
    def _check_ndi_stok_range(self):
        for template in self:
            if template.ndi_stok_maks and template.ndi_stok_min > template.ndi_stok_maks:
                raise ValidationError(
                    self.env._(
                        "Stok minimum (%(minimum)s) tidak boleh melebihi stok maksimum (%(maximum)s) "
                        "pada produk %(product)s.",
                        minimum=template.ndi_stok_min,
                        maximum=template.ndi_stok_maks,
                        product=template.display_name,
                    )
                )

    @api.constrains("ndi_divisi_id", "ndi_kategori_id")
    def _check_ndi_kategori_division(self):
        for template in self:
            category = template.ndi_kategori_id
            if category and category.division_id and category.division_id != template.ndi_divisi_id:
                raise ValidationError(
                    self.env._(
                        "Kategori %(category)s milik divisi %(owner)s, tidak cocok dengan divisi "
                        "produk %(division)s.",
                        category=category.name,
                        owner=category.division_id.name,
                        division=template.ndi_divisi_id.display_name or "-",
                    )
                )

    def ndi_gross_weight_for_uom(self, uom):
        """Berat gross (kg) untuk 1 satuan ``uom``, dipakai dokumen pasal 18.

        Kalau tidak ada baris ``ndi.product.uom.weight``, jatuh kembali ke
        ``weight`` bawaan yang dikonversi ke base unit — bukan nol, supaya
        dokumen tetap tercetak dengan angka yang masuk akal.
        """
        self.ensure_one()
        line = self.ndi_uom_weight_ids.filtered(lambda w: w.uom_id == uom)[:1]
        if line:
            return line.gross_weight
        if uom and self.uom_id and uom._has_common_reference(self.uom_id):
            return uom._compute_quantity(1.0, self.uom_id, round=False) * self.weight
        return self.weight
