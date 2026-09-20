# -*- coding: utf-8 -*-
"""Master tarif pot-put yang berlaku pada tanggal transaksi.

Kuncinya netral terhadap angka (``pph23``, ``pph15_sea``, ...), dan ANGKANYA
hidup di sini dengan masa berlaku. Itulah yang membuat perubahan tarif tidak
menjadi migrasi nilai selection — dan transaksi lama tetap dapat direkonstruksi
dengan tarif yang berlaku saat itu.

⚠ Sifat final PPh 15 penerbitan dalam negeri: butir A4 di Lampiran A sudah
DITUTUP. Sumber DJP (SE-35/PJ.4/1996) menyatakan 1,8% penerbangan dalam negeri
TIDAK final dan dapat dikreditkan terhadap PPh terutang di SPT Tahunan. Banyak
sumber sekunder menyebutnya final; sumber sekunder itu keliru.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.custom_lgx_base.models.lgx_charge_code import WHT_TYPES


class LgxWhtRate(models.Model):
    _name = "lgx.wht.rate"
    _description = "Tarif Pot-Put Logistik"
    _order = "wht_type, valid_from desc"

    name = fields.Char("Nama", required=True)
    wht_type = fields.Selection(WHT_TYPES, string="Jenis", required=True, index=True)
    rate = fields.Float("Tarif (%)", digits=(5, 2), required=True)
    rate_no_npwp = fields.Float(
        "Tarif tanpa NPWP (%)", digits=(5, 2),
        help="UU PPh Pasal 23 ayat 1a: 100% lebih tinggi bila PENERIMA PENGHASILAN "
             "tidak ber-NPWP. Yang diuji NPWP penerima, bukan lawan transaksi.",
    )
    is_final = fields.Boolean(
        "Bersifat Final",
        help="PPh 15 pelayaran dalam negeri final; penerbangan dalam negeri TIDAK "
             "final dan dapat dikreditkan (SE-35/PJ.4/1996).",
    )
    legal_basis = fields.Char("Dasar Hukum")
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_to = fields.Date("Berlaku Sampai")
    company_id = fields.Many2one("res.company", "Perusahaan", index=True,
                                 help="Kosong berarti berlaku untuk semua perusahaan.")
    active = fields.Boolean(default=True)

    _rate_range = models.Constraint(
        "check(rate >= 0 and rate <= 100 and rate_no_npwp >= 0 and rate_no_npwp <= 100)",
        "Tarif pot-put harus antara 0 dan 100 persen.",
    )
    _period_valid = models.Constraint(
        "check(valid_to is null or valid_to >= valid_from)",
        "Masa berlaku tarif tidak boleh berakhir sebelum dimulai.",
    )

    @api.model
    def lgx_find(self, wht_type, on_date=None, company=None):
        """Tarif yang berlaku pada tanggal transaksi.

        Memakai tanggal transaksi dan bukan hari ini, supaya faktur lama yang
        dibuka kembali tidak diam-diam memakai tarif baru.
        """
        on_date = on_date or fields.Date.context_today(self)
        company = company or self.env.company
        return self.search([
            ("wht_type", "=", wht_type),
            ("valid_from", "<=", on_date),
            "|", ("valid_to", "=", False), ("valid_to", ">=", on_date),
            "|", ("company_id", "=", False), ("company_id", "=", company.id),
        ], order="company_id desc, valid_from desc", limit=1)
