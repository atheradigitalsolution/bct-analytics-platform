# -*- coding: utf-8 -*-
"""One row per stretch of time a patient occupied one bed."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsBedAssignment(models.Model):
    _name = "hms.bed.assignment"
    _description = "Penempatan Bed"
    _order = "from_at desc, id desc"

    admission_id = fields.Many2one("hms.admission", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="admission_id.patient_id", store=True, index=True)
    bed_id = fields.Many2one("hms.bed", "Bed", required=True, index=True)
    room_id = fields.Many2one("hms.room", related="bed_id.room_id", store=True)
    ward_id = fields.Many2one("hms.ward", related="bed_id.ward_id", store=True)
    class_id = fields.Many2one("hms.care.class", "Kelas Bed", required=True)
    charge_class_id = fields.Many2one(
        "hms.care.class", "Kelas Ditagihkan", required=True,
        help="Kelas yang dipakai mencari tarif. Berbeda dari kelas bed ketika "
             "pasien naik kelas atas permintaan sendiri: penjamin tetap ditagih "
             "sesuai haknya dan selisihnya menjadi tanggungan pasien.",
    )
    from_at = fields.Datetime("Dari", required=True, default=fields.Datetime.now, index=True)
    to_at = fields.Datetime("Sampai")
    reason = fields.Selection(
        [("admit", "Admisi"), ("transfer_medical", "Pindah Indikasi Medis"),
         ("transfer_request", "Pindah Permintaan Pasien"), ("upgrade", "Naik Kelas"),
         ("downgrade", "Turun Kelas"), ("isolation", "Isolasi"), ("discharge", "Pulang")],
        required=True, default="admit",
    )
    is_current = fields.Boolean("Berlaku Sekarang", default=True, index=True)
    requested_by_id = fields.Many2one("res.users", "Diminta Oleh",
                                      default=lambda s: s.env.user)
    approved_by_id = fields.Many2one("hms.practitioner", "Disetujui")
    note = fields.Char()

    _one_current = models.UniqueIndex("(admission_id) WHERE is_current IS TRUE")
    _bed_one_current = models.UniqueIndex("(bed_id) WHERE is_current IS TRUE")

    @api.constrains("from_at", "to_at")
    def _check_period(self):
        for rec in self:
            if rec.to_at and rec.to_at < rec.from_at:
                raise ValidationError(_("Waktu selesai penempatan mendahului waktu mulai."))

    def class_on(self, date):
        """True when this assignment covered the given calendar day."""
        self.ensure_one()
        start = self.from_at.date()
        end = self.to_at.date() if self.to_at else date
        return start <= date <= end
