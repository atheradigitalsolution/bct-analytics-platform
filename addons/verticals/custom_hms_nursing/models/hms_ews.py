# -*- coding: utf-8 -*-
"""NEWS2 scoring and escalation."""
from odoo import _, api, fields, models


def _band(value, bands):
    """Return the score for the first band whose range contains `value`."""
    for low, high, points in bands:
        if (low is None or value >= low) and (high is None or value <= high):
            return points
    return 0


class HmsEwsScore(models.Model):
    _name = "hms.ews.score"
    _description = "Skor Peringatan Dini (EWS)"
    _order = "id desc"

    observation_id = fields.Many2one("hms.observation", required=True, ondelete="cascade",
                                     index=True)
    admission_id = fields.Many2one("hms.admission", index=True)
    patient_id = fields.Many2one(related="observation_id.patient_id", store=True, index=True)
    station_id = fields.Many2one("hms.nursing.station", index=True)
    system = fields.Selection(
        [("news2", "NEWS2 (dewasa)"), ("pews", "PEWS (anak)")],
        default="news2", required=True,
    )
    score = fields.Integer(required=True)
    breakdown = fields.Char("Rincian Skor")
    level = fields.Selection(
        [("low", "Rendah"), ("medium", "Sedang"), ("high", "Tinggi")],
        required=True, index=True,
    )
    escalated = fields.Boolean(index=True)
    escalation_task_id = fields.Many2one("hms.nursing.task", readonly=True)

    @api.model
    def score_observation(self, observation):
        """Compute NEWS2 for one observation and escalate when required."""
        parts = {}
        parts["rr"] = _band(observation.respiratory_rate or 0, [
            (None, 8, 3), (9, 11, 1), (12, 20, 0), (21, 24, 2), (25, None, 3),
        ]) if observation.respiratory_rate else 0
        parts["spo2"] = _band(observation.spo2 or 0, [
            (None, 91, 3), (92, 93, 2), (94, 95, 1), (96, None, 0),
        ]) if observation.spo2 else 0
        parts["o2"] = 2 if observation.oxygen_support else 0
        parts["temp"] = _band(observation.temperature or 0, [
            (None, 35.0, 3), (35.1, 36.0, 1), (36.1, 38.0, 0), (38.1, 39.0, 1), (39.1, None, 2),
        ]) if observation.temperature else 0
        parts["sbp"] = _band(observation.systolic or 0, [
            (None, 90, 3), (91, 100, 2), (101, 110, 1), (111, 219, 0), (220, None, 3),
        ]) if observation.systolic else 0
        parts["hr"] = _band(observation.pulse or 0, [
            (None, 40, 3), (41, 50, 1), (51, 90, 0), (91, 110, 1), (111, 130, 2), (131, None, 3),
        ]) if observation.pulse else 0
        parts["avpu"] = 0 if observation.consciousness in ("alert", False) else 3
        total = sum(parts.values())

        settings = self.env["hms.settings"].get_settings()
        if total >= (settings.ews_alarm_score or 7):
            level = "high"
        elif total >= (settings.ews_escalate_score or 5):
            level = "medium"
        else:
            level = "low"

        admission = self.env["hms.admission"].search(
            [("encounter_id", "=", observation.encounter_id.id)], limit=1
        )
        station = self.env["hms.nursing.station"].search(
            [("ward_id", "=", admission.ward_id.id)], limit=1
        ) if admission else self.env["hms.nursing.station"]
        record = self.create({
            "observation_id": observation.id,
            "admission_id": admission.id if admission else False,
            "station_id": station.id,
            "score": total,
            "level": level,
            "breakdown": ", ".join(f"{k}={v}" for k, v in parts.items() if v),
        })
        if level in ("medium", "high"):
            record._escalate()
        return record

    def _escalate(self):
        """Turn a worrying score into an assigned task, not just a red badge."""
        self.ensure_one()
        task = self.env["hms.nursing.task"].create({
            "admission_id": self.admission_id.id,
            "encounter_id": self.observation_id.encounter_id.id,
            "patient_id": self.patient_id.id,
            "station_id": self.station_id.id,
            "type": "escalation",
            "title": _("Lapor dokter — EWS %s") % self.score,
            "detail": _("Skor EWS %(s)s (%(b)s). Laporkan ke DPJP dan catat responsnya.")
            % {"s": self.score, "b": self.breakdown},
            "due_at": fields.Datetime.add(
                fields.Datetime.now(), minutes=15 if self.level == "high" else 60
            ),
            "window_minutes": 15,
            "priority": "2" if self.level == "high" else "1",
        })
        self.write({"escalated": True, "escalation_task_id": task.id})
        self.env["hms.event"].emit("nursing.ews.escalated", {
            "ews_id": self.id,
            "score": self.score,
            "level": self.level,
            "patient": self.patient_id.name,
            "admission_id": self.admission_id.id,
            "station_id": self.station_id.id,
        })
        return task


class HmsObservation(models.Model):
    _inherit = "hms.observation"

    ews_score_id = fields.Many2one("hms.ews.score", "Skor EWS", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        observations = super().create(vals_list)
        for observation in observations:
            # Only score observations that carry enough vitals to be meaningful;
            # a lone weight measurement must not produce a reassuring zero.
            if not (observation.respiratory_rate or observation.pulse or observation.systolic):
                continue
            score = self.env["hms.ews.score"].score_observation(observation)
            observation.ews_score_id = score.id
        return observations
