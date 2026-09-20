# -*- coding: utf-8 -*-
"""Structured vital signs and measurements."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsObservation(models.Model):
    _name = "hms.observation"
    _description = "Observasi / Tanda-Tanda Vital"
    _inherit = ["hms.audited"]
    _order = "taken_at desc, id desc"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    # `admission_id` is added by custom_hms_inpatient, which owns hms.admission.
    # This module sits below it and must install without it.
    taken_at = fields.Datetime("Waktu Pengukuran", required=True, default=fields.Datetime.now,
                               index=True)
    taken_by_id = fields.Many2one("hms.practitioner", "Diukur Oleh")
    context = fields.Selection(
        [("initial", "Asesmen Awal"), ("routine", "Rutin"), ("pre_procedure", "Pra Tindakan"),
         ("post_procedure", "Pasca Tindakan"), ("emergency", "Gawat Darurat")],
        default="routine", required=True,
    )

    # Vitals. Separate columns rather than a key/value table: EWS scoring and
    # FHIR mapping both read these by name, and a generic bag makes both of
    # those guesswork.
    systolic = fields.Integer("Sistolik (mmHg)")
    diastolic = fields.Integer("Diastolik (mmHg)")
    pulse = fields.Integer("Nadi (x/menit)")
    respiratory_rate = fields.Integer("Napas (x/menit)")
    temperature = fields.Float("Suhu (°C)", digits=(4, 1))
    spo2 = fields.Integer("SpO₂ (%)")
    consciousness = fields.Selection(
        [("alert", "Sadar Penuh (Alert)"), ("voice", "Respons Suara"),
         ("pain", "Respons Nyeri"), ("unresponsive", "Tidak Respons")],
        string="Kesadaran",
    )
    gcs_eye = fields.Integer("GCS Mata (E)")
    gcs_verbal = fields.Integer("GCS Verbal (V)")
    gcs_motor = fields.Integer("GCS Motorik (M)")
    gcs_total = fields.Integer("GCS Total", compute="_compute_gcs", store=True)
    oxygen_support = fields.Boolean("Mendapat Oksigen")

    weight_kg = fields.Float("Berat Badan (kg)", digits=(5, 1))
    height_cm = fields.Float("Tinggi Badan (cm)", digits=(5, 1))
    bmi = fields.Float("IMT", compute="_compute_bmi", store=True, digits=(5, 1))

    pain_score = fields.Integer("Skala Nyeri (0-10)")
    fall_risk_score = fields.Integer("Skor Risiko Jatuh (Morse)")
    fall_risk_level = fields.Selection(
        [("low", "Rendah"), ("medium", "Sedang"), ("high", "Tinggi")],
        compute="_compute_fall_risk", store=True, string="Risiko Jatuh",
    )
    note = fields.Text("Catatan")

    _vitals_idx = models.Index("(patient_id, taken_at DESC)")

    @api.depends("gcs_eye", "gcs_verbal", "gcs_motor")
    def _compute_gcs(self):
        for rec in self:
            rec.gcs_total = (rec.gcs_eye or 0) + (rec.gcs_verbal or 0) + (rec.gcs_motor or 0)

    @api.depends("weight_kg", "height_cm")
    def _compute_bmi(self):
        for rec in self:
            metres = (rec.height_cm or 0.0) / 100.0
            rec.bmi = (rec.weight_kg / (metres * metres)) if metres else 0.0

    @api.depends("fall_risk_score")
    def _compute_fall_risk(self):
        # Morse Fall Scale bands as used in Indonesian hospital accreditation.
        for rec in self:
            score = rec.fall_risk_score or 0
            rec.fall_risk_level = "high" if score >= 45 else ("medium" if score >= 25 else "low")

    @api.constrains("systolic", "diastolic")
    def _check_blood_pressure(self):
        for rec in self:
            if rec.systolic and rec.diastolic and rec.diastolic >= rec.systolic:
                raise ValidationError(
                    _("Tekanan diastolik (%(d)s) tidak boleh lebih besar atau sama dengan "
                      "sistolik (%(s)s). Periksa kembali pengukuran.")
                    % {"d": rec.diastolic, "s": rec.systolic}
                )

    @api.constrains("spo2", "pain_score", "temperature")
    def _check_ranges(self):
        for rec in self:
            if rec.spo2 and not 0 <= rec.spo2 <= 100:
                raise ValidationError(_("SpO₂ harus antara 0 dan 100."))
            if rec.pain_score and not 0 <= rec.pain_score <= 10:
                raise ValidationError(_("Skala nyeri harus antara 0 dan 10."))
            if rec.temperature and not 25.0 <= rec.temperature <= 45.0:
                raise ValidationError(_("Suhu %.1f °C di luar rentang yang masuk akal.") % rec.temperature)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            # The patient header shows the latest measurements; recomputing
            # them from the whole history on every read would be wasteful.
            patient_vals = {}
            if rec.weight_kg:
                patient_vals["weight_kg_last"] = rec.weight_kg
            if rec.height_cm:
                patient_vals["height_cm_last"] = rec.height_cm
            if patient_vals:
                rec.patient_id.sudo().write(patient_vals)
            rec.env["hms.event"].emit("observation.recorded", {
                "encounter_id": rec.encounter_id.id,
                "patient_id": rec.patient_id.id,
                "observation_id": rec.id,
            })
        return records
