# -*- coding: utf-8 -*-
"""Practitioners: doctors, nurses, midwives, pharmacists, analysts.

One table for every licensed clinician. The alternative — a model per
profession — duplicates licence tracking five times and then lets the copies
drift; the Indonesian licence regime (STR nationally, SIP per practice site) is
identical in shape for all of them.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsPractitionerLicense(models.Model):
    _name = "hms.practitioner.license"
    _description = "Izin Praktik Praktisi"
    _order = "valid_to desc"

    practitioner_id = fields.Many2one("hms.practitioner", required=True, ondelete="cascade")
    type = fields.Selection(
        [("sip", "SIP — Surat Izin Praktik"), ("sipp", "SIPP — Perawat"),
         ("sik", "SIK — Sarjana/Tenaga Kesehatan"), ("sipa", "SIPA — Apoteker"),
         ("other", "Lainnya")],
        required=True, default="sip",
    )
    number = fields.Char("Nomor", required=True)
    issuer = fields.Char("Penerbit")
    facility = fields.Char("Tempat Praktik", help="SIP diterbitkan per tempat praktik.")
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai", required=True)
    document = fields.Binary("Dokumen", attachment=True)
    document_name = fields.Char()


class HmsPractitioner(models.Model):
    _name = "hms.practitioner"
    _description = "Praktisi"
    _inherit = ["mail.thread"]
    _order = "name"
    _rec_names_search = ["name", "nik"]

    name = fields.Char(required=True, tracking=True)
    title_prefix = fields.Char("Gelar Depan", help="dr., drg., Prof., Ns., apt.")
    title_suffix = fields.Char("Gelar Belakang", help="Sp.A, M.Kes, S.Kep")
    type = fields.Selection(
        [("doctor", "Dokter"), ("dentist", "Dokter Gigi"), ("nurse", "Perawat"),
         ("midwife", "Bidan"), ("pharmacist", "Apoteker"),
         ("pharmacy_tech", "Tenaga Teknis Kefarmasian"), ("lab_analyst", "Analis Laboratorium"),
         ("radiographer", "Radiografer"), ("physio", "Fisioterapis"),
         ("nutritionist", "Ahli Gizi"), ("psychologist", "Psikolog"), ("other", "Lainnya")],
        required=True, default="doctor", tracking=True, index=True,
    )
    nik = fields.Char("NIK", size=16, tracking=True)
    gender = fields.Selection([("male", "Laki-laki"), ("female", "Perempuan")])
    birth_date = fields.Date("Tanggal Lahir")
    phone = fields.Char("Telepon")
    email = fields.Char("Surel")
    photo = fields.Image("Foto", max_width=512, max_height=512)

    employee_id = fields.Many2one("hr.employee", "Data Kepegawaian", tracking=True)
    user_id = fields.Many2one("res.users", "Pengguna Sistem", tracking=True)
    employment_type = fields.Selection(
        [("full_time", "Purna Waktu"), ("part_time", "Paruh Waktu"), ("visiting", "Tamu/Mitra"),
         ("contract", "Kontrak"), ("resident", "Residen"), ("intern", "Internsip")],
        default="full_time", required=True,
    )

    str_no = fields.Char("Nomor STR", tracking=True)
    str_valid_to = fields.Date("STR Berlaku Sampai", tracking=True)
    sip_ids = fields.One2many("hms.practitioner.license", "practitioner_id", "Izin Praktik")
    license_state = fields.Selection(
        [("ok", "Berlaku"), ("expiring", "Akan berakhir"), ("expired", "Kedaluwarsa"),
         ("missing", "Belum ada")],
        compute="_compute_license_state", store=True, string="Status Izin",
    )
    license_days_left = fields.Integer("Sisa Hari Izin", compute="_compute_license_state", store=True)

    specialty_id = fields.Many2one("hms.specialty", "Spesialisasi")
    subspecialty_id = fields.Many2one("hms.specialty", "Subspesialisasi")
    unit_ids = fields.Many2many(
        "hms.unit", "hms_unit_practitioner_rel", "practitioner_id", "unit_id", string="Unit Praktik",
    )
    primary_unit_id = fields.Many2one("hms.unit", "Unit Utama")

    npwp = fields.Char(
        "NPWP",
        help="Nomor Pokok Wajib Pajak praktisi. Dipakai saat memotong PPh atas "
             "jasa medis; tanpa NPWP tarif potongan lebih tinggi.",
    )
    tax_status = fields.Selection(
        [("employee", "Pegawai Tetap (PPh 21)"),
         ("non_employee", "Bukan Pegawai (PPh 21 jasa)"),
         ("badan", "Badan / Klinik Mitra (PPh 23)")],
        string="Status Pajak", default="non_employee", required=True,
        help="Menentukan skema pemotongan pajak atas jasa medis praktisi ini. "
             "Dokter mitra umumnya 'Bukan Pegawai'; kerja sama lewat badan usaha "
             "dipotong PPh 23, bukan PPh 21.",
    )

    bpjs_doctor_code = fields.Char("Kode Dokter BPJS")
    ihs_practitioner_id = fields.Char("ID SATUSEHAT")

    signature_image = fields.Image("Tanda Tangan", max_width=512, max_height=256)
    esign_pin_hash = fields.Char("Hash PIN e-Sign", groups="base.group_system")

    can_prescribe = fields.Boolean("Boleh meresepkan", default=True)
    can_order_lab = fields.Boolean("Boleh order lab", default=True)
    can_order_rad = fields.Boolean("Boleh order radiologi", default=True)
    can_be_dpjp = fields.Boolean("Boleh menjadi DPJP", default=True)
    can_operate = fields.Boolean("Boleh mengoperasi")
    can_anesthetize = fields.Boolean("Boleh membius")

    # Nursing-specific. Kept on the same table: a nurse is a practitioner with
    # extra columns, not a different kind of person.
    nurse_level = fields.Selection(
        [("pk1", "PK I"), ("pk2", "PK II"), ("pk3", "PK III"), ("pk4", "PK IV"), ("pk5", "PK V")],
        string="Jenjang Karir",
    )
    nurse_role = fields.Selection(
        [("primary", "Perawat Primer (PPJA)"), ("associate", "Perawat Asosiat"),
         ("charge_nurse", "Ketua Tim"), ("head_nurse", "Kepala Ruang"),
         ("supervisor", "Supervisor"), ("ok_nurse", "Perawat OK"),
         ("icu_nurse", "Perawat ICU"), ("er_nurse", "Perawat IGD")],
        string="Peran Keperawatan",
    )
    can_double_check_high_alert = fields.Boolean(
        "Boleh jadi saksi obat high-alert",
        help="Syarat menjadi perawat kedua pada double-check eMAR.",
    )
    can_administer_iv = fields.Boolean("Boleh memberikan IV")
    can_take_blood_sample = fields.Boolean("Boleh mengambil sampel darah")
    competency_ids = fields.One2many("hms.nurse.competency", "practitioner_id", "Kompetensi")

    default_consult_tariff_id = fields.Many2one("hms.tariff", "Tarif Konsultasi")
    max_patients_per_session = fields.Integer("Kuota Pasien per Sesi", default=20)
    slot_minutes_default = fields.Integer("Durasi Slot (menit)", default=10)
    accepts_bpjs = fields.Boolean("Melayani BPJS", default=True)
    color = fields.Integer("Warna")
    notification_channels = fields.Char(
        "Kanal Notifikasi", default="dashboard",
        help="Daftar dipisah koma: dashboard, email, wa.",
    )
    state = fields.Selection(
        [("active", "Aktif"), ("leave", "Cuti"), ("suspended", "Ditangguhkan"),
         ("resigned", "Berhenti")],
        default="active", required=True, tracking=True,
    )
    active = fields.Boolean(default=True)

    _nik_uniq = models.Constraint(
        "unique(nik)",
        "NIK praktisi sudah terdaftar.",
    )
    _user_uniq = models.Constraint(
        "unique(user_id)",
        "Satu pengguna hanya boleh terhubung ke satu praktisi.",
    )

    @api.constrains("nik")
    def _check_nik(self):
        for rec in self:
            if rec.nik and (len(rec.nik) != 16 or not rec.nik.isdigit()):
                raise ValidationError(_("NIK harus 16 digit angka."))

    @api.depends("str_valid_to", "sip_ids.valid_to")
    def _compute_license_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            dates = [d for d in ([rec.str_valid_to] + rec.sip_ids.mapped("valid_to")) if d]
            if not dates:
                rec.license_state = "missing"
                rec.license_days_left = 0
                continue
            # The binding constraint is whichever licence expires first.
            soonest = min(dates)
            days = (soonest - today).days
            rec.license_days_left = days
            if days < 0:
                rec.license_state = "expired"
            elif days <= 90:
                rec.license_state = "expiring"
            else:
                rec.license_state = "ok"

    @api.depends("name", "title_prefix", "title_suffix")
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.title_prefix, rec.name]
            label = " ".join(p for p in parts if p)
            if rec.title_suffix:
                label = f"{label}, {rec.title_suffix}"
            rec.display_name = label


class HmsNurseCompetency(models.Model):
    _name = "hms.nurse.competency"
    _description = "Sertifikat Kompetensi Perawat"
    _order = "valid_to desc"

    practitioner_id = fields.Many2one("hms.practitioner", required=True, ondelete="cascade")
    name = fields.Char("Kompetensi", required=True, help="BTCLS, ICU, Hemodialisa, Kemoterapi, PPI.")
    cert_no = fields.Char("Nomor Sertifikat")
    issuer = fields.Char("Penerbit")
    valid_to = fields.Date("Berlaku Sampai")
