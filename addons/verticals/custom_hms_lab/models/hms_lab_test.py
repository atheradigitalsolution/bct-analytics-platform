# -*- coding: utf-8 -*-
"""Katalog pemeriksaan laboratorium: satu tarif yang dipesan → daftar parameter.

KENAPA LAPISAN INI ADA, PADAHAL SUDAH ADA ``hms.lab.parameter.tariff_ids``
-------------------------------------------------------------------------
Sebelum modul ini, hubungan "tarif apa menghasilkan parameter apa" hanya
tersimpan sebagai Many2many pada sisi parameter. Bentuk itu cukup untuk
menjawab satu pertanyaan (parameter mana yang muncul), tapi tidak punya
tempat untuk menyimpan hal yang justru menentukan apakah pemeriksaannya bisa
dikerjakan sama sekali: spesimen apa yang diambil, tabung apa yang dipakai,
berapa lama target hasilnya, dan apakah ini panel atau pemeriksaan tunggal.
Petugas sampling membaca hal-hal itu, bukan daftar parameternya.

``hms.lab.test`` menambahkan lapisan katalog tersebut. Ia TIDAK menggantikan
``tariff_ids``. Urutan resolusinya ada di
``hms.tariff._hms_lab_parameters()`` dan sengaja berjenjang:

1. Ada ``hms.lab.test`` aktif untuk tarif itu **dan** test-nya punya
   parameter → pakai ``test.parameter_ids``.
2. Tidak ada → jatuh kembali ke ``hms.lab.parameter.tariff_ids`` seperti
   sebelumnya.

Fallback itu bukan sisa kode: master lab yang sudah diisi lewat jalur lama
tetap sah dan tetap menghasilkan baris hasil tanpa harus dimigrasi lebih
dulu. Migrasi yang memaksa semua tarif punya entri katalog dalam satu
langkah akan membuat pemeriksaan yang belum sempat dikatalogkan berhenti
menghasilkan parameter — kegagalan senyap di tengah jam kerja lab.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsLabTest(models.Model):
    _name = "hms.lab.test"
    _description = "Katalog Pemeriksaan Laboratorium"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama Pemeriksaan", required=True)
    tariff_id = fields.Many2one(
        "hms.tariff", "Item Tarif", required=True, index=True, ondelete="cascade",
        help="Tarif yang dipesan dokter. Dari tarif inilah daftar parameter "
             "diturunkan saat worklist lab membuat baris hasil.",
    )
    parameter_ids = fields.Many2many(
        "hms.lab.parameter", "hms_lab_test_parameter_rel", "test_id", "parameter_id",
        string="Parameter",
        help="Parameter yang dihasilkan pemeriksaan ini. Panel 'Darah Lengkap' "
             "berisi belasan parameter; pemeriksaan tunggal berisi satu.",
    )
    parameter_count = fields.Integer(
        "Jumlah Parameter", compute="_compute_parameter_count", store=True,
    )
    specimen_type = fields.Char(
        "Jenis Spesimen",
        help="Mis. darah vena EDTA, serum, urin sewaktu. Dibaca petugas sampling.",
    )
    container = fields.Char(
        "Tabung / Wadah",
        help="Mis. tabung tutup ungu (EDTA), tutup kuning (serum separator). "
             "Salah tabung adalah penyebab penolakan spesimen yang paling sering.",
    )
    tat_minutes = fields.Integer(
        "Target Waktu Hasil (menit)",
        help="Turnaround time yang dijanjikan sejak spesimen diterima. Dipakai "
             "sebagai acuan mutu, bukan sebagai blokir.",
    )
    is_panel = fields.Boolean(
        "Panel",
        help="Ditandai bila satu permintaan menghasilkan banyak parameter "
             "sekaligus. Panel dilaporkan sebagai satu lembar hasil.",
    )
    note = fields.Text("Catatan Persiapan", help="Mis. puasa 10-12 jam.")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode pemeriksaan lab harus unik.")
    # Satu tarif aktif hanya boleh punya satu entri katalog, supaya resolusi
    # parameter tidak pernah bergantung pada urutan pencarian. Entri yang
    # diarsipkan dikecualikan agar katalog lama masih bisa disimpan sebagai
    # riwayat.
    _tariff_active_uniq = models.UniqueIndex("(tariff_id) WHERE active IS TRUE")

    @api.depends("parameter_ids")
    def _compute_parameter_count(self):
        for rec in self:
            rec.parameter_count = len(rec.parameter_ids)

    @api.constrains("is_panel", "parameter_ids")
    def _check_panel(self):
        for rec in self:
            if rec.is_panel and len(rec.parameter_ids) < 2:
                raise ValidationError(
                    _("Pemeriksaan '%s' ditandai panel tetapi hanya punya satu "
                      "parameter atau kurang.") % rec.name
                )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"
