# -*- coding: utf-8 -*-
"""Test panels, their parameters, and age/sex-aware reference ranges."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsLabParameter(models.Model):
    _name = "hms.lab.parameter"
    _description = "Parameter Laboratorium"
    _order = "sequence, code"

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    tariff_ids = fields.Many2many(
        "hms.tariff", "hms_tariff_lab_parameter_rel", "parameter_id", "tariff_id",
        string="Termasuk dalam Pemeriksaan",
    )
    loinc_code = fields.Char("Kode LOINC")
    uom_name = fields.Char("Satuan")
    value_type = fields.Selection(
        [("numeric", "Angka"), ("text", "Teks"), ("selection", "Pilihan")],
        default="numeric", required=True,
    )
    selection_values = fields.Char("Pilihan", help="Dipisah koma, mis. Negatif,Positif")
    method = fields.Char("Metode")
    specimen_type = fields.Char("Jenis Spesimen")
    tat_minutes = fields.Integer("Target Waktu Hasil (menit)")
    decimal_places = fields.Integer("Angka Desimal", default=2)
    range_ids = fields.One2many("hms.lab.reference.range", "parameter_id", "Nilai Rujukan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode parameter lab harus unik.")

    def find_range(self, gender=None, age_years=0):
        """Return the reference range that applies to this patient.

        Most specific first: a range naming the patient's sex beats a range
        that applies to everyone, so a paediatric female range is not shadowed
        by a generic adult one.
        """
        self.ensure_one()
        candidates = self.range_ids.filtered(
            lambda r: (r.age_from or 0) <= age_years
            and (r.age_to == 0 or age_years <= r.age_to)
        )
        return (candidates.filtered(lambda r: r.gender == gender)[:1]
                or candidates.filtered(lambda r: not r.gender)[:1])


class HmsLabReferenceRange(models.Model):
    _name = "hms.lab.reference.range"
    _description = "Nilai Rujukan Laboratorium"
    _order = "parameter_id, age_from"

    parameter_id = fields.Many2one("hms.lab.parameter", required=True, ondelete="cascade")
    gender = fields.Selection(
        [("male", "Laki-laki"), ("female", "Perempuan")],
        help="Kosong berarti berlaku untuk semua jenis kelamin.",
    )
    age_from = fields.Integer("Usia Dari (tahun)", default=0)
    age_to = fields.Integer("Usia Sampai (tahun)", default=0, help="0 berarti tanpa batas atas.")
    ref_low = fields.Float("Batas Bawah", digits=(16, 4))
    ref_high = fields.Float("Batas Atas", digits=(16, 4))
    critical_low = fields.Float("Kritis Bawah", digits=(16, 4))
    critical_high = fields.Float("Kritis Atas", digits=(16, 4))
    note = fields.Char("Keterangan")

    @api.constrains("ref_low", "ref_high", "critical_low", "critical_high")
    def _check_bounds(self):
        for rec in self:
            if rec.ref_high and rec.ref_low and rec.ref_low > rec.ref_high:
                raise ValidationError(_("Batas bawah rujukan tidak boleh melebihi batas atas."))
            if rec.critical_low and rec.ref_low and rec.critical_low > rec.ref_low:
                raise ValidationError(
                    _("Ambang kritis bawah harus lebih rendah daripada batas bawah rujukan.")
                )
            if rec.critical_high and rec.ref_high and rec.critical_high < rec.ref_high:
                raise ValidationError(
                    _("Ambang kritis atas harus lebih tinggi daripada batas atas rujukan.")
                )
