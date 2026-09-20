# -*- coding: utf-8 -*-
"""Shift hand-over in SBAR format."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsHandover(models.Model):
    _name = "hms.handover"
    _description = "Serah Terima Shift (SBAR)"
    _order = "id desc"

    station_id = fields.Many2one("hms.nursing.station", required=True, index=True)
    shift_from_id = fields.Many2one("hms.nursing.shift", "Shift Menyerahkan", index=True)
    shift_to_id = fields.Many2one("hms.nursing.shift", "Shift Menerima")
    admission_id = fields.Many2one("hms.admission", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="admission_id.patient_id", store=True, index=True)

    situation = fields.Text("S — Situasi")
    background = fields.Text("B — Latar Belakang")
    assessment = fields.Text("A — Penilaian")
    recommendation = fields.Text("R — Rekomendasi")
    open_task_summary = fields.Text("Tugas Terbuka", readonly=True)

    given_by_id = fields.Many2one("hms.practitioner", "Diserahkan Oleh")
    received_by_id = fields.Many2one("hms.practitioner", "Diterima Oleh")
    signed_at = fields.Datetime(readonly=True)

    @api.model
    def draft_for(self, admission, shift=None):
        """Pre-fill SBAR from the last 24 hours.

        The nurse still writes the assessment and the recommendation — those
        are judgement. What is filled in is the part that would otherwise be
        copied by hand from four other screens, which is where transcription
        errors come from.
        """
        since = fields.Datetime.subtract(fields.Datetime.now(), hours=24)
        ews = self.env["hms.ews.score"].search(
            [("admission_id", "=", admission.id)], order="id desc", limit=1
        )
        given = self.env["hms.emar.administration"].search([
            ("admission_id", "=", admission.id), ("given_at", ">=", since),
        ])
        open_tasks = self.env["hms.nursing.task"].search([
            ("admission_id", "=", admission.id), ("state", "in", ("due", "overdue")),
        ])
        results = self.env["hms.lab.result"].search([
            ("encounter_id", "=", admission.encounter_id.id),
            ("state", "=", "verified"), ("verified_at", ">=", since),
        ]) if "hms.lab.result" in self.env else self.env["hms.handover"]

        situation = _("%(patient)s, %(age)s, bed %(bed)s, hari rawat ke-%(day)s. Dx: %(dx)s.") % {
            "patient": admission.patient_id.name,
            "age": admission.patient_id.age_display,
            "bed": admission.bed_id.code,
            "day": admission.length_of_stay,
            "dx": admission.encounter_id.primary_diagnosis_id.display_name or _("belum ditegakkan"),
        }
        background_parts = [
            _("DPJP: %s") % admission.dpjp_id.display_name,
            _("Penjamin: %s") % admission.payer_id.name,
        ]
        if admission.patient_id.has_allergy:
            background_parts.append(
                _("ALERGI: %s") % ", ".join(admission.patient_id.allergy_ids.mapped("substance"))
            )
        if admission.is_isolation:
            background_parts.append(_("Pasien dalam isolasi."))
        if admission.diet:
            background_parts.append(_("Diet: %s") % admission.diet)

        assessment_parts = []
        if ews:
            assessment_parts.append(
                _("EWS terakhir %(s)s (%(l)s).") % {"s": ews.score, "l": ews.level}
            )
        if given:
            assessment_parts.append(
                _("Obat 24 jam terakhir: %s.")
                % ", ".join(sorted(set(given.mapped("medicine_id.generic_name"))))
            )
        if results:
            assessment_parts.append(
                _("Hasil lab baru: %s.")
                % ", ".join(f"{r.parameter_id.code} {r.value_numeric:g}" for r in results[:5])
            )

        return self.create({
            "station_id": self.env["hms.nursing.station"].search(
                [("ward_id", "=", admission.ward_id.id)], limit=1
            ).id,
            "shift_from_id": shift.id if shift else False,
            "admission_id": admission.id,
            "situation": situation,
            "background": "\n".join(background_parts),
            "assessment": "\n".join(assessment_parts),
            "open_task_summary": "\n".join(
                f"- {t.title} ({fields.Datetime.to_string(t.due_at)})" for t in open_tasks
            ) or _("Tidak ada tugas terbuka."),
        })

    def action_sign(self):
        for rec in self:
            if rec.signed_at:
                raise UserError(_("Serah terima sudah ditandatangani."))
            if not (rec.given_by_id and rec.received_by_id):
                raise UserError(
                    _("Serah terima harus ditandatangani perawat yang menyerahkan "
                      "dan yang menerima.")
                )
            if rec.given_by_id == rec.received_by_id:
                raise UserError(_("Penyerah dan penerima harus perawat yang berbeda."))
            if not rec.recommendation:
                raise UserError(_("Rekomendasi untuk shift berikutnya wajib diisi."))
            rec.write({"signed_at": fields.Datetime.now()})
            rec.env["hms.event"].emit("handover.signed", {
                "handover_id": rec.id, "admission_id": rec.admission_id.id,
                "station_id": rec.station_id.id,
            })
        return True


class HmsUnitRequest(models.Model):
    _name = "hms.unit.request"
    _description = "Permintaan ke Unit Lain"
    _order = "id desc"

    station_id = fields.Many2one("hms.nursing.station", required=True, index=True)
    admission_id = fields.Many2one("hms.admission", ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="admission_id.patient_id", store=True)
    to_unit = fields.Selection(
        [("pharmacy", "Farmasi"), ("nutrition", "Gizi"), ("lab", "Laboratorium"),
         ("housekeeping", "Kebersihan"), ("transport", "Transporter"),
         ("maintenance", "Pemeliharaan")],
        required=True, index=True,
    )
    type = fields.Char("Jenis Permintaan")
    detail = fields.Text(required=True)
    priority = fields.Selection(
        [("normal", "Normal"), ("urgent", "Segera"), ("cito", "CITO")],
        default="normal", required=True,
    )
    state = fields.Selection(
        [("open", "Terbuka"), ("in_progress", "Diproses"), ("done", "Selesai"),
         ("rejected", "Ditolak")],
        default="open", required=True, index=True,
    )
    requested_by_id = fields.Many2one("res.users", default=lambda s: s.env.user, readonly=True)
    requested_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    handled_by_id = fields.Many2one("res.users", readonly=True)
    handled_at = fields.Datetime(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for req in requests:
            req.env["hms.event"].emit("unit.request.created", {
                "request_id": req.id, "to_unit": req.to_unit,
                "priority": req.priority, "station_id": req.station_id.id,
            })
        return requests

    def action_handle(self):
        self.write({
            "state": "done", "handled_by_id": self.env.uid, "handled_at": fields.Datetime.now(),
        })
        for req in self:
            req.env["hms.event"].emit("unit.request.handled", {"request_id": req.id})
        return True
