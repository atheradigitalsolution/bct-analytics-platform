# -*- coding: utf-8 -*-
"""Nursing assessment with SDKI / SLKI / SIKI."""
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsSdki(models.Model):
    _name = "hms.sdki"
    _description = "Diagnosis Keperawatan (SDKI)"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    category = fields.Char("Kategori")
    definition = fields.Text()
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode SDKI harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}"


class HmsSlki(models.Model):
    _name = "hms.slki"
    _description = "Luaran Keperawatan (SLKI)"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    category = fields.Char()
    definition = fields.Text()
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode SLKI harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}"


class HmsSiki(models.Model):
    _name = "hms.siki"
    _description = "Intervensi Keperawatan (SIKI)"
    _order = "code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    category = fields.Char()
    definition = fields.Text()
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode SIKI harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.code} — {rec.name}"


class HmsNursingAssessment(models.Model):
    _name = "hms.nursing.assessment"
    _description = "Asuhan Keperawatan"
    _inherit = ["hms.audited"]
    _order = "assessed_at desc, id desc"

    admission_id = fields.Many2one("hms.admission", ondelete="cascade", index=True)
    encounter_id = fields.Many2one("hms.encounter", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    type = fields.Selection(
        [("initial", "Pengkajian Awal"), ("reassessment", "Pengkajian Ulang"),
         ("shift_evaluation", "Evaluasi Shift")],
        required=True, default="initial",
    )
    nurse_id = fields.Many2one("hms.practitioner", "Perawat", required=True,
                               default=lambda s: s._default_nurse())
    assessed_at = fields.Datetime(default=fields.Datetime.now, required=True)

    # Sixteen-domain screening, stored as explicit columns for the ones that
    # drive downstream behaviour and free text for the rest.
    fall_risk_score = fields.Integer("Skor Risiko Jatuh (Morse)")
    braden_score = fields.Integer("Skor Braden (Dekubitus)")
    pain_score = fields.Integer("Skala Nyeri")
    nutrition_screen = fields.Selection(
        [("none", "Tidak Berisiko"), ("mild", "Risiko Ringan"), ("severe", "Risiko Berat")],
        string="Skrining Gizi", default="none",
    )
    functional_status = fields.Selection(
        [("independent", "Mandiri"), ("partial", "Bantuan Sebagian"), ("total", "Bantuan Penuh")],
        default="independent",
    )
    psychosocial = fields.Text("Psikososial & Spiritual")
    education_need = fields.Text("Kebutuhan Edukasi")
    domains = fields.Text("Domain Lain (catatan)")

    diagnosis_ids = fields.One2many("hms.nursing.diagnosis", "assessment_id", "Diagnosis")
    evaluation = fields.Text("Evaluasi (SOAP Keperawatan)")

    signed = fields.Boolean(readonly=True, copy=False)
    signature_hash = fields.Char(readonly=True, copy=False)
    signed_at = fields.Datetime(readonly=True, copy=False)
    revises_id = fields.Many2one("hms.nursing.assessment", readonly=True, copy=False)
    is_current = fields.Boolean(default=True, readonly=True)

    @api.model
    def _default_nurse(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    def action_sign(self):
        """Same append-only rule as the medical record: signed means final."""
        for rec in self:
            if rec.signed:
                raise UserError(_("Asuhan sudah ditandatangani."))
            material = "|".join([
                str(rec.id), str(rec.nurse_id.id),
                fields.Datetime.to_string(rec.assessed_at) or "",
                rec.evaluation or "", rec.psychosocial or "",
                str(rec.fall_risk_score), str(rec.braden_score),
            ])
            rec.write({
                "signed": True,
                "signed_at": fields.Datetime.now(),
                "signature_hash": hashlib.sha256(material.encode()).hexdigest(),
            })
        return True

    def write(self, vals):
        signed = self.filtered("signed")
        allowed = {"signed", "signed_at", "signature_hash", "is_current", "revises_id"}
        if signed and set(vals) - allowed:
            raise UserError(
                _("Asuhan keperawatan yang sudah ditandatangani tidak dapat diubah. "
                  "Buat pengkajian ulang sebagai revisi.")
            )
        return super().write(vals)

    def action_revise(self):
        self.ensure_one()
        if not self.signed:
            raise UserError(_("Asuhan yang belum ditandatangani cukup diubah langsung."))
        new = self.copy({
            "revises_id": self.id, "signed": False, "signed_at": False,
            "signature_hash": False, "assessed_at": fields.Datetime.now(),
        })
        self.write({"is_current": False})
        return new


class HmsNursingDiagnosis(models.Model):
    _name = "hms.nursing.diagnosis"
    _description = "Diagnosis Keperawatan"
    _order = "id"

    assessment_id = fields.Many2one("hms.nursing.assessment", required=True, ondelete="cascade")
    patient_id = fields.Many2one(related="assessment_id.patient_id", store=True, index=True)
    sdki_id = fields.Many2one("hms.sdki", "Diagnosis (SDKI)", required=True)
    related_factors = fields.Text("Faktor Berhubungan")
    signs = fields.Text("Tanda & Gejala")
    slki_ids = fields.Many2many("hms.slki", string="Luaran (SLKI)")
    siki_ids = fields.Many2many("hms.siki", string="Intervensi (SIKI)")
    target_date = fields.Date("Target Tercapai")
    state = fields.Selection(
        [("active", "Aktif"), ("resolved", "Teratasi"), ("partial", "Teratasi Sebagian")],
        default="active", required=True,
    )
