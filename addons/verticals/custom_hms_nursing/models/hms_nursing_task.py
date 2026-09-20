# -*- coding: utf-8 -*-
"""Scheduled nursing work."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

TASK_TYPES = [
    ("vitals", "Pengukuran TTV"),
    ("medication", "Pemberian Obat"),
    ("procedure", "Tindakan Keperawatan"),
    ("sample", "Pengambilan Sampel"),
    ("instruction", "Instruksi Dokter"),
    ("education", "Edukasi Pasien"),
    ("escalation", "Lapor Dokter"),
    ("manual", "Manual"),
]


class HmsNursingTask(models.Model):
    _name = "hms.nursing.task"
    _description = "Tugas Keperawatan"
    _order = "due_at, priority desc, id"

    admission_id = fields.Many2one("hms.admission", "Admisi", ondelete="cascade", index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="cascade", index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, index=True)
    station_id = fields.Many2one("hms.nursing.station", "Station", index=True)
    type = fields.Selection(TASK_TYPES, required=True, default="manual", index=True)
    title = fields.Char(required=True)
    detail = fields.Text()
    due_at = fields.Datetime("Jatuh Tempo", required=True, index=True)
    window_minutes = fields.Integer(
        "Toleransi (menit)", default=30,
        help="Tugas dianggap terlambat setelah melewati jatuh tempo + toleransi.",
    )
    state = fields.Selection(
        [("due", "Jatuh Tempo"), ("overdue", "Terlambat"), ("done", "Selesai"),
         ("skipped", "Dilewati"), ("cancelled", "Dibatalkan")],
        default="due", required=True, index=True,
    )
    priority = fields.Selection(
        [("0", "Normal"), ("1", "Penting"), ("2", "Mendesak")], default="0",
    )
    done_by_id = fields.Many2one("hms.practitioner", "Dikerjakan Oleh", readonly=True)
    done_at = fields.Datetime(readonly=True)
    skip_reason = fields.Char("Alasan Dilewati")
    source_model = fields.Char(index=True)
    source_id = fields.Integer(index=True)
    minutes_late = fields.Integer(compute="_compute_late", store=True)

    _open_idx = models.Index("(station_id, due_at) WHERE state IN ('due', 'overdue')")

    @api.depends("due_at", "done_at", "state")
    def _compute_late(self):
        for task in self:
            if task.done_at and task.due_at and task.done_at > task.due_at:
                task.minutes_late = int((task.done_at - task.due_at).total_seconds() // 60)
            else:
                task.minutes_late = 0

    def action_done(self, practitioner=None):
        practitioner = practitioner or self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        for task in self:
            if task.state in ("done", "cancelled"):
                raise UserError(_("Tugas '%s' sudah selesai atau dibatalkan.") % task.title)
            task.write({
                "state": "done",
                "done_by_id": practitioner.id if practitioner else False,
                "done_at": fields.Datetime.now(),
            })
            task.env["hms.event"].emit("nursing.task.done", {
                "task_id": task.id, "station_id": task.station_id.id,
                "patient_id": task.patient_id.id,
            })
        return True

    def action_skip(self, reason=None):
        for task in self:
            if not (reason or task.skip_reason):
                raise UserError(
                    _("Alasan melewati tugas wajib dicatat — tugas keperawatan yang "
                      "dilewati tanpa alasan tidak dapat dipertanggungjawabkan.")
                )
            task.write({"state": "skipped", "skip_reason": reason or task.skip_reason})
        return True

    @api.model
    def _cron_mark_overdue(self):
        """Move past-due tasks into the overdue bucket and announce them."""
        now = fields.Datetime.now()
        candidates = self.search([("state", "=", "due")])
        late = candidates.filtered(
            lambda t: t.due_at
            and fields.Datetime.add(t.due_at, minutes=t.window_minutes) < now
        )
        late.write({"state": "overdue"})
        for task in late:
            task.env["hms.event"].emit("nursing.task.overdue", {
                "task_id": task.id, "station_id": task.station_id.id,
                "patient": task.patient_id.name, "title": task.title,
            })
        return len(late)

    @api.model
    def _cron_schedule_vitals(self):
        """Keep every inpatient's vitals schedule one interval ahead.

        The interval shortens automatically for patients whose last EWS was
        high — which is the entire point of an early-warning score.
        """
        settings = self.env["hms.settings"].get_settings()
        default_hours = settings.vitals_interval_hours or 8
        admissions = self.env["hms.admission"].search([("state", "=", "admitted")])
        created = 0
        for admission in admissions:
            pending = self.search_count([
                ("admission_id", "=", admission.id), ("type", "=", "vitals"),
                ("state", "in", ("due", "overdue")),
            ])
            if pending:
                continue
            latest = self.env["hms.ews.score"].search(
                [("admission_id", "=", admission.id)], order="id desc", limit=1
            )
            hours = {"high": 1, "medium": 4}.get(latest.level, default_hours) if latest else default_hours
            station = self.env["hms.nursing.station"].search(
                [("ward_id", "=", admission.ward_id.id)], limit=1
            )
            self.create({
                "admission_id": admission.id,
                "encounter_id": admission.encounter_id.id,
                "patient_id": admission.patient_id.id,
                "station_id": station.id,
                "type": "vitals",
                "title": _("Pengukuran TTV"),
                "due_at": fields.Datetime.add(fields.Datetime.now(), hours=hours),
                "priority": "1" if latest and latest.level == "high" else "0",
            })
            created += 1
        return created


class HmsClinicalNote(models.Model):
    _inherit = "hms.clinical.note"

    def action_sign(self):
        """A doctor's written instruction becomes a nursing task on signing.

        Signing is the right trigger: an unsigned note is still a draft, and
        turning drafts into tasks would have nurses acting on orders the doctor
        has not committed to.
        """
        res = super().action_sign()
        Task = self.env["hms.nursing.task"]
        for note in self:
            if not note.instruction:
                continue
            admission = self.env["hms.admission"].search(
                [("encounter_id", "=", note.encounter_id.id)], limit=1
            )
            station = self.env["hms.nursing.station"].search(
                [("ward_id", "=", admission.ward_id.id)], limit=1
            ) if admission else self.env["hms.nursing.station"]
            Task.create({
                "admission_id": admission.id if admission else False,
                "encounter_id": note.encounter_id.id,
                "patient_id": note.patient_id.id,
                "station_id": station.id,
                "type": "instruction",
                "title": _("Instruksi: %s") % (note.instruction[:60]),
                "detail": note.instruction,
                "due_at": fields.Datetime.add(fields.Datetime.now(), hours=1),
                "source_model": note._name,
                "source_id": note.id,
                "priority": "1",
            })
        return res
