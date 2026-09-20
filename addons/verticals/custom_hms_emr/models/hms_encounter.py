# -*- coding: utf-8 -*-
"""Hangs the clinical record off the encounter."""
from odoo import _, api, fields, models


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    observation_ids = fields.One2many("hms.observation", "encounter_id", "Observasi")
    note_ids = fields.One2many("hms.clinical.note", "encounter_id", "Catatan Klinis",
                               domain=[("is_current", "=", True)])
    all_note_ids = fields.One2many("hms.clinical.note", "encounter_id", "Semua Versi Catatan")
    diagnosis_ids = fields.One2many("hms.diagnosis", "encounter_id", "Diagnosis")
    procedure_ids = fields.One2many("hms.procedure", "encounter_id", "Tindakan")
    consent_ids = fields.One2many("hms.consent", "encounter_id", "Persetujuan")
    summary_ids = fields.One2many("hms.summary", "encounter_id", "Resume")

    primary_diagnosis_id = fields.Many2one(
        "hms.icd10", "Diagnosis Utama", compute="_compute_primary_diagnosis", store=True,
    )
    unsigned_note_count = fields.Integer(compute="_compute_unsigned_notes")
    last_observation_id = fields.Many2one(
        "hms.observation", "TTV Terakhir", compute="_compute_last_observation",
    )

    @api.depends("diagnosis_ids.rank", "diagnosis_ids.icd10_id", "diagnosis_ids.stage")
    def _compute_primary_diagnosis(self):
        for enc in self:
            final = enc.diagnosis_ids.filtered(
                lambda d: d.rank == "primary" and d.stage == "final"
            )[:1]
            working = enc.diagnosis_ids.filtered(lambda d: d.rank == "primary")[:1]
            enc.primary_diagnosis_id = (final or working).icd10_id

    @api.depends("note_ids.signed")
    def _compute_unsigned_notes(self):
        for enc in self:
            enc.unsigned_note_count = len(enc.note_ids.filtered(lambda n: not n.signed))

    @api.depends("observation_ids.taken_at")
    def _compute_last_observation(self):
        for enc in self:
            enc.last_observation_id = enc.observation_ids.sorted("taken_at", reverse=True)[:1]

    def _closing_blockers(self):
        """Unsigned notes stop a visit from closing.

        An unsigned CPPT is not a medical record — it is a draft. Letting the
        encounter close around it produces charts that cannot be defended, and
        the author has usually gone home by the time anyone notices.
        """
        blockers = super()._closing_blockers()
        if self.unsigned_note_count:
            blockers.append(
                _("%s catatan klinis belum ditandatangani.") % self.unsigned_note_count
            )
        unsigned_consent = self.consent_ids.filtered(lambda c: c.state == "draft")
        if unsigned_consent:
            blockers.append(
                _("%s persetujuan masih berstatus draf.") % len(unsigned_consent)
            )
        return blockers

    def action_generate_summary(self):
        self.ensure_one()
        summary_type = "discharge" if self.type == "inpatient" else "outpatient"
        summary = self.env["hms.summary"].generate_for(self, summary_type)
        return {
            "type": "ir.actions.act_window",
            "res_model": "hms.summary",
            "res_id": summary.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_view_timeline(self):
        """All encounters for this patient, newest first."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Riwayat %s") % self.patient_id.name,
            "res_model": "hms.encounter",
            "view_mode": "list,form",
            "domain": [("patient_id", "=", self.patient_id.id)],
            "context": {"search_default_f_all": 1},
        }
