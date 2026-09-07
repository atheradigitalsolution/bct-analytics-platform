# -*- coding: utf-8 -*-
"""Snapshot tingkat harga di baris POS.

``pos_order_line`` tidak punya kolom UoM sama sekali dan tidak punya
``pricelist_item_id`` — pricelist hanya ada di ``pos.order``. Tanpa field ini,
omset POS per Harga 1-9 (pasal 4) tidak bisa dipisahkan dari total.

Ketiadaan kolom UoM itu juga alasan model ini TIDAK menimpa ``_ndi_line_uom``.
Kuantitas POS dinyatakan dalam satuan referensi produk, jadi bawaan mixin sudah
benar dan konversi HPP-nya menjadi operasi kosong. Menuliskan penimpaan di sini
akan menyiratkan ada pilihan satuan yang sebenarnya tidak pernah ada.

Order POS sampai ke Odoo dalam keadaan sudah selesai, jadi praktis snapshot
terisi sekali saat baris dibuat dan tidak pernah bergerak lagi.
"""

from odoo import api, models

EDITABLE_STATES = ("draft",)


class PosOrderLine(models.Model):
    _name = "pos.order.line"
    _inherit = ["pos.order.line", "ndi.hj.level.mixin"]

    @api.depends("order_id.pricelist_id", "product_id", "order_id.state")
    def _compute_ndi_hj_snapshot(self):
        return super()._compute_ndi_hj_snapshot()

    def _ndi_pricelist(self):
        return self.order_id.pricelist_id

    def _ndi_is_frozen(self):
        return bool(self.order_id) and self.order_id.state not in EDITABLE_STATES
