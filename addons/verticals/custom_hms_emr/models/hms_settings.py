# -*- coding: utf-8 -*-
"""Parameter kewenangan klinis yang dipakai modul ini.

Tenggat tanda tangan perintah lisan adalah kebijakan rumah sakit yang
dituliskan dalam SPO, bukan konstanta. Angka default 24 jam mengikuti standar
akreditasi (STARKES SKP 2: konfirmasi pemberi perintah dalam 1x24 jam).
"""
from odoo import fields, models


class HmsSettings(models.Model):
    _inherit = "hms.settings"

    verbal_order_confirm_hours = fields.Integer(
        "Batas konfirmasi perintah lisan (jam)", default=24,
        help="Tenggat tanda tangan pemberi perintah atas instruksi lisan/telepon "
             "yang sudah dibacakan ulang. Standar akreditasi lazim menerapkan "
             "1x24 jam. Lewat tenggat, perintah ditandai 'Lewat Batas Tanda "
             "Tangan' — ditagih, BUKAN diblokir, karena pasien sudah menerima "
             "tindakannya.",
    )
