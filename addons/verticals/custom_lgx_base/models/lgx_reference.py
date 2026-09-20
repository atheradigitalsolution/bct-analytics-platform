# -*- coding: utf-8 -*-
"""Master referensi kecil: tipe kontainer, komoditas, jenis dokumen.

Kecil, tetapi tiga-tiganya membawa angka yang menentukan uang: kapasitas
kontainer menentukan fill rate konsolidasi, komoditas menentukan larangan dan
pembatasan, jenis dokumen menentukan apakah sebuah lembar butuh meterai.
"""
from odoo import api, fields, models


class LgxContainerType(models.Model):
    _name = "lgx.container.type"
    _description = "Tipe Kontainer"
    _order = "sequence, code"

    sequence = fields.Integer(default=10)
    code = fields.Char("Kode ISO", required=True, index=True, help="20GP, 40GP, 40HC, 20RF, 40FR, ...")
    name = fields.Char("Nama", required=True)
    size_ft = fields.Integer("Ukuran (ft)", default=20)
    is_reefer = fields.Boolean("Berpendingin")
    is_high_cube = fields.Boolean("High Cube")
    is_open_top = fields.Boolean("Open Top")
    is_flat_rack = fields.Boolean("Flat Rack")
    teu = fields.Float("TEU", default=1.0, help="Twenty-foot Equivalent Unit. 20ft = 1, 40ft = 2.")
    max_payload_kg = fields.Float("Muatan Maksimum (kg)")
    tare_weight_kg = fields.Float("Berat Kosong (kg)")
    internal_volume_cbm = fields.Float(
        "Volume Dalam (CBM)",
        help="Dasar perhitungan fill rate konsolidasi LCL. Angka nominal ISO, "
             "bukan ruang yang benar-benar terpakai.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode tipe kontainer harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}" if rec.code else rec.name


class LgxCommodity(models.Model):
    _name = "lgx.commodity"
    _description = "Komoditas"
    _order = "name"
    _parent_store = True

    name = fields.Char("Nama", required=True)
    code = fields.Char("Kode")
    parent_id = fields.Many2one("lgx.commodity", "Induk", ondelete="cascade", index=True)
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many("lgx.commodity", "parent_id", "Turunan")
    is_dangerous = fields.Boolean("Barang Berbahaya (DG)")
    imdg_class = fields.Char("Kelas IMDG", help="Diisi bila barang berbahaya, mis. 3, 8, 9.")
    un_number = fields.Char("Nomor UN")
    requires_temperature_control = fields.Boolean("Butuh Suhu Terkendali")
    temperature_min_c = fields.Float("Suhu Minimum (°C)")
    temperature_max_c = fields.Float("Suhu Maksimum (°C)")
    active = fields.Boolean(default=True)


class LgxDocumentType(models.Model):
    _name = "lgx.document.type"
    _description = "Jenis Dokumen Logistik"
    _order = "sequence, code"

    sequence = fields.Integer(default=10)
    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama", required=True)
    category = fields.Selection(
        [
            ("transport", "Dokumen Angkut"),
            ("customs", "Kepabeanan"),
            ("commercial", "Komersial"),
            ("permit", "Perizinan / Lartas"),
            ("proof", "Bukti Terima / Serah"),
            ("contract", "Kontrak & Perjanjian"),
            ("vehicle", "Dokumen Kendaraan"),
            ("personnel", "Dokumen Personel"),
        ],
        string="Kategori", required=True, default="transport",
    )
    requires_stamp_duty = fields.Boolean(
        "Perlu Meterai", default=False,
        help="UU 10/2020 Pasal 7 mengecualikan konosemen, surat angkutan barang, "
             "surat penyimpanan barang, serta bukti pengiriman dan penerimaan "
             "barang. Default di modul ini mengikuti pengecualian itu; ubah per "
             "jenis dokumen, jangan di kode.",
    )
    is_customer_visible = fields.Boolean(
        "Terlihat Pelanggan", default=False,
        help="Menentukan apakah dokumen muncul di portal pelanggan.",
    )
    has_expiry = fields.Boolean(
        "Punya Masa Berlaku",
        help="Dokumen bermasa-berlaku ikut mesin peringatan generik custom_lgx_doc.",
    )
    default_warning_days = fields.Integer("Ambang Peringatan (hari)", default=30)
    blocks_milestone_code = fields.Char(
        "Menghalangi Milestone",
        help="Kode milestone yang tidak boleh tercapai selama dokumen ini belum ada. "
             "Kosong berarti dokumen hanya menjadi pengingat.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode jenis dokumen harus unik.")
