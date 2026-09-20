# -*- coding: utf-8 -*-
"""Tarif penyimpanan dan handling, dan konversi pallet.

Tarif berjenjang menurut volume adalah hal biasa di 3PL, dan masa bebas serta
tagihan minimum hampir selalu ada. Ketiganya diperlakukan sebagai data supaya
kontrak baru tidak menjadi rilis modul.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxWmsClient(models.Model):
    _inherit = "lgx.wms.client"

    storage_rule_ids = fields.One2many("lgx.wms.storage.rule", "client_id", "Tarif Penyimpanan")
    handling_rule_ids = fields.One2many("lgx.wms.handling.rule", "client_id", "Tarif Handling")
    units_per_pallet_default = fields.Float(
        "Unit per Pallet (default)", default=0.0,
        help="Dipakai menghitung ekuivalen pallet bila produk tidak punya angkanya "
             "sendiri. Nol berarti tagihan per pallet tidak dapat dihitung untuk "
             "klien ini — dan itu dikatakan, bukan dibulatkan menjadi nol pallet.",
    )

    def _lgx_pallet_equivalent(self, product, quantity):
        """Ekuivalen pallet dari kuantitas produk.

        Memakai angka produk bila ada, lalu default klien. Tidak pernah menebak 1
        pallet per unit: tagihan penyimpanan yang dihitung dari tebakan adalah
        tagihan yang dicabut pelanggan pada rapat bulanan pertama.
        """
        self.ensure_one()
        per_pallet = getattr(product, "lgx_units_per_pallet", 0.0) or self.units_per_pallet_default
        if not per_pallet:
            return 0.0
        return (quantity or 0.0) / per_pallet


class ProductTemplate(models.Model):
    _inherit = "product.template"

    lgx_units_per_pallet = fields.Float(
        "Unit per Pallet",
        help="Dipakai penagihan gudang untuk menghitung ekuivalen pallet dari kuantitas.",
    )


class LgxWmsStorageRule(models.Model):
    _name = "lgx.wms.storage.rule"
    _description = "Tarif Penyimpanan"
    _order = "client_id, valid_from desc"

    client_id = fields.Many2one("lgx.wms.client", "Klien", required=True,
                                ondelete="cascade", index=True)
    company_id = fields.Many2one(related="client_id.company_id", store=True, index=True)
    name = fields.Char("Nama", required=True)
    basis = fields.Selection(
        [("per_pallet_day", "Per Pallet per Hari"), ("per_cbm_day", "Per CBM per Hari"),
         ("per_sku_month", "Per SKU per Bulan"), ("per_kg_day", "Per Kg per Hari")],
        string="Dasar", required=True, default="per_pallet_day",
    )
    rate = fields.Monetary("Tarif", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(related="client_id.currency_id", readonly=True)
    free_days = fields.Integer("Masa Bebas (hari)")
    minimum_charge = fields.Monetary("Tagihan Minimum per Periode", currency_field="currency_id")
    tier_ids = fields.One2many("lgx.wms.storage.tier", "rule_id", "Jenjang")
    product_category_id = fields.Many2one("product.category", "Berlaku untuk Kategori")
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    _rate_non_negative = models.Constraint(
        "check(rate >= 0 and minimum_charge >= 0)", "Tarif dan tagihan minimum tidak boleh negatif.",
    )

    def lgx_rate_for(self, volume):
        """Tarif untuk volume tertentu, memperhitungkan jenjang."""
        self.ensure_one()
        applicable = self.tier_ids.filtered(lambda t: volume >= t.min_volume)
        if applicable:
            return applicable.sorted("min_volume")[-1].rate
        return self.rate


class LgxWmsStorageTier(models.Model):
    _name = "lgx.wms.storage.tier"
    _description = "Jenjang Tarif Penyimpanan"
    _order = "rule_id, min_volume"

    rule_id = fields.Many2one("lgx.wms.storage.rule", "Tarif", required=True,
                              ondelete="cascade", index=True)
    min_volume = fields.Float("Volume Minimum", required=True)
    rate = fields.Monetary("Tarif", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(related="rule_id.currency_id", readonly=True)

    _min_volume_non_negative = models.Constraint(
        "check(min_volume >= 0)", "Volume minimum jenjang tidak boleh negatif.",
    )


class LgxWmsHandlingRule(models.Model):
    _name = "lgx.wms.handling.rule"
    _description = "Tarif Handling"
    _order = "client_id, operation"

    client_id = fields.Many2one("lgx.wms.client", "Klien", required=True,
                                ondelete="cascade", index=True)
    company_id = fields.Many2one(related="client_id.company_id", store=True, index=True)
    name = fields.Char("Nama", required=True)
    operation = fields.Selection(
        [("inbound", "Masuk"), ("outbound", "Keluar"), ("vas", "Value Added Service"),
         ("return", "Retur")],
        string="Operasi", required=True, default="inbound",
    )
    basis = fields.Selection(
        [("per_pallet", "Per Pallet"), ("per_carton", "Per Karton"), ("per_line", "Per Baris"),
         ("per_unit", "Per Unit"), ("per_hour", "Per Jam")],
        string="Dasar", required=True, default="per_pallet",
    )
    rate = fields.Monetary("Tarif", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(related="client_id.currency_id", readonly=True)
    minimum_charge = fields.Monetary("Tagihan Minimum", currency_field="currency_id")
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    _rate_non_negative = models.Constraint(
        "check(rate >= 0)", "Tarif handling tidak boleh negatif.",
    )
