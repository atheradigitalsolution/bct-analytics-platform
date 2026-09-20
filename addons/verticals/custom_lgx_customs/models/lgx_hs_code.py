# -*- coding: utf-8 -*-
"""HS code BTKI dan tarifnya.

Tarif disimpan PER HS CODE dengan masa berlaku, bukan sebagai konstanta, karena
BTKI berubah dan deklarasi lama harus tetap dapat direkonstruksi dengan tarif
yang berlaku pada tanggal pendaftarannya.

`lartas_flag` menandai larangan dan pembatasan. Ia tidak memblokir apa pun
sendiri — ia memunculkan daftar izin yang dibutuhkan, karena yang menghalangi
pengiriman bukan HS code-nya melainkan izin yang belum ada.

A25 DITUTUP (diperiksa 2026-09-20) — sumber dan ukurannya.

BTKI 2022 ditetapkan PMK 26/PMK.010/2022, berlaku 1 April 2022, memuat
99 bab dan **11.552 pos tarif** 8 digit (BTKI 2017: 10.841). Sumber resmi
untuk penelusuran: portal INSW (insw.go.id), Inatrade (Kemendag), dan
beacukai.go.id/btki.html. INSW yang paling lengkap untuk keperluan kami —
ia menyertakan bea masuk, PPh impor, lartas, dan fasilitas FTA sekaligus.

MODUL INI MEMUAT DELAPAN. Bukan 11.552, dan angka itu disebut supaya selisih
1.444 kali lipatnya tidak pernah disalahpahami sebagai "hampir lengkap".
Kedelapannya contoh untuk demo dan uji; muat sisanya lewat `lgx_import_csv`
dari unduhan INSW.

Yang membuat kekosongan ini AMAN adalah bentuk modelnya, bukan niat baik:
deklarasi menunjuk `hs_code_id` sebagai Many2one wajib, jadi pos tarif yang
belum dimuat tidak dapat dipilih dan tidak dapat diam-diam dianggap nol. Yang
tidak ada TERLIHAT tidak ada. Kalau tarif suatu saat jatuh ke bawaan nol
ketika HS code tidak ditemukan, sifat aman itu hilang dan seluruh perhitungan
bea menjadi nol yang tampak wajar.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxHsCode(models.Model):
    _name = "lgx.hs.code"
    _description = "HS Code / BTKI"
    _order = "code"
    _rec_name = "code"

    code = fields.Char("HS Code", required=True, index=True, help="8 digit BTKI, mis. 8471.30.20.")
    name = fields.Char("Uraian", required=True)
    section = fields.Char("Bagian")
    chapter = fields.Char("Bab")
    uom_id = fields.Many2one("uom.uom", "Satuan Pabean")

    bm_rate = fields.Float("Bea Masuk (%)", digits=(5, 2))
    bm_specific = fields.Float("Bea Masuk Spesifik (per satuan)",
                               help="Untuk pos tarif yang dikenai bea masuk spesifik, bukan ad valorem.")
    ppn_rate = fields.Float("PPN Impor (%)", digits=(5, 2), default=11.0)
    ppnbm_rate = fields.Float("PPnBM (%)", digits=(5, 2))
    pph22_rate = fields.Float("PPh 22 Impor (%)", digits=(5, 2), default=2.5)
    pph22_rate_no_api = fields.Float(
        "PPh 22 tanpa API (%)", digits=(5, 2), default=7.5,
        help="Importir tanpa Angka Pengenal Importir dikenai tarif lebih tinggi.",
    )

    lartas_flag = fields.Boolean("Lartas (Larangan & Pembatasan)")
    permit_note = fields.Text("Izin yang Dibutuhkan")
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "HS code harus unik.")
    # Kelima tarif, bukan tiga. Versi sebelumnya menjaga bm_rate, ppn_rate, dan
    # pph22_rate lalu melewatkan ppnbm_rate serta pph22_rate_no_api — penjaga
    # yang dipasang di satu tempat dan terlupa di tempat lain pada model yang
    # sama. Keduanya mengalikan dasar pungutan sama seperti tiga yang lain.
    #
    # TIDAK ada batas atas, dan itu disengaja: tarif PPnBM dapat mencapai
    # ratusan persen untuk barang mewah, dan batas maksimum menurut undang-
    # undang belum kami verifikasi ke sumber primer. Menebak angka batas lalu
    # menolak data yang sah lebih buruk daripada tidak membatasi — yang salah
    # ketik akan tertangkap perbandingan terhadap BTKI, bukan oleh constraint
    # yang dikarang.
    _rates_sane = models.Constraint(
        "check(bm_rate >= 0 and ppn_rate >= 0 and ppnbm_rate >= 0 "
        "and pph22_rate >= 0 and pph22_rate_no_api >= 0)",
        "Tarif pungutan impor tidak boleh negatif.",
    )

    @api.constrains("code")
    def _check_code(self):
        for record in self:
            digits = (record.code or "").replace(".", "")
            if digits and not digits.isdigit():
                raise ValidationError(_(
                    "HS code '%s' hanya boleh angka dan titik pemisah.", record.code,
                ))

    @api.depends("code", "name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.code} — {record.name}"
