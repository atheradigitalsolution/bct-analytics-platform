# -*- coding: utf-8 -*-
"""Kurs Menteri Keuangan (NDPBM) dengan masa berlaku.

Butir A26 DITUTUP (diperiksa 2026-09-20). Kurs ini ditetapkan **mingguan**
lewat Keputusan Menteri Keuangan dan berlaku **Rabu pukul 00.00 WIB sampai
Selasa** berikutnya — periodisasi itu berubah dari Senin-Minggu sejak 17
Oktober 2012. Sumber resminya fiskal.kemenkeu.go.id.

Mengapa ia master dan bukan angka yang diketik di dokumen: ``fx_rate_tax``
adalah pengali setiap pungutan impor. Nilai Pabean, Bea Masuk, PPN Impor,
PPnBM, dan PPh 22 semuanya berskala LINEAR terhadapnya. Satu nol yang
kelebihan mengalikan seluruh pungutan sepuluh kali, dan tidak ada satu pun
angka lain di dokumen yang akan terlihat ganjil karenanya — semuanya ikut
bergerak, konsisten dan salah.

Yang TIDAK dibangun, dan disebut supaya tidak disangka ada: penarikan
otomatis terjadwal dari fiskal.kemenkeu.go.id. Situs itu tidak punya kontrak
API yang dapat kami verifikasi, dan penarik yang diam-diam gagal lalu
menyisakan kurs minggu lalu justru menghasilkan kesalahan yang paling sulit
dilihat. Sampai sumbernya pasti, kurs diisi manual — dan ``unknown`` yang
muncul di deklarasi adalah pengingat bahwa ia belum diisi, bukan gangguan.
"""
from odoo import _, api, fields, models


class LgxKmkRate(models.Model):
    _name = "lgx.kmk.rate"
    _description = "Kurs KMK (NDPBM)"
    _order = "valid_from desc, currency_id"
    _rec_name = "kmk_number"

    kmk_number = fields.Char(
        "Nomor KMK", required=True, index=True,
        help="Nomor Keputusan Menteri Keuangan yang menetapkan kurs ini.")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True, index=True)
    rate = fields.Float(
        "Kurs (Rp)", digits=(16, 6), required=True,
        help="Berapa rupiah untuk satu satuan mata uang ini.")
    valid_from = fields.Date(
        "Berlaku Dari", required=True, index=True,
        help="Rabu, sesuai periodisasi NDPBM sejak 17 Oktober 2012.")
    valid_to = fields.Date("Berlaku Sampai", required=True, help="Selasa berikutnya.")
    company_id = fields.Many2one(
        "res.company", "Perusahaan", index=True,
        help="Kosong berarti berlaku untuk semua perusahaan.")
    active = fields.Boolean(default=True)

    _rate_positive = models.Constraint(
        "check(rate > 0)", "Kurs KMK harus lebih besar dari nol.")
    _period_valid = models.Constraint(
        "check(valid_to >= valid_from)",
        "Masa berlaku kurs tidak boleh berakhir sebelum dimulai.")

    @api.model
    def lgx_find(self, currency, on_date=None, company=None):
        """Kurs yang berlaku pada TANGGAL DOKUMEN, bukan hari ini.

        Deklarasi yang dibuka kembali tiga minggu kemudian harus tetap
        menunjukkan kurs yang dipakai saat pendaftaran — kalau tidak,
        rekonsiliasi terhadap SPPB yang sudah terbit tidak akan pernah cocok.
        """
        if not currency:
            return self.browse()
        on_date = on_date or fields.Date.context_today(self)
        company = company or self.env.company
        return self.search([
            ("currency_id", "=", currency.id if hasattr(currency, "id") else currency),
            ("valid_from", "<=", on_date),
            ("valid_to", ">=", on_date),
            "|", ("company_id", "=", False), ("company_id", "=", company.id),
        ], order="company_id desc, valid_from desc", limit=1)

    def name_get(self):
        return [(r.id, _("%s — %s %s", r.kmk_number, r.currency_id.name, r.rate))
                for r in self]
