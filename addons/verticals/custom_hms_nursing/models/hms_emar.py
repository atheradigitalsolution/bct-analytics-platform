# -*- coding: utf-8 -*-
"""Electronic medication administration record."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsEmarSchedule(models.Model):
    _name = "hms.emar.schedule"
    _description = "Jadwal Pemberian Obat"
    _order = "scheduled_at, id"

    prescription_line_id = fields.Many2one("hms.prescription.line", required=True,
                                           ondelete="cascade", index=True)
    admission_id = fields.Many2one("hms.admission", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="admission_id.patient_id", store=True, index=True)
    station_id = fields.Many2one("hms.nursing.station", index=True)
    medicine_id = fields.Many2one(related="prescription_line_id.medicine_id", store=True)
    product_id = fields.Many2one(related="prescription_line_id.product_id", store=True)
    dose = fields.Float("Dosis")
    dose_unit = fields.Char("Satuan")
    route_id = fields.Many2one("hms.route", "Rute")
    scheduled_at = fields.Datetime("Dijadwalkan", required=True, index=True)
    is_prn = fields.Boolean("Bila Perlu")
    is_high_alert = fields.Boolean(related="medicine_id.is_high_alert", store=True)
    state = fields.Selection(
        [("due", "Jatuh Tempo"), ("given", "Diberikan"), ("held", "Ditunda"),
         ("refused", "Ditolak Pasien"), ("omitted", "Tidak Diberikan"),
         ("cancelled", "Dibatalkan")],
        default="due", required=True, index=True,
    )
    administration_ids = fields.One2many("hms.emar.administration", "schedule_id", "Pemberian")

    _due_idx = models.Index("(station_id, scheduled_at) WHERE state = 'due'")

    @api.model
    def generate_for_prescription(self, prescription):
        """Expand an inpatient prescription into per-dose slots.

        Times come from the frequency master, so "3x1" means 08:00/16:00/00:00
        for every drug in the hospital rather than whatever each nurse assumes.
        """
        admission = self.env["hms.admission"].search(
            [("encounter_id", "=", prescription.encounter_id.id)], limit=1
        )
        if not admission:
            return self.browse()
        station = self.env["hms.nursing.station"].search(
            [("ward_id", "=", admission.ward_id.id)], limit=1
        )
        created = self.browse()
        start = fields.Datetime.now()
        for line in prescription.line_ids.filtered(lambda l: l.state != "cancelled"):
            times = line.frequency_id.get_times() if line.frequency_id else [(8, 0)]
            days = max(line.duration_days or 1, 1)
            for day in range(days):
                for hour, minute in times or [(8, 0)]:
                    moment = (start + timedelta(days=day)).replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    if moment < start and day == 0:
                        continue
                    created |= self.create({
                        "prescription_line_id": line.id,
                        "admission_id": admission.id,
                        "station_id": station.id,
                        "dose": line.dose,
                        "dose_unit": line.dose_unit,
                        "route_id": line.route_id.id,
                        "scheduled_at": moment,
                        "is_prn": line.is_prn,
                    })
        return created

    def action_open_administration(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "hms.emar.administration",
            "view_mode": "form",
            "target": "new",
            "context": {"default_schedule_id": self.id},
        }


class HmsEmarAdministration(models.Model):
    _name = "hms.emar.administration"
    _description = "Pencatatan Pemberian Obat"
    _order = "given_at desc, id desc"

    schedule_id = fields.Many2one("hms.emar.schedule", required=True, ondelete="cascade",
                                  index=True)
    admission_id = fields.Many2one(related="schedule_id.admission_id", store=True, index=True)
    patient_id = fields.Many2one(related="schedule_id.patient_id", store=True, index=True)
    medicine_id = fields.Many2one(related="schedule_id.medicine_id", store=True)
    is_high_alert = fields.Boolean(related="schedule_id.is_high_alert", store=True)
    outcome = fields.Selection(
        [("given", "Diberikan"), ("held", "Ditunda"), ("refused", "Ditolak Pasien"),
         ("omitted", "Tidak Diberikan")],
        required=True, default="given",
    )
    given_at = fields.Datetime("Waktu Aktual", default=fields.Datetime.now, required=True)
    given_by_id = fields.Many2one("hms.practitioner", "Perawat", required=True,
                                  default=lambda s: s._default_nurse())
    witness_id = fields.Many2one(
        "hms.practitioner", "Saksi (Double-Check)",
        domain="[('can_double_check_high_alert', '=', True)]",
    )
    dose_given = fields.Float("Dosis Diberikan")
    site = fields.Char("Lokasi Pemberian")
    patient_scanned = fields.Boolean("Gelang Pasien Dipindai")
    medication_scanned = fields.Boolean("Label Obat Dipindai")
    reason = fields.Char("Alasan (bila tidak diberikan)")
    note = fields.Char()
    stock_move_id = fields.Many2one("stock.move", readonly=True)

    @api.model
    def _default_nurse(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    @api.constrains("witness_id", "given_by_id", "outcome")
    def _check_double_check(self):
        """High-alert drugs need a second, qualified pair of eyes.

        This is one of the few hard stops in the system: the whole point of the
        high-alert designation is that a single nurse's judgement is not enough.
        """
        for rec in self:
            if rec.outcome != "given" or not rec.is_high_alert:
                continue
            if not rec.witness_id:
                raise ValidationError(
                    _("Obat high-alert '%s' memerlukan saksi double-check.")
                    % rec.medicine_id.display_name
                )
            if rec.witness_id == rec.given_by_id:
                raise ValidationError(
                    _("Saksi double-check harus perawat yang berbeda.")
                )
            if not rec.witness_id.can_double_check_high_alert:
                raise ValidationError(
                    _("%s belum berwenang menjadi saksi obat high-alert.")
                    % rec.witness_id.display_name
                )

    @api.constrains("outcome", "reason")
    def _check_reason(self):
        for rec in self:
            if rec.outcome != "given" and not rec.reason:
                raise ValidationError(
                    _("Obat yang tidak diberikan wajib disertai alasan.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.schedule_id.write({"state": rec.outcome})
            rec.env["hms.event"].emit("emar.given", {
                "administration_id": rec.id,
                "schedule_id": rec.schedule_id.id,
                "patient_id": rec.patient_id.id,
                "outcome": rec.outcome,
                "high_alert": rec.is_high_alert,
            })
            rec._close_task()
        return records

    def _close_task(self):
        """Tick off the matching nursing task, if one was generated."""
        self.ensure_one()
        task = self.env["hms.nursing.task"].search([
            ("source_model", "=", "hms.emar.schedule"),
            ("source_id", "=", self.schedule_id.id),
            ("state", "in", ("due", "overdue")),
        ], limit=1)
        if task:
            task.action_done(self.given_by_id)
        return True


class HmsPrescription(models.Model):
    _inherit = "hms.prescription"

    emar_schedule_ids = fields.One2many(
        "hms.emar.schedule", "prescription_line_id", compute="_compute_emar", string="Jadwal eMAR",
    )

    def _compute_emar(self):
        for rx in self:
            rx.emar_schedule_ids = self.env["hms.emar.schedule"].search([
                ("prescription_line_id", "in", rx.line_ids.ids),
            ])

    def action_dispense(self):
        """Dispensing an inpatient prescription opens its administration record."""
        res = super().action_dispense()
        for rx in self.filtered(lambda r: r.type == "inpatient"):
            schedules = self.env["hms.emar.schedule"].generate_for_prescription(rx)
            Task = self.env["hms.nursing.task"]
            for schedule in schedules:
                Task.create({
                    "admission_id": schedule.admission_id.id,
                    "encounter_id": rx.encounter_id.id,
                    "patient_id": schedule.patient_id.id,
                    "station_id": schedule.station_id.id,
                    "type": "medication",
                    "title": _("Beri %s") % schedule.medicine_id.display_name,
                    "due_at": schedule.scheduled_at,
                    "window_minutes": 30,
                    "priority": "1" if schedule.is_high_alert else "0",
                    "source_model": schedule._name,
                    "source_id": schedule.id,
                })
        return res
