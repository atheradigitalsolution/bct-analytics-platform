# -*- coding: utf-8 -*-
"""Nurse stations and shifts."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsNursingStation(models.Model):
    _name = "hms.nursing.station"
    _description = "Nurse Station"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    type = fields.Selection(
        [("inpatient", "Rawat Inap"), ("emergency", "IGD"), ("outpatient", "Poliklinik")],
        required=True, default="inpatient",
    )
    ward_id = fields.Many2one("hms.ward", "Ruang Rawat")
    unit_id = fields.Many2one("hms.unit", "Unit Layanan")
    location_id = fields.Many2one(
        "stock.location", "Lokasi Floor Stock", domain="[('usage', '=', 'internal')]",
    )
    nurse_ids = fields.Many2many(
        "hms.practitioner", string="Perawat",
        domain="[('type', 'in', ('nurse', 'midwife'))]",
    )
    bed_ids = fields.One2many("hms.bed", compute="_compute_beds", string="Bed")
    admission_ids = fields.One2many("hms.admission", compute="_compute_beds", string="Pasien")
    patient_count = fields.Integer(compute="_compute_beds")
    overdue_task_count = fields.Integer(compute="_compute_task_stats")
    high_ews_count = fields.Integer(compute="_compute_task_stats")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode nurse station harus unik.")

    @api.depends("ward_id")
    def _compute_beds(self):
        for station in self:
            beds = station.ward_id.bed_ids
            station.bed_ids = beds
            admissions = self.env["hms.admission"].search([
                ("ward_id", "=", station.ward_id.id),
                ("state", "in", ("admitted", "discharge_planned")),
            ])
            station.admission_ids = admissions
            station.patient_count = len(admissions)

    def _compute_task_stats(self):
        now = fields.Datetime.now()
        for station in self:
            station.overdue_task_count = self.env["hms.nursing.task"].search_count([
                ("station_id", "=", station.id),
                ("state", "in", ("due", "overdue")),
                ("due_at", "<", now),
            ])
            station.high_ews_count = self.env["hms.ews.score"].search_count([
                ("station_id", "=", station.id), ("level", "=", "high"),
                ("escalated", "=", False),
            ])

    def patient_board(self):
        """Everything the board screen shows, in one query pass."""
        self.ensure_one()
        rows = []
        for admission in self.admission_ids:
            latest_ews = self.env["hms.ews.score"].search(
                [("admission_id", "=", admission.id)], order="id desc", limit=1
            )
            rows.append({
                "admission_id": admission.id,
                "bed": admission.bed_id.code,
                "patient": admission.patient_id.name,
                "mrn": admission.patient_id.mrn,
                "age": admission.patient_id.age_display,
                "dpjp": admission.dpjp_id.display_name,
                "day": admission.length_of_stay,
                "diagnosis": admission.encounter_id.primary_diagnosis_id.display_name or "",
                "ews": latest_ews.score if latest_ews else None,
                "ews_level": latest_ews.level if latest_ews else None,
                "allergy": admission.patient_id.has_allergy,
                "isolation": admission.is_isolation,
                "diet": admission.diet or "",
                "tasks_due": self.env["hms.nursing.task"].search_count([
                    ("admission_id", "=", admission.id), ("state", "in", ("due", "overdue")),
                ]),
            })
        return rows


class HmsNursingShift(models.Model):
    _name = "hms.nursing.shift"
    _description = "Shift Keperawatan"
    _order = "date desc, shift"

    station_id = fields.Many2one("hms.nursing.station", required=True, index=True)
    date = fields.Date(required=True, default=lambda s: fields.Date.context_today(s), index=True)
    shift = fields.Selection(
        [("morning", "Pagi"), ("afternoon", "Siang"), ("night", "Malam")],
        required=True, default="morning",
    )
    time_from = fields.Float("Mulai", default=7.0)
    time_to = fields.Float("Selesai", default=14.0)
    nurse_ids = fields.Many2many("hms.practitioner", string="Perawat Bertugas")
    charge_nurse_id = fields.Many2one("hms.practitioner", "Ketua Tim")
    state = fields.Selection(
        [("planned", "Direncanakan"), ("active", "Berjalan"), ("closed", "Selesai")],
        default="planned", required=True,
    )

    _shift_uniq = models.Constraint(
        "unique(station_id, date, shift)", "Shift untuk station, tanggal dan waktu itu sudah ada.",
    )

    def action_start(self):
        for shift in self:
            if shift.state != "planned":
                raise UserError(_("Shift sudah dimulai atau ditutup."))
            shift.write({"state": "active"})
        return True

    def action_close(self):
        """A shift cannot close while its hand-over is unsigned."""
        for shift in self:
            unsigned = self.env["hms.handover"].search_count([
                ("shift_from_id", "=", shift.id), ("signed_at", "=", False),
            ])
            if unsigned:
                raise UserError(
                    _("%s serah terima belum ditandatangani.") % unsigned
                )
            shift.write({"state": "closed"})
        return True
