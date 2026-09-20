# -*- coding: utf-8 -*-
"""Parameter rekam medis yang belum ada di singleton, ditambahkan modul ini.

Tiga angka yang dipakai modul ini — ``klpcm_due_hours``,
``emr_correction_grace_hours``, ``emr_retention_years`` — **sudah** ada di
``custom_hms_base`` dan sengaja tidak diduplikasi di sini. Yang ditambahkan
hanya parameter yang memang lahir bersama alur di modul ini.

Keduanya adalah kebijakan internal rumah sakit, bukan norma nasional, dan
``help``-nya mengatakan begitu. PMK 24/2022 mengatur *bahwa* permintaan
pelepasan informasi disampaikan kepada pimpinan (Ps. 34(2)) dan *bahwa*
retensi paling singkat 25 tahun (Ps. 39(1)); ia tidak menetapkan berapa hari
sebuah permintaan harus dijawab, dan tidak menetapkan kapan tinjauan retensi
dijalankan. Angka default di bawah karena itu ditulis sebagai titik
konfigurasi, bukan sebagai aturan.
"""
from odoo import fields, models


class HmsSettings(models.Model):
    _inherit = "hms.settings"

    roi_response_due_days = fields.Integer(
        "Target penyelesaian pelepasan informasi (hari)", default=7,
        help="Tenggat internal sejak permintaan pelepasan informasi diajukan "
             "sampai dokumen diserahkan. TIDAK ADA NORMA NASIONAL untuk angka "
             "ini — PMK 24/2022 hanya mewajibkan permintaan disampaikan kepada "
             "pimpinan (Ps. 34 ayat (2)) tanpa menyebut batas waktu. Sesuaikan "
             "dengan SPO rumah sakit.",
    )
    retention_review_lead_days = fields.Integer(
        "Tinjauan retensi dimulai berapa hari sebelum jatuh tempo", default=180,
        help="Rekam medis yang akan mencapai batas retensi dalam rentang ini "
             "sudah dimasukkan ke daftar tinjauan, supaya pengecualian "
             "(klaim/perkara yang masih berjalan) sempat diperiksa sebelum "
             "tanggal jatuh temponya lewat. Kebijakan internal RS.",
    )
