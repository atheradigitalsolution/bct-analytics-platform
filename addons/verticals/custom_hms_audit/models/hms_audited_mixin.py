# -*- coding: utf-8 -*-
"""Mixin that records who looked at a patient's record."""
from odoo import api, fields, models


class HmsAudited(models.AbstractModel):
    _name = "hms.audited"
    _description = "Mixin Audit Akses Rekam Medis"

    def _hms_audit_patient_id(self):
        """Return the patient this record belongs to.

        Overridden by models that reach the patient indirectly — a lab result
        knows its order, the order knows the encounter, the encounter knows the
        patient.
        """
        self.ensure_one()
        if "patient_id" in self._fields:
            return self.patient_id.id
        return False

    def _hms_audit_encounter_id(self):
        self.ensure_one()
        if "encounter_id" in self._fields:
            return self.encounter_id.id
        if self._name == "hms.encounter":
            return self.id
        return False

    def _hms_log_access(self, action):
        """Record one access, folded into today's row for the same user+patient.

        Folding matters: opening a single encounter screen triggers dozens of
        reads across notes, orders and results. One row per call turns the
        audit table into noise precisely when an investigator needs it.
        """
        if not self or (self.env.su and not self.env.context.get("hms_audit_force")):
            # Server-side machinery (crons, computes) is not a person looking
            # at a chart. Logging it would drown the human accesses.
            return
        Log = self.env["hms.access.log"].sudo()
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        request = getattr(self.env, "request", None) or self.env.context.get("hms_request_meta") or {}
        ip = request.get("ip") if isinstance(request, dict) else None
        ua = request.get("user_agent") if isinstance(request, dict) else None
        for record in self:
            patient_id = record._hms_audit_patient_id()
            existing = Log.search([
                ("user_id", "=", self.env.uid),
                ("patient_id", "=", patient_id),
                ("model_name", "=", self._name),
                ("action", "=", action),
                ("access_date", "=", today),
            ], limit=1)
            if existing:
                # write() is blocked on the model; the counter update is the one
                # legitimate mutation, so it goes through SQL deliberately.
                self.env.cr.execute(
                    "UPDATE hms_access_log SET hit_count = hit_count + 1, last_at = %s WHERE id = %s",
                    (now, existing.id),
                )
                # The ORM cache still holds the pre-increment value; without
                # this, anything reading the counter later in the same
                # transaction sees a stale number.
                existing.invalidate_recordset(["hit_count", "last_at"])
                continue
            entry = {
                "user_id": self.env.uid,
                "patient_id": patient_id,
                "model_name": self._name,
                "res_id": record.id,
                "action": action,
                "access_date": today,
                "ip_address": ip,
                "user_agent": ua,
                "was_in_care_team": record._hms_audit_in_care_team(),
            }
            if "encounter_id" in Log._fields:
                entry["encounter_id"] = record._hms_audit_encounter_id()
            Log.create(entry)

    def _hms_audit_in_care_team(self):
        """True when the current user is clinically involved with this patient.

        custom_hms_scheduling replaces this with a real care-team lookup. The
        default is conservative: unknown involvement is recorded as "not in
        care team" so the row shows up in the review queue rather than hiding.
        """
        return False

    def read(self, fields=None, load="_classic_read"):
        res = super().read(fields=fields, load=load)
        self._hms_log_access("read")
        return res

    def write(self, vals):
        res = super().write(vals)
        self._hms_log_access("write")
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._hms_log_access("create")
        return records
