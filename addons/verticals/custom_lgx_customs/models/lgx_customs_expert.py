# -*- coding: utf-8 -*-
"""Ahli Kepabeanan bersertifikat.

Dua aturan dari PMK 219/2019 yang langsung menjadi constraint:

1. PPJK wajib memiliki pegawai berkualifikasi Ahli Kepabeanan bersertifikat.
2. **Satu ahli hanya boleh melayani satu PPJK.** Itu ditegakkan di Postgres, bukan
   hanya diingatkan di layar.

Pemeriksaan masa berlaku sertifikat ada di sini dan bukan menunggu mesin
peringatan generik di `custom_lgx_doc`: LGX-C01 menuntut deklarasi DITOLAK bila
sertifikat ahlinya kedaluwarsa, dan aturan yang menahan uang tidak boleh
menunggu fase berikutnya.

BUTIR A8 MASIH TERBUKA, dan sengaja tidak ditutup dengan jawaban yang salah
(diperiksa 2026-09-20). Pencarian tentang "masa berlaku sertifikat ahli
kepabeanan" mengembalikan angka **2 tahun** yang tampak meyakinkan. Angka itu
adalah KETENTUAN PERALIHAN PMK 219/2019 — jendela dua tahun sejak PMK berlaku
bagi pemegang sertifikat lama untuk mengajukan izin spesialis kepabeanan, dan
jendela itu sudah lewat. Ia bukan masa berlaku sertifikatnya.

Mencatatnya sebagai masa berlaku akan mengulang persis kekeliruan yang menutup
butir A4, hanya ke arah sebaliknya. Yang masih perlu dibaca: ketentuan BPPK
Kemenkeu tentang sertifikasi Ahli Kepabeanan, bukan PMK registrasinya.

Untungnya ini tidak memblokir apa pun. `certificate_expiry` disalin dari
sertifikatnya, tidak pernah dihitung dari masa berlaku — sama seperti KIR dan
Kartu Pengawasan di `custom_lgx_fleet`. Selama tanggalnya datang dari dokumen,
tidak tahu berapa lama masa berlakunya tidak membuat sistem salah; ia hanya
membuat kita tidak bisa memperingatkan lebih awal untuk sertifikat yang
tanggalnya belum diisi.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxCustomsExpert(models.Model):
    _name = "lgx.customs.expert"
    _description = "Ahli Kepabeanan"
    _order = "name"

    name = fields.Char("Nama", required=True)
    employee_id = fields.Many2one("res.partner", "Kartu Pegawai")
    user_id = fields.Many2one("res.users", "Pengguna Odoo")
    certificate_no = fields.Char("Nomor Sertifikat", required=True, index=True)
    certificate_date = fields.Date("Tanggal Sertifikat")
    certificate_expiry = fields.Date("Masa Berlaku Sertifikat")
    npwp = fields.Char("NPWP", size=16)
    ppjk_partner_id = fields.Many2one(
        "res.partner", "PPJK", domain="[('lgx_is_ppjk','=',True)]", required=True,
        help="Satu ahli hanya boleh melayani SATU PPJK (PMK 219/2019).",
    )
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company)
    is_expired = fields.Boolean("Kedaluwarsa", compute="_compute_is_expired", store=True)
    days_to_expiry = fields.Integer("Sisa Hari", compute="_compute_is_expired", store=True)
    active = fields.Boolean(default=True)

    _certificate_uniq = models.Constraint(
        "unique(certificate_no)", "Nomor sertifikat Ahli Kepabeanan harus unik.",
    )
    _one_ppjk_per_expert = models.Constraint(
        "unique(certificate_no, ppjk_partner_id)",
        "Satu ahli hanya boleh terdaftar pada satu PPJK.",
    )

    @api.depends("certificate_expiry")
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for expert in self:
            if expert.certificate_expiry:
                expert.days_to_expiry = (expert.certificate_expiry - today).days
                expert.is_expired = expert.certificate_expiry < today
            else:
                expert.days_to_expiry = 0
                expert.is_expired = False

    @api.constrains("certificate_no", "ppjk_partner_id")
    def _check_single_ppjk(self):
        """Satu nomor sertifikat, satu PPJK. Diperiksa juga lintas record aktif-nonaktif."""
        for expert in self:
            duplicate = self.with_context(active_test=False).search([
                ("id", "!=", expert.id),
                ("certificate_no", "=", expert.certificate_no),
                ("ppjk_partner_id", "!=", expert.ppjk_partner_id.id),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    "Ahli Kepabeanan dengan sertifikat %s sudah terdaftar pada PPJK %s. "
                    "Satu ahli hanya boleh melayani satu PPJK (PMK 219/2019).",
                    expert.certificate_no, duplicate.ppjk_partner_id.display_name,
                ))
