# -*- coding: utf-8 -*-
"""Parameter mutu yang dipakai modul ini, ditambahkan ke singleton yang sudah ada.

Target waktu tanggap komplain adalah **kebijakan**, bukan konstanta. Menuliskan
24/72/168 jam di dalam kode berarti setiap rumah sakit yang memakai SIMRS ini
harus mengubah sumber untuk memakai SPO-nya sendiri, dan yang sebenarnya
terjadi adalah tidak ada yang mengubahnya — angka nasional dipakai sebagai
angka RS tanpa pernah diputuskan siapa pun.

Angka defaultnya mengikuti definisi operasional INM "Kecepatan Waktu Tanggap
Komplain" (Permenkes 30/2022): grading merah 1x24 jam, kuning 3 hari, hijau
7 hari.
"""
from odoo import fields, models


class HmsSettings(models.Model):
    _inherit = "hms.settings"

    complaint_response_red_hours = fields.Integer(
        "Target tanggap komplain merah (jam)", default=24,
        help="Komplain berdampak luas/berisiko hukum. Definisi operasional INM "
             "'Kecepatan Waktu Tanggap Komplain' (Permenkes 30/2022): 1x24 jam.",
    )
    complaint_response_yellow_hours = fields.Integer(
        "Target tanggap komplain kuning (jam)", default=72,
        help="Komplain berdampak sedang antar unit. Definisi operasional INM "
             "(Permenkes 30/2022): 3 hari.",
    )
    complaint_response_green_hours = fields.Integer(
        "Target tanggap komplain hijau (jam)", default=168,
        help="Komplain ringan yang dapat diselesaikan unit setempat. Definisi "
             "operasional INM (Permenkes 30/2022): 7 hari.",
    )
