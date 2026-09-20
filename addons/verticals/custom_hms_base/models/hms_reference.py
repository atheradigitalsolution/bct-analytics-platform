# -*- coding: utf-8 -*-
"""Clinical and administrative reference tables.

These are look-up lists the hospital does not invent: administrative regions
from Kemendagri, specialties with their BPJS codes, ICD-10 and ICD-9-CM. They
are separated from the operational models so a bad import can be reloaded
without touching patient data.
"""
from odoo import api, fields, models


class HmsRegion(models.Model):
    _name = "hms.region"
    _description = "Wilayah Administratif"
    _parent_store = True
    _order = "code"

    code = fields.Char("Kode Kemendagri", required=True, index=True)
    name = fields.Char(required=True)
    level = fields.Selection(
        [("province", "Provinsi"), ("city", "Kabupaten/Kota"),
         ("district", "Kecamatan"), ("village", "Desa/Kelurahan")],
        required=True,
    )
    parent_id = fields.Many2one("hms.region", "Induk", ondelete="cascade", index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("hms.region", "parent_id", "Turunan")
    postal_code = fields.Char("Kode Pos")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode wilayah harus unik.",
    )

    @api.depends("name", "parent_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.parent_id.name} / {rec.name}" if rec.parent_id else rec.name


class HmsSpecialty(models.Model):
    _name = "hms.specialty"
    _description = "Spesialisasi"
    _order = "name"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    bpjs_code = fields.Char("Kode BPJS")
    parent_id = fields.Many2one("hms.specialty", "Induk (subspesialis dari)")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode spesialisasi harus unik.",
    )


class HmsIcd10(models.Model):
    _name = "hms.icd10"
    _description = "ICD-10 Diagnosis"
    _order = "code"
    _rec_names_search = ["code", "name_id", "name_en"]

    code = fields.Char(required=True, index=True)
    name_id = fields.Char("Nama (Indonesia)")
    name_en = fields.Char("Nama (Inggris)", required=True)
    chapter = fields.Char("Bab")
    group_code = fields.Char("Blok")
    is_billable = fields.Boolean("Dapat ditagihkan", default=True)
    is_notifiable = fields.Boolean(
        "Wajib lapor", help="Penyakit yang wajib dilaporkan ke dinas kesehatan."
    )
    is_icd10_im = fields.Boolean(
        "Kode ICD-IM",
        help="Penanda kode ICD-10 Indonesian Modification. E-Klaim 5.9 mewajibkan "
             "kode ICD-IM diisi untuk semua pasien, bukan hanya pasien JKN.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode ICD-10 harus unik.",
    )

    @api.depends("code", "name_id", "name_en")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name_id or rec.name_en}"


class HmsIcd9(models.Model):
    _name = "hms.icd9"
    _description = "ICD-9-CM Prosedur"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    is_surgical = fields.Boolean("Tindakan bedah")
    is_special_cmg = fields.Boolean(
        "Pemicu Special CMG",
        help="Prosedur yang memicu Special CMG (special procedure / prosthesis / "
             "investigation / drug) pada grouper INA-CBG, sehingga klaimnya "
             "mendapat tambahan di luar tarif dasar CBG.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode ICD-9-CM harus unik.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}"


class HmsInfectionFlag(models.Model):
    _name = "hms.infection.flag"
    _description = "Penanda Kewaspadaan Infeksi"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    precaution = fields.Selection(
        [("contact", "Kontak"), ("droplet", "Droplet"), ("airborne", "Udara"),
         ("protective", "Protektif")],
        required=True, default="contact",
    )
    requires_isolation = fields.Boolean("Perlu isolasi")
    note = fields.Text()

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode kewaspadaan harus unik.",
    )


class HmsIngredient(models.Model):
    """Active pharmaceutical ingredients.

    Lives in hms_base rather than hms_pharmacy because the patient allergy list
    points at it, and a patient record must be installable before the pharmacy
    module exists.
    """
    _name = "hms.ingredient"
    _description = "Zat Aktif"
    _order = "name"

    code = fields.Char()
    name = fields.Char("Nama Zat Aktif", required=True)
    atc_code = fields.Char("Kode ATC")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint(
        "unique(name)",
        "Nama zat aktif harus unik.",
    )


class HmsDosageForm(models.Model):
    _name = "hms.dosage.form"
    _description = "Bentuk Sediaan"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    is_liquid = fields.Boolean("Sediaan cair")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode bentuk sediaan harus unik.",
    )


class HmsRoute(models.Model):
    _name = "hms.route"
    _description = "Rute Pemberian"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    is_parenteral = fields.Boolean("Parenteral")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode rute harus unik.",
    )


class HmsFrequency(models.Model):
    """Dosing frequency, with the clock times eMAR schedules from."""
    _name = "hms.frequency"
    _description = "Frekuensi Pemberian"
    _order = "per_day desc, code"

    code = fields.Char(required=True, help="Contoh: 3x1, 2x1, q8h, PRN.")
    name = fields.Char(required=True)
    per_day = fields.Integer("Kali per Hari", default=1)
    times = fields.Char(
        "Jam Pemberian", default="08:00",
        help="Daftar jam dipisah koma, mis. 08:00,16:00,00:00. "
             "custom_hms_nursing memakai nilai ini untuk membuat jadwal eMAR.",
    )
    is_prn = fields.Boolean("Bila perlu (PRN)")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode frekuensi harus unik.",
    )

    def get_times(self):
        """Return the schedule as a list of (hour, minute) tuples."""
        self.ensure_one()
        out = []
        for chunk in (self.times or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            hh, _sep, mm = chunk.partition(":")
            try:
                out.append((int(hh), int(mm or 0)))
            except ValueError:
                continue
        return out


class HmsDrugClass(models.Model):
    _name = "hms.drug.class"
    _description = "Kelas Terapi Obat"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    requires_stewardship = fields.Boolean(
        "Masuk program PPRA", help="Antibiotik yang pemakaiannya dipantau."
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode kelas terapi harus unik.",
    )
