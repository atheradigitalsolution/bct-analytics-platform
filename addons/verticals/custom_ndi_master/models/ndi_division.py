# -*- coding: utf-8 -*-
"""Divisi produk NDI (pasal 5).

Model CRUD tersendiri, bukan ``product.category``. Alasannya: ``product.category``
di Odoo membawa properti akuntansi (akun stok, akun HPP, metode valuasi) dan
dipakai oleh ``stock_account`` untuk menentukan jurnal. Divisi NDI adalah
pengelompokan komersial ("Bahan Baku", "Pakan Unggas", "Pakan Ruminansia",
"Kemasan", "Barang Dagangan") yang dipakai di filter laporan dan dashboard.
Menumpangkannya ke ``product.category`` akan mencampur dua sumbu yang klien
memang ingin pisah, dan mengunci divisi ke konfigurasi akuntansi.
"""

from odoo import api, fields, models


class NdiDivision(models.Model):
    _name = "ndi.division"
    _description = "NDI Divisi Produk"
    _order = "sequence, name, id"

    name = fields.Char(required=True, translate=False, index=True)
    code = fields.Char(index=True, help="Kode pendek untuk laporan dan impor data.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    category_ids = fields.One2many("ndi.product.category", "division_id", string="Kategori")
    category_count = fields.Integer(compute="_compute_category_count")
    product_count = fields.Integer(compute="_compute_product_count")
    note = fields.Text()

    _name_uniq = models.Constraint(
        "UNIQUE (name)",
        "Nama divisi harus unik.",
    )

    @api.depends("category_ids")
    def _compute_category_count(self):
        data = self.env["ndi.product.category"]._read_group(
            [("division_id", "in", self.ids)], ["division_id"], ["__count"]
        )
        mapped = {division.id: count for division, count in data}
        for record in self:
            record.category_count = mapped.get(record.id, 0)

    def _compute_product_count(self):
        data = self.env["product.template"]._read_group(
            [("ndi_divisi_id", "in", self.ids)], ["ndi_divisi_id"], ["__count"]
        )
        mapped = {division.id: count for division, count in data}
        for record in self:
            record.product_count = mapped.get(record.id, 0)
