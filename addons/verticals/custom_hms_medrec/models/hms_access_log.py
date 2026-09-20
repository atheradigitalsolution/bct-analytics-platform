# -*- coding: utf-8 -*-
"""Menambah satu nilai ``action`` pada jejak akses: ``disclose``.

**Aditif, bukan pengganti.** ``selection_add`` menyisipkan nilai baru dan
membiarkan ``read/write/create/unlink/print/export`` milik ``custom_hms_audit``
utuh. Mengganti daftarnya (menulis ulang ``action = fields.Selection([...])``)
akan membuat setiap baris log lama yang nilainya tidak ada di daftar baru
menjadi tidak terbaca oleh ORM — sebuah jejak audit yang hilang diam-diam,
yang justru paling dibutuhkan ketika ada dugaan penyalahgunaan.

``ondelete`` wajib diisi karena ``action`` bersifat ``required``: Odoo perlu
tahu apa yang terjadi pada baris ber-``disclose`` bila modul ini dicopot.
Pilihannya ``cascade`` dan itu disengaja — baris pelepasan informasi hanya
bermakna bila modul yang mencatatnya ada. Menyisakan baris yatim dengan nilai
yang tidak lagi dikenal daftar Selection lebih buruk daripada tidak ada baris.

Kenapa pelepasan dicatat sebagai akses, bukan sebagai kolom di
``hms.roi.request`` saja: pertanyaan yang ditanyakan auditor bukan "permintaan
apa saja yang pernah masuk", melainkan "siapa saja yang pernah melihat rekam
medis pasien ini". Jawaban itu hanya lengkap kalau pelepasan informasi ada di
tabel yang sama dengan pembacaan layar.
"""
from odoo import fields, models


class HmsAccessLog(models.Model):
    _inherit = "hms.access.log"

    action = fields.Selection(
        selection_add=[("disclose", "Pelepasan Informasi")],
        ondelete={"disclose": "cascade"},
    )
