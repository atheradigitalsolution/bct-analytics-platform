# -*- coding: utf-8 -*-
"""Kategori kendaraan dan konfigurasi sumbu.

Konfigurasi sumbu (1.1, 1.2, 1.22, 1.222) menentukan JBI maksimum yang
diperbolehkan untuk sebuah kendaraan. Disimpan sebagai master supaya tarif rute
dapat dibedakan per kategori tanpa mengetik ulang batas beratnya di setiap tarif.
"""
from odoo import api, fields, models


class LgxVehicleCategory(models.Model):
    _name = "lgx.vehicle.category"
    _description = "Kategori Kendaraan Angkutan Barang"
    _order = "sequence, code"

    sequence = fields.Integer(default=10)
    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama", required=True)
    axle_configuration = fields.Char("Konfigurasi Sumbu", help="Mis. 1.1, 1.2, 1.22, 1.222.")
    typical_jbi_kg = fields.Float("JBI Tipikal (kg)")
    typical_payload_kg = fields.Float("Muatan Tipikal (kg)")
    typical_volume_cbm = fields.Float("Volume Bak Tipikal (CBM)")
    can_carry_container = fields.Boolean("Dapat Mengangkut Kontainer")
    container_size_ft = fields.Integer("Ukuran Kontainer (ft)")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode kategori kendaraan harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.code} — {record.name}"
