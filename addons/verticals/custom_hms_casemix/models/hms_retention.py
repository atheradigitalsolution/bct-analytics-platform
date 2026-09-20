# -*- coding: utf-8 -*-
"""Melengkapi pengecualian retensi dengan pemeriksaan klaim yang sungguhan.

``custom_hms_medrec`` mendefinisikan ``_has_active_claim`` sebagai hook yang
mengembalikan ``False`` — bukan karena tidak ada klaim, melainkan karena modul
itu tidak punya cara mengetahuinya, dan menuliskannya apa adanya lebih jujur
daripada menebak. Di sinilah jawabannya diisi.

"Berjalan" didefinisikan sebagai: klaim yang belum selesai secara finansial.
Klaim ``paid`` sudah tuntas; ``rejected`` dan ``expired`` sudah tidak akan
menghasilkan uang lagi dan kerugiannya dibukukan lewat
``hms.claim.adjustment``. Sisanya — termasuk ``dispute`` yang bisa berjalan
berbulan-bulan lewat tiga tingkat — masih bisa menuntut berkasnya dibuka.
"""
from odoo import api, models

SETTLED_CLAIM_STATES = ("paid", "rejected", "expired")


class HmsRetentionReview(models.Model):
    _inherit = "hms.retention.review"

    def _has_active_claim(self):
        self.ensure_one()
        if not self.patient_id:
            return False
        return bool(self.env["hms.claim"].sudo().search_count([
            ("patient_id", "=", self.patient_id.id),
            ("state", "not in", SETTLED_CLAIM_STATES),
        ]))

    @api.depends("patient_id", "legal_hold")
    def _compute_exception(self):
        """Dependensi tidak bisa menunjuk klaim, jadi disebut terang-terangan.

        ``has_active_claim`` tersimpan, tetapi ia bergantung pada tabel lain
        yang tidak ada di ``_depends``: menambahkan ``hms.claim.state`` ke
        dependensi akan memaksa recompute seluruh daftar tinjauan setiap kali
        satu klaim berpindah status. Karena itu nilainya dihitung ulang tepat
        sebelum keputusan diambil (``action_review``), dan itu titik yang
        benar-benar penting.
        """
        return super()._compute_exception()
