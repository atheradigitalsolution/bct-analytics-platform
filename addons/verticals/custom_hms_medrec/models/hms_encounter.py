# -*- coding: utf-8 -*-
"""Pemicu analisis kelengkapan, dipasang di ``write`` dan bukan di ``action_close``.

Ada dua jalan sebuah kunjungan berhenti dilayani, dan keduanya nyata:

1. ``hms.encounter.action_close()`` — rawat jalan/IGD selesai (``finished``);
2. ``hms.admission.action_discharge()`` — pasien rawat inap pulang, dan
   modul rawat inap menulis ``state = 'discharged'`` **langsung ke encounter**
   tanpa melewati ``action_close``.

Menempel pada ``action_close`` saja berarti tidak satu pun berkas rawat inap
pernah dianalisis — persis berkas yang paling sering tidak lengkap dan paling
mahal bila klaimnya dikembalikan. Karena itu pemicunya dipasang pada transisi
*state*, bukan pada nama metode: apa pun yang membuat kunjungan menjadi
``finished``/``discharged`` akan menjalankan analisis.

Analisis dijalankan lewat ``postcommit``? **Tidak.** Sengaja di dalam
transaksi yang sama: bila pemulangan pasien di-rollback, baris KLPCM-nya harus
ikut hilang. Analisis hanya melakukan pembacaan dan penulisan baris kecil;
biayanya jauh di bawah biaya pemulangan itu sendiri.
"""
from odoo import api, fields, models

CLOSED_STATES = ("finished", "discharged")


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    klpcm_ids = fields.One2many("hms.klpcm", "encounter_id", "Temuan KLPCM")
    klpcm_open_count = fields.Integer(
        "KLPCM Terbuka", compute="_compute_klpcm_open_count", store=True,
        help="Selama angka ini bukan nol, kunjungan belum boleh masuk koding klaim.",
    )

    @api.depends("klpcm_ids.state")
    def _compute_klpcm_open_count(self):
        for enc in self:
            enc.klpcm_open_count = len(enc.klpcm_ids.filtered(lambda k: k.state == "open"))

    def write(self, vals):
        """Jalankan analisis untuk kunjungan yang baru saja berhenti dilayani.

        Yang dibandingkan adalah state *sebelum* dan *sesudah*, bukan sekadar
        "state ada di vals": menulis ``finished`` pada kunjungan yang sudah
        ``finished`` (hal yang terjadi setiap kali layar disimpan ulang) tidak
        boleh memicu apa pun.
        """
        before = {enc.id: enc.state for enc in self}
        res = super().write(vals)
        if "state" not in vals or self.env.context.get("hms_skip_klpcm"):
            return res
        just_closed = self.filtered(
            lambda e: e.state in CLOSED_STATES and before.get(e.id) not in CLOSED_STATES
        )
        if just_closed:
            self.env["hms.klpcm"].analyze_encounter(just_closed)
        return res

    def action_reanalyze_klpcm(self):
        """Analisis ulang manual — dipakai PMIK dari layar kunjungan."""
        self.env["hms.klpcm"].analyze_encounter(self)
        return True
