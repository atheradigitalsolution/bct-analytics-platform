# -*- coding: utf-8 -*-
"""Practice schedules and the daily slots generated from them."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

WEEKDAYS = [
    ("0", "Senin"), ("1", "Selasa"), ("2", "Rabu"), ("3", "Kamis"),
    ("4", "Jumat"), ("5", "Sabtu"), ("6", "Minggu"),
]


class HmsScheduleTemplate(models.Model):
    _name = "hms.schedule.template"
    _description = "Template Jadwal Praktik"
    _order = "practitioner_id, weekday, time_from"

    practitioner_id = fields.Many2one("hms.practitioner", "Dokter", required=True, index=True,
                                      domain="[('type', 'in', ('doctor', 'dentist'))]")
    unit_id = fields.Many2one("hms.unit", "Poli", required=True)
    weekday = fields.Selection(WEEKDAYS, "Hari", required=True, index=True)
    session = fields.Selection(
        [("morning", "Pagi"), ("afternoon", "Siang"), ("evening", "Sore"), ("night", "Malam")],
        required=True, default="morning",
    )
    time_from = fields.Float("Jam Mulai", required=True, default=8.0)
    time_to = fields.Float("Jam Selesai", required=True, default=12.0)
    slot_minutes = fields.Integer("Durasi Slot (menit)", default=10, required=True)
    quota_walkin = fields.Integer("Kuota Walk-in", default=15)
    quota_booking = fields.Integer("Kuota Booking", default=10)
    quota_bpjs = fields.Integer("Kuota BPJS", default=10)
    room_id = fields.Many2one("hms.room", "Ruang Periksa")
    valid_from = fields.Date("Berlaku Dari", default=lambda s: fields.Date.context_today(s))
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    @api.constrains("time_from", "time_to")
    def _check_times(self):
        for rec in self:
            if rec.time_to <= rec.time_from:
                raise ValidationError(_("Jam selesai harus setelah jam mulai."))

    @api.constrains("practitioner_id", "weekday", "time_from", "time_to", "valid_from", "valid_to")
    def _check_overlap(self):
        """A doctor cannot be in two clinics at once.

        Checked here because the conflict is invisible until two patients are
        booked against the same half hour in different poli.
        """
        for rec in self:
            others = self.search([
                ("id", "!=", rec.id),
                ("practitioner_id", "=", rec.practitioner_id.id),
                ("weekday", "=", rec.weekday),
                ("active", "=", True),
            ])
            for other in others:
                if rec.time_from < other.time_to and other.time_from < rec.time_to:
                    if rec.valid_to and other.valid_from and rec.valid_to < other.valid_from:
                        continue
                    if other.valid_to and rec.valid_from and other.valid_to < rec.valid_from:
                        continue
                    raise ValidationError(
                        _("Jadwal %(d)s pada %(w)s bertabrakan dengan jadwal di %(u)s.")
                        % {"d": rec.practitioner_id.display_name,
                           "w": dict(WEEKDAYS)[rec.weekday], "u": other.unit_id.name}
                    )

    @api.depends("practitioner_id", "unit_id", "weekday")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s %s %02d:%02d" % (
                rec.practitioner_id.display_name or "",
                rec.unit_id.name or "",
                dict(WEEKDAYS).get(rec.weekday, ""),
                int(rec.time_from), int((rec.time_from % 1) * 60),
            )

    def generate_slots(self, date):
        """Materialise this template's slots for one calendar day."""
        self.ensure_one()
        if str(date.weekday()) != self.weekday:
            return self.env["hms.schedule.slot"]
        if self.valid_from and date < self.valid_from:
            return self.env["hms.schedule.slot"]
        if self.valid_to and date > self.valid_to:
            return self.env["hms.schedule.slot"]
        Slot = self.env["hms.schedule.slot"]
        existing = Slot.search([("template_id", "=", self.id), ("date", "=", date)])
        if existing:
            return existing
        blocked = self.env["hms.schedule.exception"].search([
            ("practitioner_id", "=", self.practitioner_id.id),
            ("state", "=", "approved"),
            ("date_from", "<=", date),
            ("date_to", ">=", date),
        ], limit=1)
        vals = []
        cursor = self.time_from
        while cursor + self.slot_minutes / 60.0 <= self.time_to + 1e-6:
            vals.append({
                "template_id": self.id,
                "practitioner_id": self.practitioner_id.id,
                "unit_id": self.unit_id.id,
                "date": date,
                "time_from": cursor,
                "time_to": cursor + self.slot_minutes / 60.0,
                "state": "blocked" if blocked else "open",
                "block_reason": blocked.type if blocked else False,
            })
            cursor += self.slot_minutes / 60.0
        return Slot.create(vals)

    @api.model
    def _cron_generate_slots(self, days_ahead=7):
        """Roll the slot horizon forward every night."""
        today = fields.Date.context_today(self)
        templates = self.search([("active", "=", True)])
        created = 0
        for offset in range(days_ahead + 1):
            date = today + timedelta(days=offset)
            for template in templates:
                created += len(template.generate_slots(date))
        return created


class HmsScheduleSlot(models.Model):
    _name = "hms.schedule.slot"
    _description = "Slot Jadwal Praktik"
    _order = "date, time_from"

    template_id = fields.Many2one("hms.schedule.template", ondelete="cascade", index=True)
    practitioner_id = fields.Many2one("hms.practitioner", required=True, index=True)
    unit_id = fields.Many2one("hms.unit", required=True, index=True)
    date = fields.Date(required=True, index=True)
    time_from = fields.Float("Mulai", required=True)
    time_to = fields.Float("Selesai", required=True)
    state = fields.Selection(
        [("open", "Tersedia"), ("booked", "Dibooking"), ("walkin", "Walk-in"),
         ("blocked", "Diblokir"), ("cancelled", "Dibatalkan")],
        default="open", required=True, index=True,
    )
    ticket_id = fields.Many2one("hms.qms.ticket", "Tiket Antrian", ondelete="set null")
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="set null")
    booking_code = fields.Char("Kode Booking", index=True)
    block_reason = fields.Char("Alasan Blokir")

    _slot_uniq = models.Constraint(
        "unique(practitioner_id, date, time_from)",
        "Slot untuk dokter, tanggal dan jam tersebut sudah ada.",
    )

    def action_block(self, reason=None):
        for slot in self:
            if slot.state in ("booked", "walkin"):
                raise UserError(
                    _("Slot %(d)s %(t)s sudah terisi pasien; alihkan pasiennya lebih dulu.")
                    % {"d": slot.date, "t": slot.time_from}
                )
            slot.write({"state": "blocked", "block_reason": reason})
        return True


class HmsScheduleException(models.Model):
    _name = "hms.schedule.exception"
    _description = "Pengecualian Jadwal (Cuti/Dinas)"
    _order = "date_from desc"

    practitioner_id = fields.Many2one("hms.practitioner", required=True, index=True)
    type = fields.Selection(
        [("leave", "Cuti Tahunan"), ("sick", "Sakit"), ("duty", "Dinas Luar"),
         ("training", "Pendidikan/Seminar"), ("holiday", "Libur Nasional"),
         ("time_change", "Perubahan Jam")],
        required=True, default="leave",
    )
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(required=True, index=True)
    time_from = fields.Float("Jam Mulai")
    time_to = fields.Float("Jam Selesai")
    leave_id = fields.Many2one("hr.leave", "Pengajuan Cuti", ondelete="set null")
    state = fields.Selection(
        [("draft", "Diajukan"), ("approved", "Disetujui"), ("rejected", "Ditolak")],
        default="draft", required=True, index=True,
    )
    replacement_practitioner_id = fields.Many2one("hms.practitioner", "Dokter Pengganti")
    note = fields.Text()
    affected_slot_ids = fields.Many2many("hms.schedule.slot", string="Slot Terdampak",
                                         compute="_compute_affected")
    affected_booked_count = fields.Integer("Pasien Terdampak", compute="_compute_affected")

    @api.constrains("date_from", "date_to")
    def _check_range(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise ValidationError(_("Tanggal selesai mendahului tanggal mulai."))

    @api.depends("practitioner_id", "date_from", "date_to")
    def _compute_affected(self):
        for rec in self:
            slots = self.env["hms.schedule.slot"].search([
                ("practitioner_id", "=", rec.practitioner_id.id),
                ("date", ">=", rec.date_from),
                ("date", "<=", rec.date_to),
                ("state", "!=", "cancelled"),
            ])
            rec.affected_slot_ids = slots
            rec.affected_booked_count = len(slots.filtered(
                lambda s: s.state in ("booked", "walkin")
            ))

    def action_approve(self):
        """Approve and block the slots, surfacing anyone already booked."""
        for rec in self:
            rec.write({"state": "approved"})
            free = rec.affected_slot_ids.filtered(lambda s: s.state == "open")
            free.write({"state": "blocked", "block_reason": rec.type})
            if rec.affected_booked_count:
                rec.env["hms.event"].emit("schedule.changed", {
                    "exception_id": rec.id,
                    "practitioner_id": rec.practitioner_id.id,
                    "booked_affected": rec.affected_booked_count,
                })
        return True

    def action_reassign(self):
        """Move booked slots to the replacement doctor."""
        self.ensure_one()
        if not self.replacement_practitioner_id:
            raise UserError(_("Tentukan dokter pengganti terlebih dahulu."))
        booked = self.affected_slot_ids.filtered(lambda s: s.state in ("booked", "walkin"))
        for slot in booked:
            slot.write({"practitioner_id": self.replacement_practitioner_id.id})
            if slot.encounter_id:
                slot.encounter_id.write({
                    "practitioner_id": self.replacement_practitioner_id.id,
                })
        return len(booked)
