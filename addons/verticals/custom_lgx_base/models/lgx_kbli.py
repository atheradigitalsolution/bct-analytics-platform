# -*- coding: utf-8 -*-
"""KBLI dua versi, dan pemetaan di antaranya.

KBLI 2025 sudah berlaku (Peraturan BPS No. 7 Tahun 2025) dengan masa transisi
paralel bersama KBLI 2020. Selama masa itu, dokumen perizinan yang sama bisa
menyebut kode berbeda tergantung kapan ia terbit — jadi master ini menyimpan
KEDUA versi beserta pemetaannya, bukan memilih salah satu.

A9 SEBAGIAN TERTUTUP (diperiksa 2026-09-20), dan bagian yang tertutup
membenarkan bentuk model ini sementara bagian yang terbuka jadi lebih mendesak.

TERTUTUP — bentuk konversinya. BPS menerbitkan Tabel Konversi KBLI 2020-2025
(April 2026), dan konversinya TIDAK selalu satu-ke-satu: ada yang tetap, ada
yang berubah, ada yang DIPECAH menjadi beberapa kode lebih spesifik, ada yang
DIGABUNG dari beberapa kode lama. Itu persis alasan `counterpart_ids` berupa
Many2many dan bukan Many2one — kalau ia Many2one, satu kode 2020 yang dipecah
menjadi tiga kode 2025 memaksa seseorang memilih salah satu dan membuang dua.

TERTUTUP — sumbernya. Tabel Konversi BPS, dan konversi otomatis di
oss.go.id/kbli/konversi yang memakai tabel korespondensi yang sama.

MASIH TERBUKA, dan ini yang harus diisi manusia: pemetaan konkret untuk
pergudangan (52101) dan pelayaran (50131). Tidak diisi tebakan. Kode KBLI yang
salah di dokumen perizinan bukan kesalahan kosmetik — ia menentukan tingkat
risiko dan bentuk perizinan yang wajib dipenuhi.

DAN SATU FAKTA YANG MENGUBAH ARTI `is_verified = False`: implementasi nasional
KBLI 2025 di OSS dijadwalkan paling lambat 18 Juni 2026. Tanggal itu SUDAH
LEWAT. Jadi baris 2020 yang belum terpetakan bukan lagi sekadar "belum
dikonfirmasi" — ia berpotensi sudah tidak dipakai untuk perizinan baru, dan
selisih antara keduanya kini menanggung risiko kepatuhan, bukan hanya
ketidakrapian data.

Baris yang belum terkonfirmasi ditandai `is_verified = False` dan TERLIHAT
begitu di layar — bukan disembunyikan di komentar kode yang tidak dibaca siapa
pun. Daftar bawaan sengaja kecil; muat lengkap lewat `lgx.kbli.lgx_import_csv`.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxKbli(models.Model):
    _name = "lgx.kbli"
    _description = "KBLI (Klasifikasi Baku Lapangan Usaha Indonesia)"
    _order = "version desc, code"
    _rec_name = "code"

    version = fields.Selection(
        [("2020", "KBLI 2020"), ("2025", "KBLI 2025")],
        string="Versi", required=True, default="2025", index=True,
    )
    code = fields.Char("Kode", required=True, size=5, index=True)
    name = fields.Char("Nama Kegiatan", required=True)
    section = fields.Char("Kategori", help="Huruf kategori KBLI, mis. H untuk Transportasi.")
    risk_level = fields.Selection(
        [("rendah", "Rendah"), ("menengah_rendah", "Menengah Rendah"),
         ("menengah_tinggi", "Menengah Tinggi"), ("tinggi", "Tinggi")],
        string="Tingkat Risiko",
        help="Menentukan bentuk perizinan: NIB saja, NIB + Sertifikat Standar, atau NIB + Izin.",
    )
    permit_form = fields.Char("Bentuk Perizinan")
    requirement_note = fields.Text(
        "Persyaratan Operasional",
        help="Yang menyentuh master data sistem: KIR, denah pool, fasilitas bongkar muat, GPS.",
    )
    counterpart_ids = fields.Many2many(
        "lgx.kbli", "lgx_kbli_mapping_rel", "from_id", "to_id",
        string="Padanan Versi Lain",
        help="Pemetaan 2020 ⇄ 2025. Many2many karena konversinya tidak selalu satu-ke-satu: "
             "satu kode lama dapat pecah menjadi beberapa kode baru dan sebaliknya.",
    )
    is_verified = fields.Boolean(
        "Terverifikasi ke Sumber", default=False,
        help="False berarti kode atau pemetaannya berasal dari riset sekunder dan belum "
             "dikonfirmasi ke OSS/BPS. Ditampilkan, bukan disembunyikan.",
    )
    source_note = fields.Char("Sumber")
    active = fields.Boolean(default=True)

    _code_version_uniq = models.Constraint(
        "unique(code, version)", "Kode KBLI ini sudah ada untuk versi tersebut.",
    )

    @api.constrains("code")
    def _check_code(self):
        for record in self:
            if record.code and (not record.code.isdigit() or len(record.code) != 5):
                raise ValidationError(_("Kode KBLI harus 5 digit angka. Nilai: %s", record.code))

    @api.depends("code", "name", "version")
    def _compute_display_name(self):
        for record in self:
            mark = "" if record.is_verified else " ⚠"
            record.display_name = f"[{record.version}] {record.code} — {record.name}{mark}"

    @api.model
    def lgx_import_csv(self, rows, version, verified=False, source=None):
        """Muat KBLI dari baris CSV yang sudah diurai. Idempoten per (kode, versi).

        Dipisah dari pembacaan berkas dengan sengaja: pemuatan puluhan ribu baris
        adalah pekerjaan jalur master data yang dijalankan operator dari shell
        atau skrip, dan method yang menerima BARIS — bukan path — dapat diuji
        tanpa menyiapkan berkas di disk.

        Kolom yang dibaca: code, name, section, risk_level, permit_form,
        requirement_note. Kolom lain diabaikan, supaya ekspor mentah dari BPS
        dapat dimuat tanpa dibersihkan lebih dulu.
        """
        created = updated = skipped = 0
        for row in rows:
            code = (row.get("code") or "").strip()
            if not code or not code.isdigit() or len(code) != 5:
                skipped += 1
                continue
            values = {
                "code": code,
                "version": version,
                "name": (row.get("name") or "").strip() or code,
                "section": (row.get("section") or "").strip() or False,
                "risk_level": (row.get("risk_level") or "").strip() or False,
                "permit_form": (row.get("permit_form") or "").strip() or False,
                "requirement_note": (row.get("requirement_note") or "").strip() or False,
                "is_verified": verified,
                "source_note": source,
            }
            existing = self.search([("code", "=", code), ("version", "=", version)], limit=1)
            if existing:
                existing.write(values)
                updated += 1
            else:
                self.create(values)
                created += 1
        return {"created": created, "updated": updated, "skipped": skipped}

    @api.model
    def lgx_map_versions(self, pairs, verified=False):
        """Tautkan padanan 2020 ⇄ 2025 dari daftar (kode_2020, kode_2025)."""
        linked = missing = 0
        for old_code, new_code in pairs:
            old = self.search([("code", "=", old_code), ("version", "=", "2020")], limit=1)
            new = self.search([("code", "=", new_code), ("version", "=", "2025")], limit=1)
            if not old or not new:
                missing += 1
                continue
            old.write({"counterpart_ids": [(4, new.id)], "is_verified": verified or old.is_verified})
            new.write({"counterpart_ids": [(4, old.id)], "is_verified": verified or new.is_verified})
            linked += 1
        return {"linked": linked, "missing": missing}

    # Pemetaan bawaan yang relevan logistik. Dijalankan lewat <function> di blok
    # tanpa noupdate, jadi ia diperbaiki sendiri saat konversi yang ⚠ akhirnya
    # terkonfirmasi dan daftar ini diperbarui.
    _SEED_MAPPING = [
        # (kode 2020, kode 2025, sudah terverifikasi)
        ("52291", "52311", True),
        ("49431", "49231", True),
        ("52101", "52109", False),
    ]

    @api.model
    def _lgx_seed_version_mapping(self):
        verified_pairs = [(a, b) for a, b, ok in self._SEED_MAPPING if ok]
        unverified_pairs = [(a, b) for a, b, ok in self._SEED_MAPPING if not ok]
        result = self.lgx_map_versions(verified_pairs, verified=True)
        result_unverified = self.lgx_map_versions(unverified_pairs, verified=False)
        return {
            "terverifikasi": result,
            "belum_terverifikasi": result_unverified,
        }
