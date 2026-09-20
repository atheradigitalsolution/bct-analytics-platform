# -*- coding: utf-8 -*-
"""The patient record.

Two rules here are load-bearing and easy to lose in a refactor:

1. The medical record number comes from a `no_gap` sequence read inside the
   creating transaction. Concurrent registrations therefore serialise on the
   sequence row rather than racing to the same number.
2. A patient is never deleted and never silently overwritten. Duplicates are
   merged forward (`merged_into_id`) so that references from old encounters
   still resolve.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsPatientAllergy(models.Model):
    _name = "hms.patient.allergy"
    _description = "Alergi Pasien"
    _order = "severity desc, id"

    patient_id = fields.Many2one("hms.patient", required=True, ondelete="cascade", index=True)
    substance_type = fields.Selection(
        [("drug", "Obat"), ("food", "Makanan"), ("environment", "Lingkungan"), ("other", "Lainnya")],
        required=True, default="drug",
    )
    substance = fields.Char("Zat/Bahan", required=True)
    ingredient_id = fields.Many2one(
        "hms.ingredient", "Zat Aktif",
        help="Diisi untuk alergi obat agar pemeriksaan resep dapat berjalan otomatis.",
    )
    reaction = fields.Char("Reaksi")
    severity = fields.Selection(
        [("mild", "Ringan"), ("moderate", "Sedang"), ("severe", "Berat"),
         ("anaphylaxis", "Anafilaksis")],
        required=True, default="moderate",
    )
    onset_date = fields.Date("Tanggal Kejadian")
    source = fields.Selection(
        [("patient", "Anamnesis pasien"), ("family", "Keluarga"), ("record", "Rekam medis"),
         ("test", "Uji alergi")],
        default="patient",
    )
    verified_by_id = fields.Many2one("hms.practitioner", "Diverifikasi Oleh")
    note = fields.Char("Catatan")


class HmsPatientInsurance(models.Model):
    _name = "hms.patient.insurance"
    _description = "Kepesertaan Penjamin"

    patient_id = fields.Many2one("hms.patient", required=True, ondelete="cascade")
    payer_id = fields.Many2one("hms.payer", "Penjamin", required=True)
    plan_id = fields.Many2one("hms.payer.plan", "Produk/Kelas Hak")
    member_no = fields.Char("Nomor Anggota", required=True)
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai")
    card_image = fields.Image("Foto Kartu", max_width=1024, max_height=1024)
    is_primary = fields.Boolean("Penjamin Utama")


class HmsPatientChronic(models.Model):
    _name = "hms.patient.chronic"
    _description = "Kondisi Kronis Pasien"

    patient_id = fields.Many2one("hms.patient", required=True, ondelete="cascade")
    icd10_id = fields.Many2one("hms.icd10", "Diagnosis", required=True)
    since = fields.Date("Sejak")
    note = fields.Char("Catatan")


class HmsPatient(models.Model):
    _name = "hms.patient"
    _description = "Pasien"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "mrn desc"
    _rec_names_search = ["mrn", "name", "nik", "bpjs_no"]

    # --- Identity ---------------------------------------------------------
    mrn = fields.Char("No. Rekam Medis", required=True, readonly=True, copy=False,
                      default=lambda s: _("Baru"), index=True, tracking=True)
    name = fields.Char("Nama Lengkap", required=True, tracking=True)
    nik = fields.Char("NIK", size=16, tracking=True, index=True)
    no_kk = fields.Char("No. Kartu Keluarga", size=16)
    identity_type = fields.Selection(
        [("ktp", "KTP"), ("kia", "KIA"), ("passport", "Paspor"), ("kitas", "KITAS"),
         ("none", "Tanpa Identitas")],
        required=True, default="ktp",
    )
    identity_no = fields.Char("Nomor Identitas Lain")
    birth_date = fields.Date("Tanggal Lahir", required=True, tracking=True)
    birth_place = fields.Char("Tempat Lahir")
    age_display = fields.Char("Usia", compute="_compute_age")
    age_years = fields.Integer("Usia (tahun)", compute="_compute_age", store=True)
    gender = fields.Selection(
        [("male", "Laki-laki"), ("female", "Perempuan")], required=True, tracking=True,
    )
    blood_type = fields.Selection(
        [("a", "A"), ("b", "B"), ("ab", "AB"), ("o", "O")], string="Golongan Darah",
    )
    rhesus = fields.Selection([("pos", "Positif"), ("neg", "Negatif")], string="Rhesus")
    marital_status = fields.Selection(
        [("single", "Belum Kawin"), ("married", "Kawin"), ("widowed", "Cerai Mati"),
         ("divorced", "Cerai Hidup")],
    )
    religion = fields.Selection(
        [("islam", "Islam"), ("kristen", "Kristen"), ("katolik", "Katolik"),
         ("hindu", "Hindu"), ("buddha", "Buddha"), ("konghucu", "Konghucu"),
         ("other", "Lainnya")],
        help="Data sensitif — dikumpulkan hanya untuk kebutuhan pelayanan kerohanian.",
    )
    education = fields.Selection(
        [("none", "Tidak Sekolah"), ("sd", "SD"), ("smp", "SMP"), ("sma", "SMA"),
         ("d3", "Diploma"), ("s1", "Sarjana"), ("s2", "Magister"), ("s3", "Doktor")],
    )
    occupation = fields.Char("Pekerjaan")
    nationality_id = fields.Many2one(
        "res.country", "Kewarganegaraan",
        default=lambda s: s.env.ref("base.id", raise_if_not_found=False),
    )
    language = fields.Char("Bahasa yang Dipahami")
    mother_name = fields.Char("Nama Ibu Kandung")
    is_newborn = fields.Boolean("Bayi Baru Lahir")
    mother_patient_id = fields.Many2one("hms.patient", "Pasien Ibu")
    is_anonymous = fields.Boolean(
        "Identitas Belum Diketahui",
        help="Pasien Tn/Ny X dari IGD. Wajib dilengkapi begitu teridentifikasi.",
    )
    photo = fields.Image("Foto", max_width=512, max_height=512)

    partner_id = fields.Many2one(
        "res.partner", "Kontak Penagihan", required=True, ondelete="restrict", copy=False,
        help="Dibuat otomatis; dipakai sebagai lawan transaksi invoice.",
    )
    merged_into_id = fields.Many2one("hms.patient", "Digabung Ke", readonly=True, copy=False)

    ihs_patient_id = fields.Char("ID SATUSEHAT", readonly=True, copy=False)
    bpjs_no = fields.Char("No. Kartu JKN", size=13, index=True)
    bpjs_class = fields.Selection(
        [("1", "Kelas 1"), ("2", "Kelas 2"), ("3", "Kelas 3")], string="Hak Kelas BPJS",
    )
    bpjs_status = fields.Char("Status Kepesertaan", readonly=True)
    bpjs_checked_at = fields.Datetime("Terakhir Dicek", readonly=True)

    # --- Contact ----------------------------------------------------------
    phone = fields.Char("Telepon/WA", tracking=True)
    phone2 = fields.Char("Telepon Alternatif")
    email = fields.Char("Surel")
    address_street = fields.Char("Alamat")
    rt = fields.Char("RT", size=3)
    rw = fields.Char("RW", size=3)
    village_id = fields.Many2one("hms.region", "Desa/Kelurahan", domain="[('level','=','village')]")
    district_id = fields.Many2one("hms.region", "Kecamatan", domain="[('level','=','district')]")
    city_id = fields.Many2one("hms.region", "Kabupaten/Kota", domain="[('level','=','city')]")
    state_region_id = fields.Many2one("hms.region", "Provinsi", domain="[('level','=','province')]")
    postal_code = fields.Char("Kode Pos")
    domicile_same_as_id = fields.Boolean("Domisili sama dengan KTP", default=True)
    domicile_street = fields.Char("Alamat Domisili")
    domicile_village_id = fields.Many2one("hms.region", "Desa/Kel. Domisili")
    emergency_contact_name = fields.Char("Kontak Darurat")
    emergency_contact_relation = fields.Char("Hubungan")
    emergency_contact_phone = fields.Char("Telepon Darurat")
    guardian_partner_id = fields.Many2one("res.partner", "Penanggung Jawab")

    # --- Clinical summary -------------------------------------------------
    allergy_ids = fields.One2many("hms.patient.allergy", "patient_id", "Alergi")
    has_allergy = fields.Boolean(compute="_compute_has_allergy", store=True, string="Ada Alergi")
    chronic_condition_ids = fields.One2many("hms.patient.chronic", "patient_id", "Kondisi Kronis")
    disability = fields.Selection(
        [("none", "Tidak Ada"), ("mobility", "Mobilitas"), ("visual", "Penglihatan"),
         ("hearing", "Pendengaran"), ("speech", "Bicara"), ("intellectual", "Intelektual"),
         ("multiple", "Ganda")],
        default="none", string="Disabilitas",
    )
    special_needs = fields.Text("Kebutuhan Khusus")
    height_cm_last = fields.Float("TB Terakhir (cm)", readonly=True)
    weight_kg_last = fields.Float("BB Terakhir (kg)", readonly=True)
    is_dnr = fields.Boolean("DNR", help="Do Not Resuscitate — harus didukung dokumen persetujuan.")
    infection_flag_ids = fields.Many2many("hms.infection.flag", string="Kewaspadaan Infeksi")
    is_vip = fields.Boolean("VIP")
    is_employee = fields.Boolean("Karyawan RS")
    is_staff_family = fields.Boolean("Keluarga Karyawan")

    # --- Administrative ---------------------------------------------------
    default_payer_id = fields.Many2one("hms.payer", "Penjamin Default")
    insurance_ids = fields.One2many("hms.patient.insurance", "patient_id", "Kepesertaan")
    consent_marketing = fields.Boolean("Setuju dihubungi untuk informasi layanan")
    consent_data_sharing = fields.Boolean("Setuju berbagi data untuk rujukan")
    first_visit_date = fields.Date("Kunjungan Pertama", readonly=True)
    last_visit_date = fields.Date("Kunjungan Terakhir", readonly=True)
    visit_count = fields.Integer("Jumlah Kunjungan", readonly=True)
    note_internal = fields.Text("Catatan Internal (non-klinis)")
    state = fields.Selection(
        [("active", "Aktif"), ("merged", "Digabung"), ("deceased", "Meninggal"),
         ("inactive", "Tidak Aktif")],
        default="active", required=True, tracking=True,
    )
    deceased_at = fields.Datetime("Waktu Meninggal")
    death_cause_icd10_id = fields.Many2one("hms.icd10", "Sebab Kematian")
    active = fields.Boolean(default=True)

    _mrn_uniq = models.Constraint(
        "unique(mrn)",
        "Nomor rekam medis harus unik.",
    )
    _nik_uniq = models.Constraint(
        "unique(nik)",
        "NIK sudah terdaftar pada pasien lain.",
    )

    # --- Computes ---------------------------------------------------------
    @api.depends("birth_date")
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.birth_date:
                rec.age_display = ""
                rec.age_years = 0
                continue
            delta = relativedelta(today, rec.birth_date)
            rec.age_years = delta.years
            rec.age_display = _("%(y)s th %(m)s bl %(d)s hr") % {
                "y": delta.years, "m": delta.months, "d": delta.days,
            }

    @api.depends("allergy_ids")
    def _compute_has_allergy(self):
        for rec in self:
            rec.has_allergy = bool(rec.allergy_ids)

    @api.depends("mrn", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.mrn} — {rec.name}" if rec.mrn else rec.name

    # --- Constraints ------------------------------------------------------
    @api.constrains("nik", "is_newborn", "is_anonymous", "identity_type")
    def _check_nik(self):
        for rec in self:
            if rec.nik:
                if len(rec.nik) != 16 or not rec.nik.isdigit():
                    raise ValidationError(_("NIK harus 16 digit angka."))
            elif not (rec.is_newborn or rec.is_anonymous or rec.identity_type != "ktp"):
                raise ValidationError(
                    _("NIK wajib diisi kecuali untuk bayi baru lahir, pasien tanpa identitas, "
                      "atau pemegang identitas selain KTP.")
                )

    @api.constrains("birth_date")
    def _check_birth_date(self):
        for rec in self:
            if rec.birth_date and rec.birth_date > fields.Date.context_today(rec):
                raise ValidationError(_("Tanggal lahir tidak boleh di masa depan."))

    # --- CRUD -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("mrn") or vals["mrn"] == _("Baru"):
                vals["mrn"] = self.env["ir.sequence"].next_by_code("hms.patient.mrn") or "/"
            if not vals.get("partner_id"):
                vals["partner_id"] = self._create_billing_partner(vals).id
        return super().create(vals_list)

    def _create_billing_partner(self, vals):
        """Every patient gets a partner so `account.move` has a counterparty."""
        return self.env["res.partner"].sudo().create({
            "name": vals.get("name") or _("Pasien"),
            "company_type": "person",
            "phone": vals.get("phone"),
            "email": vals.get("email"),
            "street": vals.get("address_street"),
        })

    def write(self, vals):
        res = super().write(vals)
        # Keep the billing partner's name in step; an invoice addressed to a
        # stale name is a real complaint at the cashier desk.
        if vals.get("name"):
            for rec in self:
                rec.partner_id.sudo().write({"name": vals["name"]})
        return res

    # --- Actions ----------------------------------------------------------
    def action_merge_into(self, target_id):
        """Merge this duplicate into `target_id`.

        Records are re-pointed by the modules that own them (`custom_hms_*`
        each implement `_hms_merge_patient`), so this method stays agnostic of
        what exists downstream.
        """
        self.ensure_one()
        target = self.browse(target_id)
        if target == self:
            raise UserError(_("Pasien tidak dapat digabung ke dirinya sendiri."))
        if target.state == "merged":
            raise UserError(_("Pasien tujuan sendiri sudah digabung ke rekam lain."))
        for model_name in self.env.registry.models:
            model = self.env.get(model_name)
            if model is None or not model._auto:
                continue
            hook = getattr(model, "_hms_merge_patient", None)
            if hook:
                hook(self, target)
        self.write({
            "state": "merged", "merged_into_id": target.id, "active": False,
        })
        target.message_post(
            body=_("Rekam medis %s digabungkan ke rekam ini.") % self.mrn
        )
        return True
