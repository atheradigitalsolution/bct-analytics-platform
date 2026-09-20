# -*- coding: utf-8 -*-
"""Links an observation to the admission it was taken during."""
from odoo import fields, models


class HmsObservation(models.Model):
    _inherit = "hms.observation"

    admission_id = fields.Many2one(
        "hms.admission", "Admisi", index=True,
        help="Diisi untuk observasi yang diambil selama rawat inap; "
             "papan pasien nurse station membacanya per admisi, bukan per kunjungan.",
    )
