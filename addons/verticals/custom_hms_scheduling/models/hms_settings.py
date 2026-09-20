# -*- coding: utf-8 -*-
"""Parameter kebijakan penjadwalan.

Dua angka yang sebelumnya tidak punya rumah. Keduanya kebijakan rumah sakit,
bukan norma nasional, jadi keduanya tinggal di ``hms.settings`` dan bukan di
dalam kode — poli mata yang memanggil pasien per gelombang mingguan tidak
punya toleransi yang sama dengan poli dengan slot per jam.
"""
from odoo import fields, models


class HmsSettings(models.Model):
    _inherit = "hms.settings"

    followup_missed_grace_days = fields.Integer(
        "Toleransi rencana kontrol (hari)", default=3,
        help="Berapa hari setelah tanggal rencana sebuah kontrol masih "
             "dianggap mungkin dipenuhi sebelum ditandai 'tidak datang'. "
             "Kebijakan internal RS; isi 0 untuk mematikan penandaan otomatis.",
    )
    procedure_default_minutes = fields.Integer(
        "Durasi tindakan default (menit)", default=60,
        help="Perkiraan durasi yang dipakai saat menjadwalkan tindakan bila "
             "item tarifnya belum mengisi 'Durasi (menit)'. Acuan untuk "
             "menata papan operasi, bukan batas keras.",
    )
