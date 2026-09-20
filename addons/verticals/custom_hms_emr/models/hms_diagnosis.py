# -*- coding: utf-8 -*-
"""Diagnoses (ICD-10) and procedures (ICD-9-CM)."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsDiagnosis(models.Model):
    _name = "hms.diagnosis"
    _description = "Diagnosis"
    _inherit = ["hms.audited"]
    _order = "rank, id"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    icd10_id = fields.Many2one("hms.icd10", "Kode ICD-10", required=True, index=True)
    rank = fields.Selection(
        [("primary", "Diagnosis Utama"), ("secondary", "Diagnosis Sekunder"),
         ("complication", "Komplikasi"), ("comorbidity", "Komorbid")],
        required=True, default="primary",
    )
    stage = fields.Selection(
        [("working", "Diagnosis Kerja"), ("final", "Diagnosis Akhir"),
         ("differential", "Diagnosis Banding")],
        required=True, default="working",
    )
    diagnosed_at = fields.Datetime("Waktu", default=fields.Datetime.now, required=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter",
                                      default=lambda s: s._default_practitioner())
    note = fields.Char("Keterangan")
    ihs_condition_id = fields.Char("ID Condition SATUSEHAT", readonly=True, copy=False)

    # A partial unique index, not an EXCLUDE constraint: EXCLUDE with the `=`
    # operator on an integer needs btree_gist, and requiring an extension for
    # this would make the module fail to install on a stock cluster.
    _one_final_primary = models.UniqueIndex(
        "(encounter_id) WHERE rank = 'primary' AND stage = 'final'",
    )

    @api.model
    def _default_practitioner(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    def unlink(self):
        if any(d.stage == "final" for d in self):
            raise UserError(
                _("Diagnosis akhir tidak dapat dihapus karena menjadi dasar klaim dan laporan RL. "
                  "Ubah menjadi diagnosis kerja bila keliru.")
            )
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.env["hms.event"].emit("diagnosis.added", {
                "encounter_id": rec.encounter_id.id,
                "icd10": rec.icd10_id.code,
                "rank": rec.rank,
            })
        return records


class HmsProcedure(models.Model):
    _name = "hms.procedure"
    _description = "Prosedur / Tindakan"
    _inherit = ["hms.audited"]
    _order = "performed_at desc, id desc"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    icd9_id = fields.Many2one("hms.icd9", "Kode ICD-9-CM", index=True)
    tariff_id = fields.Many2one("hms.tariff", "Item Tarif")
    name = fields.Char("Nama Tindakan", required=True)
    performed_at = fields.Datetime("Waktu Tindakan", default=fields.Datetime.now, required=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Operator/Pelaksana")
    assistant_ids = fields.Many2many("hms.practitioner", "hms_procedure_assistant_rel",
                                     "procedure_id", "practitioner_id", string="Asisten")
    outcome = fields.Selection(
        [("success", "Berhasil"), ("partial", "Sebagian"), ("failed", "Gagal"),
         ("aborted", "Dibatalkan")],
        default="success",
    )
    complication = fields.Char("Komplikasi")
    note = fields.Text("Laporan Tindakan")
    consent_id = fields.Many2one("hms.consent", "Persetujuan Tindakan")

    @api.constrains("tariff_id", "consent_id")
    def _check_consent_when_required(self):
        """A procedure whose tariff demands informed consent must carry one.

        Enforced at the data layer because the consent is the hospital's legal
        defence; a UI-only check disappears the moment anything writes through
        the API.
        """
        for rec in self:
            if rec.tariff_id.requires_consent and not rec.consent_id:
                raise ValidationError(
                    _("Tindakan '%s' memerlukan informed consent yang tertandatangani.")
                    % rec.name
                )
