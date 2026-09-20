# -*- coding: utf-8 -*-
"""Medical resume (outpatient) and discharge summary (inpatient)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsSummary(models.Model):
    _name = "hms.summary"
    _description = "Resume Medis / Ringkasan Pulang"
    _inherit = ["hms.audited"]
    _order = "id desc"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    type = fields.Selection(
        [("outpatient", "Resume Medis Rawat Jalan"), ("discharge", "Ringkasan Pulang Rawat Inap")],
        required=True, default="outpatient",
    )
    practitioner_id = fields.Many2one("hms.practitioner", "DPJP")
    admitted_at = fields.Datetime("Masuk")
    discharged_at = fields.Datetime("Keluar")
    length_of_stay = fields.Integer("Lama Rawat (hari)", compute="_compute_los", store=True)

    chief_complaint = fields.Text("Keluhan Utama")
    history = fields.Text("Riwayat Penyakit")
    physical_exam = fields.Text("Pemeriksaan Fisik")
    lab_summary = fields.Text("Hasil Penunjang")
    diagnosis_primary_id = fields.Many2one("hms.icd10", "Diagnosis Utama")
    diagnosis_secondary_ids = fields.Many2many("hms.icd10", string="Diagnosis Sekunder")
    procedure_summary = fields.Text("Tindakan yang Dilakukan")
    treatment = fields.Text("Terapi Selama Perawatan")
    discharge_medication = fields.Text("Obat Pulang")
    condition_at_discharge = fields.Selection(
        [("recovered", "Sembuh"), ("improved", "Membaik"), ("unchanged", "Tidak Berubah"),
         ("worse", "Memburuk"), ("deceased", "Meninggal")],
        string="Keadaan Keluar",
    )
    disposition = fields.Selection(
        [("home", "Pulang"), ("referred", "Dirujuk"), ("against_advice", "Pulang Paksa"),
         ("deceased", "Meninggal"), ("transfer", "Pindah Rawat")],
        string="Cara Keluar",
    )
    followup_instruction = fields.Text("Anjuran & Kontrol")
    followup_date = fields.Date("Tanggal Kontrol")
    followup_unit_id = fields.Many2one("hms.unit", "Poli Kontrol")

    state = fields.Selection(
        [("draft", "Draf"), ("final", "Final")], default="draft", required=True, readonly=True,
    )
    finalized_at = fields.Datetime(readonly=True)
    finalized_by_id = fields.Many2one("res.users", readonly=True)

    _encounter_type_uniq = models.Constraint(
        "unique(encounter_id, type)",
        "Satu kunjungan hanya boleh punya satu resume per jenis.",
    )

    @api.depends("admitted_at", "discharged_at")
    def _compute_los(self):
        for rec in self:
            if rec.admitted_at and rec.discharged_at:
                rec.length_of_stay = max((rec.discharged_at.date() - rec.admitted_at.date()).days, 1)
            else:
                rec.length_of_stay = 0

    @api.model
    def generate_for(self, encounter, summary_type="outpatient"):
        """Pre-fill a resume from what is already recorded.

        The doctor finalises it; nothing here invents clinical content. Every
        field is copied from an existing record, so a wrong resume is traceable
        to a wrong source note rather than to a generator.
        """
        existing = self.search([
            ("encounter_id", "=", encounter.id), ("type", "=", summary_type),
        ], limit=1)
        if existing and existing.state == "final":
            return existing

        diagnoses = self.env["hms.diagnosis"].search([("encounter_id", "=", encounter.id)])
        primary = diagnoses.filtered(lambda d: d.rank == "primary")[:1]
        secondary = diagnoses.filtered(lambda d: d.rank != "primary")
        notes = self.env["hms.clinical.note"].search([
            ("encounter_id", "=", encounter.id), ("is_current", "=", True),
        ], order="noted_at")
        procedures = self.env["hms.procedure"].search([("encounter_id", "=", encounter.id)])

        vals = {
            "encounter_id": encounter.id,
            "type": summary_type,
            "practitioner_id": encounter.practitioner_id.id,
            "chief_complaint": encounter.chief_complaint,
            "history": "\n\n".join(n.subjective for n in notes if n.subjective) or False,
            "physical_exam": "\n\n".join(n.objective for n in notes if n.objective) or False,
            "diagnosis_primary_id": primary.icd10_id.id if primary else False,
            "diagnosis_secondary_ids": [(6, 0, secondary.mapped("icd10_id").ids)],
            "procedure_summary": "\n".join(
                f"- {p.name} ({p.icd9_id.code or '-'})" for p in procedures
            ) or False,
            "treatment": "\n\n".join(n.plan for n in notes if n.plan) or False,
            "admitted_at": encounter.arrival_at,
            "discharged_at": encounter.closed_at,
        }
        if existing:
            existing.write(vals)
            return existing
        return self.create(vals)

    def action_finalize(self):
        for rec in self:
            if rec.state == "final":
                raise UserError(_("Resume sudah final."))
            if not rec.diagnosis_primary_id:
                raise UserError(
                    _("Diagnosis utama wajib diisi — resume tanpa diagnosis utama "
                      "tidak dapat dipakai untuk klaim maupun pelaporan RL.")
                )
            rec.write({
                "state": "final",
                "finalized_at": fields.Datetime.now(),
                "finalized_by_id": self.env.uid,
            })
        return True

    def write(self, vals):
        if any(r.state == "final" for r in self) and set(vals) - {"state"}:
            raise UserError(_("Resume yang sudah final tidak dapat diubah."))
        return super().write(vals)
