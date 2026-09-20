# -*- coding: utf-8 -*-
"""Peran pihak dalam rantai logistik.

Satu partner kerap memegang beberapa peran sekaligus — sebuah PT bisa menjadi
pelanggan sekaligus vendor trucking sekaligus depo. Karena itu perannya adalah
Boolean berdampingan, bukan satu Selection: memaksa satu peran akan membuat
staf membuat partner kembar, dan piutang orang yang sama jadi tercecer di dua
kartu.

Identitas kepabeanan memakai NIB + NPWP + jenis akses. PMK 219/2019 mengganti
konsep NIK/NP PPJK dengan Akses Kepabeanan yang melekat pada NIB dan NPWP, jadi
tidak ada field "NIK Kepabeanan" di sini — dan tidak boleh ditambahkan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CUSTOMS_ACCESS_TYPES = [
    ("importer", "Importir"),
    ("exporter", "Eksportir"),
    ("ppjk", "PPJK"),
    ("carrier", "Pengangkut"),
    ("ftz", "Pengusaha FTZ"),
    ("pjt", "PJT"),
    ("tps", "Pengusaha TPS"),
    ("tpb", "Penyelenggara/Pengusaha TPB"),
    ("kite", "Penerima Fasilitas KITE"),
]


class ResPartner(models.Model):
    _inherit = "res.partner"

    lgx_is_carrier = fields.Boolean("Carrier / Pelayaran")
    lgx_is_agent = fields.Boolean("Agen Luar Negeri")
    lgx_is_shipper = fields.Boolean("Shipper")
    lgx_is_consignee = fields.Boolean("Consignee")
    lgx_is_depot = fields.Boolean("Depo / Terminal")
    lgx_is_ppjk = fields.Boolean("PPJK")
    lgx_is_warehouse_client = fields.Boolean("Pemilik Barang (Gudang)")

    lgx_scac = fields.Char("Kode SCAC", size=4, help="Standard Carrier Alpha Code, untuk carrier laut.")
    lgx_iata_code = fields.Char("Kode IATA", size=3, help="Untuk carrier udara.")
    lgx_nib = fields.Char("NIB", size=13, help="Nomor Induk Berusaha dari OSS. 13 digit.")
    lgx_customs_access_type = fields.Selection(
        CUSTOMS_ACCESS_TYPES, string="Jenis Akses Kepabeanan",
        help="PMK 219/2019. Akses Kepabeanan melekat pada NIB + NPWP; tidak ada "
             "lagi NIK Kepabeanan sebagai identitas utama.",
    )
    lgx_nitku = fields.Char(
        "NITKU", size=22,
        help="Nomor Identitas Tempat Kegiatan Usaha, 22 digit "
             "(16 digit NPWP/NIK + 6 digit urut TKU). Menggantikan NPWP cabang.",
    )
    lgx_agent_profit_share = fields.Float(
        "Bagi Hasil Agen (%)",
        help="Porsi agen atas laba job nominasi. Dipakai custom_lgx_ff untuk "
             "membentuk baris biaya bagian agen, agar tidak terlupakan.",
    )
    lgx_free_days_demurrage = fields.Integer(
        "Masa Bebas Demurrage (hari)",
        help="Default dari kontrak carrier ini. Dapat ditimpa per kontainer.",
    )
    lgx_free_days_detention = fields.Integer("Masa Bebas Detensi (hari)")

    @api.constrains("lgx_nib")
    def _check_lgx_nib(self):
        for rec in self:
            if rec.lgx_nib and (not rec.lgx_nib.isdigit() or len(rec.lgx_nib) != 13):
                raise ValidationError(_("NIB harus 13 digit angka. Nilai: %s", rec.lgx_nib))

    @api.constrains("lgx_nitku")
    def _check_lgx_nitku(self):
        for rec in self:
            if rec.lgx_nitku and (not rec.lgx_nitku.isdigit() or len(rec.lgx_nitku) != 22):
                raise ValidationError(_("NITKU harus 22 digit angka. Nilai: %s", rec.lgx_nitku))

    def lgx_has_valid_npwp(self):
        """True bila NPWP 16 digit tersedia.

        Dipakai penentuan tarif PPh 23: tanpa NPWP tarifnya 100% lebih tinggi.
        Yang diuji selalu NPWP PENERIMA penghasilan — pada bukti potong keluaran
        itu berarti vendor, pada potongan yang diterima itu berarti cabang kita
        sendiri. Menguji partner yang salah menghasilkan tarif yang salah setiap
        kali salah satu pihak tidak ber-NPWP.
        """
        self.ensure_one()
        digits = "".join(ch for ch in (self.vat or "") if ch.isdigit())
        return len(digits) == 16
