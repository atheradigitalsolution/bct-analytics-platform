# -*- coding: utf-8 -*-
"""Parameter casemix yang belum ada, dan satu efek samping yang disengaja.

Lima parameter yang dipakai modul ini — ``claim_expiry_months``,
``claim_variance_threshold``, ``readmission_window_days``,
``fragmentation_window_days``, ``grouper_mode`` — **sudah** ada di
``custom_hms_base`` dan tidak diduplikasi. Yang ditambahkan hanya tiga angka
yang lahir bersama alur di sini, dan yang ketiga
(``claim_adjustment_authorization_limit``) sengaja tidak menumpang pada
``claim_variance_threshold``; alasannya ditulis di
``models/hms_claim_adjustment.py``.

=============================================================================
KEPUTUSAN: MENGUBAH `claim_expiry_months` MENGGESER TENGGAT KLAIM YANG BELUM
DIAJUKAN — DAN HANYA YANG BELUM DIAJUKAN
=============================================================================

``hms.claim.deadline_at`` tidak dihitung ulang dari pengaturan setiap kali
dibaca; ia tersimpan, dihitung dari ``expiry_months_applied`` yang dibekukan
di masing-masing klaim. Alasannya sama dengan tenggat KLPCM dan tenggat IKP:
sebuah tenggat adalah bukti kepatuhan pada saat itu, dan tenggat yang bergeser
sendiri setiap kali seseorang menyentuh layar pengaturan tidak membuktikan
apa-apa.

Tapi membekukan semuanya juga salah. Kalau rumah sakit mengoreksi parameter
yang keliru (mis. tertulis 3 bulan padahal Perpres 82/2018 Ps. 77 memberi 6),
klaim yang masih di meja koder harus ikut terkoreksi — kalau tidak, koreksi
itu hanya berlaku untuk pasien yang belum datang.

Jadi pembatasnya bukan waktu, melainkan **apakah klaim sudah keluar dari
rumah sakit**: selama masih di state pra-pengajuan, tenggatnya ikut bergeser;
begitu diajukan ke BPJS, ia beku. ``write`` di bawah inilah yang
mewujudkannya, dan tesnya membuktikan keduanya.
"""
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class HmsSettings(models.Model):
    _inherit = "hms.settings"

    claim_pending_escalation_days = fields.Integer(
        "Eskalasi klaim pending (hari)", default=60,
        help="Lama sebuah klaim boleh berstatus pending sebelum dieskalasi ke "
             "manajemen. TIDAK ADA NORMA NASIONAL untuk angka ini; 60 hari "
             "dipakai sebagai kebijakan internal karena klaim yang menua "
             "melewati separuh masa kedaluwarsa 6 bulan sudah kehilangan "
             "ruang untuk diperbaiki dua kali.",
    )
    claim_adjustment_authorization_limit = fields.Float(
        "Plafon otorisasi penyesuaian klaim (Rp)", default=500000.0, digits=(16, 2),
        help="Penyesuaian klaim sampai dengan nilai ini boleh disahkan "
             "Verifikator Internal Casemix; di atasnya wajib manajemen. "
             "TIDAK ADA NORMA NASIONAL untuk angka ini — ia batas materialitas "
             "internal rumah sakit, dan nol berarti seluruh penyesuaian naik "
             "ke manajemen. Sengaja BUKAN claim_variance_threshold: yang itu "
             "mengukur selisih tarif untuk memicu review empat mata, bukan "
             "wewenang mengesahkan kerugian.",
    )
    claim_dispute_sla_days = fields.Integer(
        "SLA penyelesaian dispute per tingkat (hari kerja)", default=10,
        help="Alur dispute berjenjang Kantor Cabang -> Kedeputian Wilayah -> "
             "Pusat, masing-masing dengan batas waktu. Angka default 10 hari "
             "kerja mengikuti praktik yang lazim dikutip, BUKAN kutipan "
             "peraturan yang sudah diverifikasi — konfirmasikan ke KC BPJS "
             "wilayah.",
    )

    def write(self, vals):
        res = super().write(vals)
        if "claim_expiry_months" in vals:
            self.env["hms.claim"]._sync_expiry_months(self)
        return res
