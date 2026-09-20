# -*- coding: utf-8 -*-
"""Penanda kategori barang milik klien.

Field ini ada supaya "kategori mana yang barang klien" adalah data, bukan
kesepakatan lisan tentang nama kategori. Laporan keuangan yang harus
mengecualikan barang klien membacanya dari sini.
"""
from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = "product.category"

    lgx_is_client_goods = fields.Boolean(
        "Barang Milik Klien (3PL)",
        help="Kategori ini menampung barang yang BUKAN milik perusahaan. Harus "
             "berpasangan dengan valuasi manual/periodik, kalau tidak "
             "penerimaannya membentuk jurnal dan masuk neraca.",
    )
