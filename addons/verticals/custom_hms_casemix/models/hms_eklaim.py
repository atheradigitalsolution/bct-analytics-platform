# -*- coding: utf-8 -*-
"""Dua titik masuk E-Klaim yang sengaja DIBIARKAN KOSONG.

=============================================================================
KENAPA MODUL INI TIDAK MEMBANGUN BRIDGING E-KLAIM
=============================================================================

Manual resmi web service E-Klaim 5.10.x dari Kemenkes belum ada di tangan.
Yang tersedia hanyalah potongan implementasi pihak ketiga dan tulisan blog,
dan keduanya bukan sumber yang sah untuk membangun jalur yang mengirim uang.

Yang TIDAK ditulis di modul ini, dan alasannya:

* **Enumerasi** ``jenis_rawat``, ``cara_masuk``, ``discharge_status``,
  ``kode_tarif``, ``payor_id``, dan 18 komponen ``tarif_rs``. Sebuah
  ``Selection`` dengan kunci tebakan menyimpan nilai yang harus dimigrasi
  begitu daftar resminya datang — dan migrasi diam-diam atas data pemetaan
  klaim adalah cara yang sangat rapi untuk salah menagih ribuan berkas
  sekaligus. Karena itu ``hms.eklaim.code`` menyimpan kategori dan kode
  sebagai teks bebas yang **diimpor**, bukan sebagai daftar yang dikarang.
* **Payload ``set_claim_data``, enkripsi AES-256-CBC, pemanggilan
  ``ws.php``.** Payload yang formatnya ditebak tidak akan gagal dengan
  jelas; ia akan diterima sebagian, menghasilkan grouping yang salah, dan
  kesalahannya baru ketahuan berbulan-bulan kemudian sebagai klaim pending.
  Lebih baik tidak punya tombol sama sekali daripada punya tombol yang
  berbohong.
* **Kunci enkripsi.** Tidak ada kolomnya di sini. Menyediakan tempat
  menyimpan kunci sebelum ada yang memakainya hanya menciptakan rahasia yang
  menganggur di basis data.

Yang ADA: tempat menaruh jawabannya begitu manualnya datang, dengan ``help``
yang menyatakan statusnya terang-terangan supaya tidak ada yang mengira
kolom kosong ini adalah bug.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsEklaimCode(models.Model):
    _name = "hms.eklaim.code"
    _description = "Master Kode E-Klaim (diimpor dari manual resmi)"
    _order = "category, sequence, code"
    _rec_names_search = ["code", "label"]

    # Char, bukan Selection — untuk kategorinya sendiri pun. Daftar kategori
    # E-Klaim belum terverifikasi, dan sebuah Selection kategori yang salah
    # akan membuat seluruh impor gagal dengan pesan yang menyesatkan.
    category = fields.Char(
        "Kategori", required=True, index=True,
        help="Nama kelompok enumerasi persis seperti tertulis di manual resmi "
             "E-Klaim, mis. jenis_rawat, cara_masuk, discharge_status, "
             "kode_tarif, payor_id, tarif_rs. DAFTAR KATEGORI DI ATAS BELUM "
             "TERVERIFIKASI — ia contoh penamaan, bukan daftar yang harus "
             "dipakai. Isi apa adanya dari manual.",
    )
    code = fields.Char(
        "Kode", required=True, index=True,
        help="Nilai yang dikirim ke E-Klaim, persis seperti di manual "
             "(perhatikan huruf besar/kecil).",
    )
    label = fields.Char("Uraian", required=True)
    sequence = fields.Integer(default=10)
    note = fields.Text(
        "Catatan",
        help="Halaman/versi manual asal kode ini. Diisi supaya kode yang "
             "keliru bisa ditelusuri ke sumbernya, bukan ke ingatan orang.",
    )
    source_document = fields.Char(
        "Dokumen Sumber",
        help="Judul dan versi manual resmi tempat kode ini dibaca, mis. "
             "'Petunjuk Teknis WS E-Klaim 5.10.1'. Kosong berarti kode ini "
             "belum bisa dipertanggungjawabkan.",
    )
    active = fields.Boolean(default=True)

    _category_code_uniq = models.Constraint(
        "unique(category, code)",
        "Kode E-Klaim harus unik dalam satu kategori.",
    )

    @api.depends("code", "label")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.label}"


class HmsEklaimConfig(models.Model):
    _name = "hms.eklaim.config"
    _description = "Parameter Koneksi E-Klaim (menunggu manual resmi)"
    _order = "id"

    name = fields.Char(default="Parameter E-Klaim", required=True)
    company_id = fields.Many2one("res.company", required=True,
                                 default=lambda s: s.env.company, ondelete="cascade")

    # Semua kolom di bawah ini sengaja TANPA default. Nilai bawaan pada
    # parameter koneksi klaim adalah tebakan yang menyamar sebagai konfigurasi:
    # ia akan lolos ke produksi karena "sudah terisi".
    base_url = fields.Char(
        "URL Layanan E-Klaim",
        help="Alamat web service E-Klaim rumah sakit ini. KOSONG SECARA "
             "SENGAJA — menunggu manual resmi dan alamat dari Kemenkes/klien. "
             "Modul ini belum memanggil layanan apa pun.",
    )
    kode_tarif = fields.Char(
        "Kode Tarif RS",
        help="Kode tarif yang dipakai grouper untuk rumah sakit ini. Enumerasi "
             "resminya BELUM TERVERIFIKASI (manual E-Klaim 5.10.x belum ada); "
             "isi persis seperti yang tertulis di manual, jangan ditebak.",
    )
    payor_id = fields.Char(
        "Payor ID",
        help="Identitas penjamin pada E-Klaim. Enumerasi resminya BELUM "
             "TERVERIFIKASI — isi dari manual resmi.",
    )
    default_coder_nik = fields.Char(
        "NIK Koder Bawaan",
        help="NIK koder yang dikirim saat finalisasi klaim. Dipakai hanya bila "
             "koder yang mengerjakan belum punya NIK tercatat.",
    )
    # Dibaca ulang dari hms.settings, bukan disalin ke kolom sendiri: mode
    # grouper adalah keputusan rumah sakit yang sudah punya tempatnya. Dua
    # sumber kebenaran untuk satu keputusan berarti salah satunya pasti
    # kedaluwarsa, dan yang kedaluwarsa itu selalu yang dibaca mesin.
    grouper_mode = fields.Char(
        "Mode Grouper", compute="_compute_grouper_mode", readonly=True,
        help="Dibaca dari Pengaturan SIMRS (hms.settings.grouper_mode). Diubah "
             "di sana, bukan di sini.",
    )
    readiness_note = fields.Text(
        "Status Kesiapan", compute="_compute_readiness_note",
        help="Ringkasan apa yang masih kurang sebelum bridging E-Klaim bisa "
             "dibangun sama sekali.",
    )

    _company_uniq = models.Constraint(
        "unique(company_id)",
        "Parameter E-Klaim hanya boleh satu per perusahaan.",
    )

    def _compute_grouper_mode(self):
        settings = self.env["hms.settings"].get_settings()
        label = dict(settings._fields["grouper_mode"].selection).get(
            settings.grouper_mode, settings.grouper_mode
        )
        for rec in self:
            rec.grouper_mode = label

    @api.depends("base_url", "kode_tarif", "payor_id")
    def _compute_readiness_note(self):
        for rec in self:
            missing = []
            if not rec.base_url:
                missing.append(_("URL layanan"))
            if not rec.kode_tarif:
                missing.append(_("kode tarif"))
            if not rec.payor_id:
                missing.append(_("payor id"))
            code_count = self.env["hms.eklaim.code"].search_count([])
            if not code_count:
                missing.append(_("master kode E-Klaim (belum ada satu pun baris)"))
            if missing:
                rec.readiness_note = _(
                    "Belum siap. Yang belum terisi: %s.\n\n"
                    "Bridging E-Klaim BELUM dibangun di sistem ini, dan tidak "
                    "akan dibangun dari tebakan: enumerasi serta format payload "
                    "menunggu manual resmi WS E-Klaim 5.10.x dari Kemenkes. "
                    "Sampai manual itu ada, klaim disusun, diverifikasi dan "
                    "difinalkan di dalam SIMRS lalu dikirim lewat aplikasi "
                    "E-Klaim seperti biasa."
                ) % ", ".join(missing)
            else:
                rec.readiness_note = _(
                    "Parameter sudah terisi. Bridging otomatis tetap BELUM "
                    "dibangun — parameter ini disiapkan untuk pekerjaan "
                    "berikutnya, bukan bukti bahwa jalurnya sudah ada."
                )

    @api.constrains("default_coder_nik")
    def _check_nik_length(self):
        for rec in self:
            if rec.default_coder_nik and len(rec.default_coder_nik) != 16:
                raise ValidationError(_("NIK harus 16 digit."))

    @api.model
    def get_config(self):
        rec = self.sudo().search([("company_id", "=", self.env.company.id)], limit=1)
        if not rec:
            rec = self.sudo().create({"company_id": self.env.company.id})
        return rec
