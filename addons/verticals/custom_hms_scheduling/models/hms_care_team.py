# -*- coding: utf-8 -*-
"""Who is responsible for this patient, and when."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

ROLES = [
    ("dpjp", "DPJP (Dokter Penanggung Jawab Pelayanan)"),
    ("co_treating", "Dokter Rawat Bersama"),
    ("consultant", "Dokter Konsulen"),
    ("resident", "Residen / Dokter Jaga"),
    ("primary_nurse", "Perawat Primer (PPJA)"),
    ("pharmacist", "Apoteker Klinis"),
    ("dietitian", "Ahli Gizi"),
]


class HmsCareTeam(models.Model):
    _name = "hms.care.team"
    _description = "Tim Perawatan"
    _order = "encounter_id, role, id"

    encounter_id = fields.Many2one("hms.encounter", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    practitioner_id = fields.Many2one("hms.practitioner", required=True, index=True)
    user_id = fields.Many2one(related="practitioner_id.user_id", store=True, index=True)
    role = fields.Selection(ROLES, required=True, default="dpjp", index=True)
    date_from = fields.Datetime(default=fields.Datetime.now, required=True)
    date_to = fields.Datetime()
    is_active = fields.Boolean(default=True, index=True)
    changed_by_id = fields.Many2one("res.users", default=lambda s: s.env.user, readonly=True)
    reason = fields.Char("Alasan Perubahan")

    _one_active_dpjp = models.UniqueIndex(
        "(encounter_id) WHERE role = 'dpjp' AND is_active IS TRUE",
    )

    @api.model
    def assign(self, encounter, practitioner, role="dpjp", reason=None):
        """Put someone on the team, retiring the previous holder of a single role."""
        if role == "dpjp":
            current = self.search([
                ("encounter_id", "=", encounter.id), ("role", "=", "dpjp"),
                ("is_active", "=", True),
            ])
            if current.practitioner_id == practitioner:
                return current
            current.write({"is_active": False, "date_to": fields.Datetime.now()})
            current.flush_recordset(["is_active", "date_to"])
            encounter.write({"practitioner_id": practitioner.id})
        return self.create({
            "encounter_id": encounter.id,
            "practitioner_id": practitioner.id,
            "role": role,
            "reason": reason,
        })


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    care_team_ids = fields.One2many("hms.care.team", "encounter_id", "Tim Perawatan")

    @api.model_create_multi
    def create(self, vals_list):
        encounters = super().create(vals_list)
        for enc in encounters:
            if enc.practitioner_id:
                self.env["hms.care.team"].create({
                    "encounter_id": enc.id,
                    "practitioner_id": enc.practitioner_id.id,
                    "role": "dpjp",
                })
        return encounters


class HmsAudited(models.AbstractModel):
    _inherit = "hms.audited"

    def _hms_audit_in_care_team(self):
        """Real care-team lookup, replacing the conservative default.

        With this installed, the audit trail can tell an access made while
        treating the patient apart from one made with blanket EMR rights — the
        distinction the compliance review actually cares about.
        """
        self.ensure_one()
        encounter_id = self._hms_audit_encounter_id()
        if not encounter_id:
            return False
        return bool(self.env["hms.care.team"].sudo().search_count([
            ("encounter_id", "=", encounter_id),
            ("user_id", "=", self.env.uid),
            ("is_active", "=", True),
        ]))
