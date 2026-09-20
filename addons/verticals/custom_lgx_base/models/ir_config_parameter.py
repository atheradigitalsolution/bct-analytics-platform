# -*- coding: utf-8 -*-
"""Pembacaan parameter angka yang tidak meledak karena salah ketik.

`get_param` mengembalikan apa adanya, dan yang memanggilnya membungkusnya
`int()` atau `float()`. Terukur di athera_lgx:

    tidak ada        -> default        aman
    ada tapi kosong  -> default        aman, Odoo memakai `or default`
    ada berisi "lima"-> "lima"          int() MELEMPAR ValueError

Mode ketiga itu yang berbahaya, dan bukan karena galatnya. Parameter diisi
manusia lewat layar Pengaturan; salah ketik di sana bukan kemungkinan teoretis.
Dan di modul ini ia punya ekor yang lebih buruk: dekorator `lgx_public_api`
menangkap `ValueError` lalu menjawab **bad_value** — yaitu "payload Anda salah"
kepada perangkat di lapangan, untuk masalah konfigurasi server. Galat yang jujur
menunjuk arah yang sama sekali salah, dan pengemudi yang membacanya akan
mengirim ulang POD yang sudah benar.

Jadi angka yang tidak dapat dibaca JATUH KE DEFAULT dan dicatat WARNING dengan
kuncinya. Sistem tetap berjalan dengan nilai yang masuk akal, dan yang salah
tetap dapat ditemukan saat dicari — bukan mengubur log seperti ERROR, bukan
menghentikan pekerjaan.

Yang SENGAJA tidak dilakukan: menolak menyimpan parameter yang tidak numerik.
Tidak semua parameter angka, dan daftar mana yang harus numerik akan berumur
lebih pendek daripada parameternya sendiri.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model
    def lgx_int(self, key, default):
        return self._lgx_number(int, key, default)

    @api.model
    def lgx_float(self, key, default):
        return self._lgx_number(float, key, default)

    @api.model
    def _lgx_number(self, konversi, key, default):
        mentah = self.sudo().get_param(key, default)
        try:
            return konversi(mentah)
        except (TypeError, ValueError):
            _logger.warning(
                "Parameter %s bernilai %r yang tidak dapat dibaca sebagai angka; "
                "memakai %r. Perbaiki di Pengaturan — nilai ini menggerakkan "
                "perhitungan, dan yang dipakai sekarang bukan yang Anda isi.",
                key, mentah, default,
            )
            return konversi(default)
