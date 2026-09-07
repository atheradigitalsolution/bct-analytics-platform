# -*- coding: utf-8 -*-
"""Snapshot tingkat harga di baris penjualan."""

from odoo import api, models

#: Selama order masih di sini, harga (``price_unit``) masih dihitung ulang oleh
#: Odoo, jadi tingkat harga juga masih boleh ikut bergerak.
EDITABLE_STATES = ("draft", "sent")


class SaleOrderLine(models.Model):
    _name = "sale.order.line"
    _inherit = ["sale.order.line", "ndi.hj.level.mixin"]

    # `product_uom_id` ikut di sini karena HPP disnapshot DALAM satuan baris:
    # mengubah satuan dari SAK 50 KG ke SAK 30 KG mengubah biaya per satuan tanpa
    # menyentuh produk maupun pricelist. Tanpa dependensi ini, satu-satunya jejak
    # perubahan itu adalah margin yang diam-diam salah.
    @api.depends("order_id.pricelist_id", "product_id", "product_uom_id", "order_id.state")
    def _compute_ndi_hj_snapshot(self):
        return super()._compute_ndi_hj_snapshot()

    def _ndi_pricelist(self):
        return self.order_id.pricelist_id

    def _ndi_line_uom(self):
        """Satuan baris penjualan, yang sering BUKAN satuan referensi produknya.

        Inilah model yang membuat konversi di mixin perlu ada: pakan berbasis kg
        dijual per sak, jadi `product_uom_id` berbeda dari `product_id.uom_id`
        pada hampir setiap baris. Kosong hanya sebelum produk dipilih, dan mixin
        sudah mundur ke satuan referensi untuk kasus itu.
        """
        return self.product_uom_id or super()._ndi_line_uom()

    def _ndi_is_frozen(self):
        return bool(self.order_id) and self.order_id.state not in EDITABLE_STATES
