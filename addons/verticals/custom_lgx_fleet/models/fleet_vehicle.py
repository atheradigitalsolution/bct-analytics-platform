# -*- coding: utf-8 -*-
"""Kendaraan angkutan barang: kapasitas legal dan dokumen yang menentukan boleh jalan.

Yang ditambahkan di sini bukan atribut deskriptif. Setiap field punya konsekuensi
operasional:

* ``jbi_kg``           batas keras validasi ODOL. Tanpa angka ini, validasi tidak
                       dapat dilakukan sama sekali — dan itu dikatakan kepada
                       pengguna, bukan dianggap lolos.
* ``kir_expiry_date``  kendaraan dengan KIR mati yang tetap jalan adalah risiko
                       hukum pada PERUSAHAAN, bukan hanya pada pengemudi.
* ``gps_device_id``    GPS terpasang adalah persyaratan izin angkutan barang,
                       jadi ketiadaannya adalah temuan, bukan preferensi.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FleetVehicle(models.Model):
    _inherit = "fleet.vehicle"

    lgx_is_freight = fields.Boolean(
        "Kendaraan Angkutan Barang", default=False,
        help="Menandai kendaraan yang tunduk pada validasi ODOL dan persyaratan "
             "izin angkutan barang. Kendaraan operasional kantor tidak.",
    )
    lgx_category_id = fields.Many2one("lgx.vehicle.category", "Kategori Angkutan")

    # --- kapasitas legal ---------------------------------------------------
    lgx_jbb_kg = fields.Float("JBB (kg)", help="Jumlah Berat yang Diperbolehkan — batas rancang bangun.")
    lgx_jbi_kg = fields.Float(
        "JBI (kg)",
        help="Jumlah Berat yang Diizinkan — BATAS VALIDASI ODOL. Ini angka yang "
             "ditegakkan di jalan, bukan JBB.",
    )
    lgx_kerb_weight_kg = fields.Float("Berat Kosong (kg)")
    lgx_payload_capacity_kg = fields.Float("Kapasitas Muatan Legal (kg)",
                                           compute="_compute_payload_capacity", store=True)
    lgx_body_length_mm = fields.Integer("Panjang Bak (mm)")
    lgx_body_width_mm = fields.Integer("Lebar Bak (mm)")
    lgx_body_height_mm = fields.Integer("Tinggi Bak (mm)")
    lgx_body_volume_cbm = fields.Float("Volume Bak (CBM)", compute="_compute_body_volume", store=True)

    # Dimensi SESUAI TIPE, disalin dari SRUT / sertifikat uji tipe. Berbeda dari
    # dimensi bak di atas, yang mencatat keadaan kendaraan sebagaimana adanya.
    # Selisih antara keduanya itulah over-dimension.
    lgx_type_length_mm = fields.Integer(
        "Panjang Sesuai Tipe (mm)",
        help="Dari SRUT atau sertifikat uji tipe, bukan hasil ukur di pool.")
    lgx_type_width_mm = fields.Integer("Lebar Sesuai Tipe (mm)")
    lgx_type_height_mm = fields.Integer("Tinggi Sesuai Tipe (mm)")
    lgx_dimension_status = fields.Selection(
        [("ok", "Sesuai tipe"), ("unknown", "Tidak dapat divalidasi"),
         ("warning", "Melebihi tipe"), ("blocked", "Melebihi tipe — diblokir")],
        string="Status Dimensi", compute="_compute_dimension_status", store=True)
    lgx_dimension_message = fields.Char(
        "Keterangan Dimensi", compute="_compute_dimension_status", store=True)
    lgx_axle_configuration = fields.Char("Konfigurasi Sumbu")

    # --- dokumen -----------------------------------------------------------
    lgx_kir_number = fields.Char("Nomor Uji Berkala (KIR)")
    lgx_kir_expiry_date = fields.Date("Masa Berlaku KIR")
    lgx_stnk_number = fields.Char("Nomor STNK")
    lgx_stnk_expiry_date = fields.Date("Masa Berlaku STNK")
    lgx_tax_expiry_date = fields.Date("Jatuh Tempo Pajak Kendaraan")
    lgx_kp_number = fields.Char("Nomor Kartu Pengawasan")
    lgx_kp_expiry_date = fields.Date("Masa Berlaku Kartu Pengawasan")
    lgx_document_status = fields.Selection(
        [("ok", "Lengkap"), ("warning", "Mendekati Kedaluwarsa"), ("expired", "Ada yang Mati")],
        string="Status Dokumen", compute="_compute_document_status", store=True,
    )
    lgx_document_issue = fields.Char("Dokumen Bermasalah", compute="_compute_document_status",
                                     store=True)

    # --- perizinan ---------------------------------------------------------
    lgx_gps_device_id = fields.Char("ID Perangkat GPS")
    lgx_gps_provider = fields.Char("Penyedia GPS")
    lgx_pool_location_id = fields.Many2one("lgx.location", "Pool",
                                           domain="[('location_type','in',('warehouse','city','depot'))]")

    _jbi_not_above_jbb = models.Constraint(
        "check(lgx_jbb_kg = 0 or lgx_jbi_kg = 0 or lgx_jbi_kg <= lgx_jbb_kg)",
        "JBI tidak boleh melebihi JBB.",
    )

    @api.depends("lgx_jbi_kg", "lgx_kerb_weight_kg")
    def _compute_payload_capacity(self):
        for vehicle in self:
            vehicle.lgx_payload_capacity_kg = max(
                0.0, (vehicle.lgx_jbi_kg or 0.0) - (vehicle.lgx_kerb_weight_kg or 0.0))

    @api.depends("lgx_body_length_mm", "lgx_body_width_mm", "lgx_body_height_mm")
    def _compute_body_volume(self):
        for vehicle in self:
            vehicle.lgx_body_volume_cbm = (
                (vehicle.lgx_body_length_mm or 0)
                * (vehicle.lgx_body_width_mm or 0)
                * (vehicle.lgx_body_height_mm or 0)
            ) / 1_000_000_000.0

    @api.depends("lgx_kir_expiry_date", "lgx_stnk_expiry_date",
                 "lgx_tax_expiry_date", "lgx_kp_expiry_date")
    def _compute_document_status(self):
        """Satu status ringkas, dan NAMA dokumen yang bermasalah.

        Status tanpa nama dokumen memaksa orang membuka form dan memeriksa empat
        tanggal satu per satu, dan itu yang membuat daftar peringatan berhenti
        dipakai.
        """
        params = self.env["ir.config_parameter"].sudo()
        warn_days = int(params.get_param("lgx.doc_expiry_warning_days", 30))
        today = fields.Date.context_today(self)
        warn_before = fields.Date.add(today, days=warn_days)
        for vehicle in self:
            expired, warning = [], []
            for field_name, label in (
                ("lgx_kir_expiry_date", _("KIR")),
                ("lgx_stnk_expiry_date", _("STNK")),
                ("lgx_tax_expiry_date", _("Pajak")),
                ("lgx_kp_expiry_date", _("Kartu Pengawasan")),
            ):
                value = vehicle[field_name]
                if not value:
                    continue
                if value < today:
                    expired.append(label)
                elif value <= warn_before:
                    warning.append(label)
            if expired:
                vehicle.lgx_document_status = "expired"
                vehicle.lgx_document_issue = ", ".join(expired)
            elif warning:
                vehicle.lgx_document_status = "warning"
                vehicle.lgx_document_issue = ", ".join(warning)
            else:
                vehicle.lgx_document_status = "ok"
                vehicle.lgx_document_issue = False

    # --- validasi ODOL -----------------------------------------------------
    def lgx_odol_enforcement_date(self):
        """Tanggal penegakan, dari konfigurasi.

        ⚠ Default 2027-01-01 berasal dari pernyataan pejabat dan siaran pers,
        bukan dari peraturan yang sudah terbit. Di materi klien ia disebut
        kebijakan yang diumumkan, bukan kewajiban hukum yang sudah berlaku.
        """
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "lgx.odol_enforcement_date", "2027-01-01")
        try:
            return fields.Date.to_date(raw)
        except (ValueError, TypeError):
            return fields.Date.to_date("2027-01-01")

    def lgx_check_load(self, cargo_weight_kg, on_date=None):
        """Periksa muatan terhadap JBI. Mengembalikan (level, pesan).

        Level: ``ok``, ``unknown``, ``warning``, ``blocked``.

        ``unknown`` bukan ``ok``. Kendaraan tanpa data JBI TIDAK lolos validasi —
        ia dinyatakan tidak dapat divalidasi, dan itu perbedaan yang menentukan:
        "belum diperiksa" yang diperlakukan sebagai "aman" adalah cara sebuah
        armada berangkat kelebihan muatan dengan sistem yang tampak hijau.
        """
        self.ensure_one()
        on_date = on_date or fields.Date.context_today(self)
        if not self.lgx_jbi_kg:
            return "unknown", _(
                "Kendaraan %s belum punya data JBI, jadi muatan tidak dapat divalidasi "
                "terhadap kapasitas legal.", self.display_name,
            )
        total = (cargo_weight_kg or 0.0) + (self.lgx_kerb_weight_kg or 0.0)
        if total <= self.lgx_jbi_kg:
            return "ok", ""
        excess = total - self.lgx_jbi_kg
        message = _(
            "Muatan %(cargo).0f kg ditambah berat kosong %(kerb).0f kg menjadi "
            "%(total).0f kg, melebihi JBI %(jbi).0f kg sebanyak %(excess).0f kg.",
            cargo=cargo_weight_kg or 0.0, kerb=self.lgx_kerb_weight_kg or 0.0,
            total=total, jbi=self.lgx_jbi_kg, excess=excess,
        )
        if on_date >= self.lgx_odol_enforcement_date():
            return "blocked", message
        return "warning", message

    def lgx_check_dimensions(self, on_date=None):
        """Over-DIMENSION, yang secara hukum BUKAN hal yang sama dengan over-load.

        Butir A12 (diperiksa 2026-09-20). UU 22/2009 memisahkan keduanya, dan
        jaraknya jauh:

        * Pasal 307 — muatan, daya angkut, tata cara pemuatan menyimpang dari
          Pasal 169 ayat (1): kurungan paling lama 2 bulan atau denda paling
          banyak Rp500.000.
        * Pasal 277 — membuat, merakit, atau memodifikasi kendaraan sehingga
          berubah tipe tanpa memenuhi kewajiban uji tipe: penjara paling lama
          1 tahun atau denda paling banyak Rp24.000.000.

        Empat puluh delapan kali lipat, dan pidananya enam kali lebih panjang.
        Sampai perbaikan ini, modul hanya memeriksa yang Rp500.000 sementara
        namanya "ODOL" — dan nama itu membuat separuh yang lebih mahal tampak
        sudah tertangani.

        Perbedaan sifat yang ikut menentukan bentuknya: over-load adalah keadaan
        SATU PERJALANAN, over-dimension adalah keadaan KENDARAAN. Bak yang lebih
        panjang dari tipenya tetap lebih panjang besok pagi, dengan muatan apa
        pun. Karena itu statusnya disimpan di kendaraan, bukan dihitung ulang
        per trip.

        ``unknown`` bukan ``ok``, dengan alasan yang sama seperti pada JBI:
        kendaraan yang dimensi tipenya belum diisi TIDAK lolos, ia dinyatakan
        tidak dapat divalidasi.
        """
        self.ensure_one()
        on_date = on_date or fields.Date.context_today(self)
        pasangan = [
            (_("panjang"), self.lgx_body_length_mm, self.lgx_type_length_mm),
            (_("lebar"), self.lgx_body_width_mm, self.lgx_type_width_mm),
            (_("tinggi"), self.lgx_body_height_mm, self.lgx_type_height_mm),
        ]
        if not any(tipe for _label, _aktual, tipe in pasangan):
            return "unknown", _(
                "Kendaraan %s belum punya dimensi sesuai tipe, jadi over-dimension "
                "tidak dapat divalidasi. Salin dari SRUT atau sertifikat uji tipe.",
                self.display_name,
            )
        lebih = []
        for label, aktual, tipe in pasangan:
            if aktual and tipe and aktual > tipe:
                lebih.append(_(
                    "%s bak %s mm melebihi tipe %s mm (selisih %s mm)",
                    label, aktual, tipe, aktual - tipe,
                ))
        if not lebih:
            return "ok", ""
        message = _(
            "Dimensi bak menyimpang dari tipe yang disahkan: %s. Ini pelanggaran "
            "Pasal 277 UU 22/2009, bukan Pasal 307 — sanksinya sampai "
            "Rp24.000.000, dan ia melekat pada kendaraan, bukan pada muatan "
            "hari ini.", "; ".join(lebih),
        )
        if on_date >= self.lgx_odol_enforcement_date():
            return "blocked", message
        return "warning", message

    @api.depends("lgx_body_length_mm", "lgx_body_width_mm", "lgx_body_height_mm",
                 "lgx_type_length_mm", "lgx_type_width_mm", "lgx_type_height_mm")
    def _compute_dimension_status(self):
        for vehicle in self:
            status, message = vehicle.lgx_check_dimensions()
            vehicle.lgx_dimension_status = status
            vehicle.lgx_dimension_message = message or _("Dimensi bak sesuai tipe.")

    @api.model
    def _cron_warn_vehicle_documents(self):
        vehicles = self.search([
            ("lgx_is_freight", "=", True),
            ("lgx_document_status", "in", ("warning", "expired")),
        ])
        for vehicle in vehicles:
            responsible = vehicle.manager_id or self.env.user
            vehicle.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Dokumen kendaraan %s: %s", vehicle.license_plate or vehicle.name,
                          vehicle.lgx_document_issue),
                note=_("Status: %s. Kendaraan dengan dokumen mati yang tetap beroperasi "
                       "adalah risiko hukum pada perusahaan, bukan hanya pada pengemudi.",
                       vehicle.lgx_document_status),
                user_id=responsible.id,
            )
        return len(vehicles)
