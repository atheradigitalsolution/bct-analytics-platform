# -*- coding: utf-8 -*-
"""Hospital-wide settings.

One row per company, created on demand. Every threshold the clinical modules
need lives here instead of in `ir.config_parameter`, because the people who
change them are hospital administrators using the Odoo UI, not operators with
shell access.
"""
from odoo import api, fields, models


class HmsSettings(models.Model):
    _name = "hms.settings"
    _description = "Pengaturan Rumah Sakit"

    name = fields.Char(default="Pengaturan SIMRS", required=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda s: s.env.company, ondelete="cascade"
    )

    # Identity shown on every printed document.
    hospital_name = fields.Char("Nama Rumah Sakit", required=True, default="Rumah Sakit")
    hospital_code = fields.Char("Kode RS (Kemenkes)")
    hospital_class = fields.Selection(
        [("a", "Kelas A"), ("b", "Kelas B"), ("c", "Kelas C"), ("d", "Kelas D")],
        default="c",
    )
    hospital_address = fields.Text("Alamat")
    hospital_phone = fields.Char("Telepon")
    hospital_logo = fields.Image("Logo", max_width=512, max_height=512)
    director_name = fields.Char("Direktur")

    # Clinical thresholds. Named after the spec sections that consume them.
    ews_escalate_score = fields.Integer("Ambang eskalasi EWS", default=5)
    ews_alarm_score = fields.Integer("Ambang alarm EWS", default=7)
    vitals_interval_hours = fields.Integer("Interval TTV default (jam)", default=8)
    no_show_recover_minutes = fields.Integer("Pemulihan no-show (menit)", default=30)
    max_call_count = fields.Integer("Panggilan sebelum no-show", default=3)
    booking_checkin_before_minutes = fields.Integer("Batas check-in booking (menit)", default=30)
    name_masking = fields.Boolean("Samarkan nama di display antrian", default=True)
    priority_interleave = fields.Integer(
        "Rasio panggil prioritas", default=3,
        help="Setiap N tiket reguler, satu tiket prioritas dipanggil lebih dulu.",
    )

    # Billing / cashier thresholds.
    discount_auth_percent = fields.Float("Diskon butuh otorisasi (%)", default=10.0)
    deposit_warning_percent = fields.Float(
        "Ambang peringatan deposit (%)", default=80.0,
        help="Bila tagihan berjalan melewati persentase ini dari deposit, kasir diberi tugas top-up.",
    )

    # ------------------------------------------------------------------
    # Parameter kebijakan rumah sakit (Gelombang 1A).
    #
    # Semua nilai di bawah ini adalah *titik konfigurasi*, bukan logika: modul
    # yang memakainya (casemix/klaim, rekam medis, finance) belum dibangun.
    # Angka defaultnya diambil dari norma yang bisa dikutip; bila sebuah angka
    # tidak punya dasar nasional, help-nya mengatakan begitu secara eksplisit
    # supaya tidak ada yang mengira itu aturan Kemenkes.
    # ------------------------------------------------------------------

    # --- Klinis & mutu ---------------------------------------------------
    critical_result_ack_minutes = fields.Integer(
        "Batas akui nilai kritis (menit)", default=30,
        help="Tenggat pelaporan dan pengakuan (read-back) hasil kritis penunjang. "
             "Default 30 menit berasal dari standar akreditasi/SPO rumah sakit, "
             "BUKAN batas nasional — sesuaikan dengan SPO yang berlaku di RS ini.",
    )
    incident_report_due_hours = fields.Integer(
        "Batas lapor IKP (jam)", default=48,
        help="Tenggat pelaporan Insiden Keselamatan Pasien ke tim KPRS. "
             "PMK 11/2017 tentang Keselamatan Pasien: paling lambat 2x24 jam.",
    )
    klpcm_due_hours = fields.Integer(
        "Batas kelengkapan berkas RM (jam)", default=48,
        help="Tenggat KLPCM (Kelengkapan Pengisian Catatan Medis) setelah pasien "
             "pulang. Lazimnya 2x24 jam mengikuti standar akreditasi rekam medis.",
    )
    discharge_summary_due_hours = fields.Integer(
        "Batas resume medis (jam)", default=24,
        help="Tenggat penyelesaian resume medis pasien pulang. Ini indikator mutu "
             "(KPI) yang dikonfigurasi RS, BUKAN blokir keras: keterlambatan "
             "dicatat dan dilaporkan, tidak menghentikan proses pemulangan.",
    )
    emr_correction_grace_hours = fields.Integer(
        "Masa koreksi RME tanpa persetujuan PMIK (jam)", default=48,
        help="Rentang waktu sejak entri dibuat, ketika penulis masih boleh "
             "mengoreksi sendiri catatan RME-nya. PMK 24/2022 tentang Rekam Medis "
             "Elektronik; lazim diterapkan 2x24 jam. Lewat batas ini koreksi "
             "memerlukan persetujuan petugas rekam medis (PMIK).",
    )
    emr_retention_years = fields.Integer(
        "Retensi rekam medis (tahun)", default=25,
        help="PMK 24/2022 Pasal 39 ayat (1): rekam medis disimpan paling singkat "
             "25 tahun sejak tanggal terakhir pasien berobat.",
    )

    # --- Rawat inap & kelas ----------------------------------------------
    titip_kelas_max_days = fields.Integer(
        "Batas titip kelas (hari)", default=3,
        help="Lama maksimal pasien dirawat di kelas selain hak kelasnya karena "
             "kamar penuh, sebelum wajib dipindahkan atau diselesaikan secara "
             "administratif.",
    )
    prorate_partial_days = fields.Boolean(
        "Prorata selisih kelas untuk hari campuran", default=False,
        help="Bila aktif, selisih naik kelas pada hari yang sebagian dijalani di "
             "kelas lama dihitung proporsional. Aturan ini BELUM TERVERIFIKASI "
             "terhadap ketentuan BPJS; default nonaktif (dihitung per hari penuh) "
             "sampai kebijakan RS dikonfirmasi.",
    )
    checkout_time = fields.Float(
        "Jam check-out rawat inap", default=12.0,
        help="Jam batas pemulangan sebelum hari rawat berikutnya dihitung. "
             "Kebijakan internal RS, tidak diatur norma nasional.",
    )
    half_day_grace_hours = fields.Integer(
        "Toleransi setelah jam check-out (jam)", default=6,
        help="Kelebihan waktu setelah jam check-out yang masih ditoleransi "
             "sebelum dibebankan sebagai setengah hari rawat. Kebijakan internal RS.",
    )
    sep_igd_to_inpatient_policy = fields.Selection(
        [("replace", "SEP IGD diganti SEP rawat inap"),
         ("merge", "SEP IGD digabung ke episode rawat inap"),
         ("separate", "SEP IGD dan SEP rawat inap berdiri sendiri")],
        string="Perlakuan SEP IGD ke rawat inap", default="merge", required=True,
        help="Perlakuan SEP ketika pasien IGD dilanjutkan menjadi rawat inap. "
             "BELUM ADA NORMA NASIONAL yang seragam untuk ini — praktiknya "
             "berbeda antar Kantor Cabang BPJS. Konfirmasikan ke KC BPJS wilayah "
             "sebelum mengubah nilai ini.",
    )

    # --- Klaim / casemix ---------------------------------------------------
    # Hanya parameter. Tidak ada logika klaim di gelombang ini; model
    # hms.claim* belum ada.
    claim_expiry_months = fields.Integer(
        "Kedaluwarsa klaim (bulan)", default=6,
        help="Perpres 82/2018 Pasal 77: klaim diajukan paling lambat 6 bulan "
             "sejak pelayanan selesai.",
    )
    claim_variance_threshold = fields.Float(
        "Ambang selisih tarif untuk review (Rp)", default=4000000.0, digits=(16, 2),
        help="Selisih antara tarif rumah sakit dan tarif grouper INA-CBG yang "
             "memicu review internal casemix. Ambang internal RS, bukan norma.",
    )
    readmission_window_days = fields.Integer(
        "Jendela readmisi (hari)", default=30,
        help="Permenkes 26/2021: rawat inap ulang dengan diagnosis sama dalam "
             "rentang ini ditandai sebagai readmisi untuk audit klaim.",
    )
    fragmentation_window_days = fields.Integer(
        "Jendela fragmentasi pelayanan (hari)", default=7,
        help="Permenkes 26/2021: episode terpisah dalam rentang ini yang "
             "seharusnya satu episode ditandai sebagai fragmentasi.",
    )
    grouper_mode = fields.Selection(
        [("inacbg", "INA-CBG"), ("idrg", "iDRG"), ("dual", "Paralel (INA-CBG + iDRG)")],
        string="Mode grouper", default="inacbg", required=True,
        help="Grouper yang dipakai saat menyusun klaim. iDRG MASIH UJI COBA "
             "(Kepmenkes 177/2026) dan tarifnya BELUM TERBIT, sehingga mode "
             "'iDRG' dan 'Paralel' hanya untuk persiapan/simulasi.",
    )
    jkn_revenue_basis = fields.Selection(
        [("cbg_final", "Nilai CBG final (setelah verifikasi)"),
         ("cbg_estimate", "Estimasi CBG (saat pasien pulang)")],
        string="Dasar pengakuan pendapatan JKN", default="cbg_final", required=True,
        help="Menentukan kapan pendapatan pasien JKN diakui: pada nilai CBG yang "
             "sudah diverifikasi BPJS, atau pada estimasi grouper saat pasien pulang.",
    )

    # --- Kasir & keuangan --------------------------------------------------
    cash_variance_tolerance = fields.Float(
        "Toleransi selisih kas (Rp)", default=0.0, digits=(16, 2),
        help="Selisih setoran kas yang masih diterima tanpa berita acara. "
             "Default nol: setiap selisih harus dijelaskan. Kebijakan internal RS.",
    )
    stamp_duty_threshold = fields.Float(
        "Ambang bea meterai (Rp)", default=5000000.0, digits=(16, 2),
        help="UU 10/2020 tentang Bea Meterai: dokumen transaksi di atas "
             "Rp5.000.000 dikenai bea meterai Rp10.000.",
    )
    billing_lock_date = fields.Date(
        "Tanggal kunci tagihan",
        help="Tagihan dengan tanggal sampai dengan hari ini tidak boleh diubah "
             "lagi. Kosongkan untuk menonaktifkan penguncian.",
    )
    hpp_mode = fields.Selection(
        [("perpetual_custom", "Perpetual (perhitungan sendiri)"),
         ("periodic", "Periodik")],
        string="Mode perhitungan HPP", default="perpetual_custom", required=True,
        help="Cara harga pokok penjualan farmasi/BHP dihitung. Odoo 19 CE tidak "
             "menyediakan akun interim (Anglo-Saxon accounting), sehingga mode "
             "perpetual dihitung oleh modul sendiri. BELUM DIUJI pada beban "
             "transaksi nyata.",
    )

    _company_uniq = models.Constraint(
        "unique(company_id)",
        "Pengaturan SIMRS hanya boleh satu per perusahaan.",
    )

    @api.model
    def get_settings(self):
        """Return the singleton for the active company, creating it if absent."""
        rec = self.sudo().search([("company_id", "=", self.env.company.id)], limit=1)
        if not rec:
            rec = self.sudo().create({"company_id": self.env.company.id})
        return rec
