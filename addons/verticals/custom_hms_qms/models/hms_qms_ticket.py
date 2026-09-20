# -*- coding: utf-8 -*-
"""Tickets and the journey that chains them."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

PRIORITIES = [
    ("none", "Reguler"),
    ("elderly", "Lansia"),
    ("disability", "Disabilitas"),
    ("pregnant", "Ibu Hamil"),
    ("infant", "Bayi"),
    ("result", "Kembali Membawa Hasil"),
    ("emergency", "Gawat Darurat"),
]

TICKET_STATES = [
    ("booked", "Booking"),
    ("waiting", "Menunggu"),
    ("called", "Dipanggil"),
    ("serving", "Dilayani"),
    ("held", "Ditahan"),
    ("finished", "Selesai"),
    ("no_show", "Tidak Hadir"),
    ("transferred", "Dipindahkan"),
    ("cancelled", "Dibatalkan"),
    ("expired", "Kedaluwarsa"),
]


class HmsQmsJourney(models.Model):
    _name = "hms.qms.journey"
    _description = "Perjalanan Antrian Pasien"
    _order = "id desc"

    encounter_id = fields.Many2one("hms.encounter", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    ticket_ids = fields.One2many("hms.qms.ticket", "journey_id", "Tiket")
    current_stage = fields.Integer("Tahap Sekarang", default=0)
    state = fields.Selection(
        [("active", "Berjalan"), ("done", "Selesai"), ("abandoned", "Ditinggalkan")],
        default="active", required=True,
    )
    total_wait_seconds = fields.Integer("Total Menunggu (detik)", compute="_compute_totals")
    total_service_seconds = fields.Integer("Total Dilayani (detik)", compute="_compute_totals")

    _encounter_uniq = models.Constraint(
        "unique(encounter_id)", "Satu kunjungan hanya punya satu perjalanan antrian.",
    )

    @api.depends("ticket_ids.wait_seconds", "ticket_ids.service_seconds")
    def _compute_totals(self):
        for journey in self:
            journey.total_wait_seconds = sum(journey.ticket_ids.mapped("wait_seconds"))
            journey.total_service_seconds = sum(journey.ticket_ids.mapped("service_seconds"))


class HmsQmsTicket(models.Model):
    _name = "hms.qms.ticket"
    _description = "Tiket Antrian"
    _order = "date desc, sequence"

    name = fields.Char("Nomor", required=True, readonly=True, index=True)
    service_id = fields.Many2one("hms.qms.service", "Layanan", required=True,
                                 ondelete="restrict", index=True)
    date = fields.Date(required=True, default=lambda s: fields.Date.context_today(s), index=True)
    sequence = fields.Integer("Urutan", required=True)
    priority = fields.Selection(PRIORITIES, default="none", required=True, index=True)
    state = fields.Selection(TICKET_STATES, default="waiting", required=True, index=True)

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="set null", index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", ondelete="set null", index=True)
    journey_id = fields.Many2one("hms.qms.journey", "Perjalanan", ondelete="set null", index=True)
    stage_no = fields.Integer("Tahap Ke-", default=1)

    counter_id = fields.Many2one("hms.qms.counter", "Loket", ondelete="set null")
    called_by_id = fields.Many2one("res.users", "Dipanggil Oleh", readonly=True)
    booking_code = fields.Char("Kode Booking", index=True)
    source = fields.Selection(
        [("kiosk", "Kiosk"), ("registration", "Pendaftaran"), ("clinical", "Alur Klinis"),
         ("booking", "Booking Online"), ("manual", "Manual Petugas"), ("antrol", "Antrean BPJS")],
        default="kiosk", required=True,
    )
    kiosk_id = fields.Many2one("hms.qms.kiosk", "Kiosk", ondelete="set null")

    created_at = fields.Datetime("Diambil", default=fields.Datetime.now, required=True, index=True)
    called_at = fields.Datetime("Dipanggil", readonly=True)
    serving_at = fields.Datetime("Mulai Dilayani", readonly=True)
    finished_at = fields.Datetime("Selesai", readonly=True)
    call_count = fields.Integer("Jumlah Panggilan", default=0, readonly=True)
    wait_seconds = fields.Integer("Menunggu (detik)", compute="_compute_durations", store=True)
    service_seconds = fields.Integer("Dilayani (detik)", compute="_compute_durations", store=True)
    estimated_at = fields.Datetime("Estimasi Dipanggil")
    position = fields.Integer("Posisi Antrian", compute="_compute_position")
    note = fields.Char()
    log_ids = fields.One2many("hms.qms.ticket.log", "ticket_id", "Riwayat")

    _number_uniq = models.Constraint(
        "unique(service_id, date, name)", "Nomor antrian sudah dipakai hari ini.",
    )
    _queue_idx = models.Index("(service_id, date, state, sequence)")

    @api.depends("created_at", "called_at", "serving_at", "finished_at")
    def _compute_durations(self):
        for ticket in self:
            if ticket.called_at and ticket.created_at:
                ticket.wait_seconds = int((ticket.called_at - ticket.created_at).total_seconds())
            else:
                ticket.wait_seconds = 0
            start = ticket.serving_at or ticket.called_at
            if ticket.finished_at and start:
                ticket.service_seconds = int((ticket.finished_at - start).total_seconds())
            else:
                ticket.service_seconds = 0

    def _compute_position(self):
        for ticket in self:
            if ticket.state != "waiting":
                ticket.position = 0
                continue
            ticket.position = self.search_count([
                ("service_id", "=", ticket.service_id.id),
                ("date", "=", ticket.date),
                ("state", "=", "waiting"),
                ("sequence", "<", ticket.sequence),
            ]) + 1

    # --- issuing ----------------------------------------------------------
    @api.model
    def issue(self, service, priority="none", encounter=None, patient=None, source="kiosk",
              kiosk=None, booking_code=None, stage_no=1, journey=None):
        """Hand out the next number for a service.

        The sequence is taken with a row lock on the service so two kiosks
        pressing the same button at the same moment cannot receive the same
        number — the one failure mode a queue system must never have.
        """
        today = fields.Date.context_today(self)
        self.env.cr.execute(
            "SELECT id FROM hms_qms_service WHERE id = %s FOR UPDATE", (service.id,)
        )
        prefix = service.priority_prefix if priority != "none" else service.prefix
        self.env.cr.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) FROM hms_qms_ticket
             WHERE service_id = %s AND date = %s AND name LIKE %s
            """,
            (service.id, today, f"{prefix}-%"),
        )
        next_seq = (self.env.cr.fetchone()[0] or 0) + 1
        ticket = self.create({
            "name": f"{prefix}-{next_seq:03d}",
            "service_id": service.id,
            "date": today,
            "sequence": next_seq,
            "priority": priority,
            "encounter_id": encounter.id if encounter else False,
            "patient_id": (patient or (encounter.patient_id if encounter else False)).id
            if (patient or encounter) else False,
            "journey_id": journey.id if journey else False,
            "stage_no": stage_no,
            "source": source,
            "kiosk_id": kiosk.id if kiosk else False,
            "booking_code": booking_code,
            "state": "booked" if source == "booking" else "waiting",
        })
        ticket._log("", ticket.state, reason=_("Tiket diterbitkan"))
        ticket._emit("qms.ticket.created")
        return ticket

    # --- state machine ----------------------------------------------------
    def _log(self, from_state, to_state, reason=None):
        self.env["hms.qms.ticket.log"].sudo().create([{
            "ticket_id": ticket.id,
            "from_state": from_state,
            "to_state": to_state,
            "counter_id": ticket.counter_id.id,
            "user_id": self.env.uid,
            "reason": reason,
        } for ticket in self])

    def _emit(self, topic):
        for ticket in self:
            ticket.env["hms.event"].emit(topic, {
                "ticket_id": ticket.id,
                "number": ticket.name,
                "service_id": ticket.service_id.id,
                "service": ticket.service_id.display_label or ticket.service_id.name,
                "counter_id": ticket.counter_id.id,
                "counter": ticket.counter_id.name or "",
                "state": ticket.state,
                "priority": ticket.priority,
                "patient": ticket._masked_patient_name(),
                "waiting": ticket.service_id.waiting_count,
            })

    def _masked_patient_name(self):
        """Public displays show a masked name, never the full one."""
        self.ensure_one()
        if not self.patient_id:
            return ""
        settings = self.env["hms.settings"].get_settings()
        name = self.patient_id.name
        if not settings.name_masking:
            return name
        parts = []
        for word in name.split():
            parts.append(word[:3] + "*" * max(len(word) - 3, 1) if len(word) > 1 else word)
        return " ".join(parts)

    def action_call(self, counter=None):
        for ticket in self:
            if ticket.state not in ("waiting", "held", "no_show"):
                raise UserError(
                    _("Tiket %s tidak dalam antrian.") % ticket.name
                )
            counter = counter or ticket.counter_id
            if not counter:
                raise UserError(_("Tentukan loket pemanggil."))
            previous = ticket.state
            ticket.write({
                "state": "called",
                "counter_id": counter.id,
                "called_at": fields.Datetime.now(),
                "called_by_id": self.env.uid,
                "call_count": ticket.call_count + 1,
            })
            counter.write({"current_ticket_id": ticket.id})
            ticket._log(previous, "called")
            ticket._emit("qms.ticket.called")
        return True

    def action_recall(self):
        settings = self.env["hms.settings"].get_settings()
        for ticket in self:
            if ticket.state not in ("called", "serving"):
                raise UserError(_("Tiket %s tidak sedang dipanggil.") % ticket.name)
            ticket.write({"call_count": ticket.call_count + 1})
            ticket._log(ticket.state, ticket.state, reason=_("Panggil ulang"))
            ticket._emit("qms.ticket.recalled")
            if ticket.call_count >= (settings.max_call_count or 3) and ticket.state == "called":
                ticket.action_no_show()
        return True

    def action_serve(self):
        for ticket in self:
            if ticket.state != "called":
                raise UserError(_("Tiket %s belum dipanggil.") % ticket.name)
            ticket.write({"state": "serving", "serving_at": fields.Datetime.now()})
            ticket._log("called", "serving")
            ticket._emit("qms.ticket.served")
        return True

    def action_hold(self, reason=None):
        for ticket in self:
            if ticket.state not in ("called", "serving"):
                raise UserError(_("Hanya tiket aktif yang dapat ditahan."))
            previous = ticket.state
            ticket.write({"state": "held"})
            ticket.counter_id.write({"current_ticket_id": False})
            ticket._log(previous, "held", reason=reason)
            ticket._emit("qms.ticket.held")
        return True

    def action_no_show(self):
        for ticket in self:
            previous = ticket.state
            ticket.write({"state": "no_show"})
            ticket.counter_id.write({"current_ticket_id": False})
            ticket._log(previous, "no_show")
            ticket._emit("qms.ticket.no_show")
        return True

    def action_restore(self):
        """Bring a no-show back without losing its place.

        The original sequence is kept, so a patient who stepped out returns
        near where they were rather than at the end — which is what the desk
        would do manually anyway.
        """
        settings = self.env["hms.settings"].get_settings()
        limit = settings.no_show_recover_minutes or 30
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.state != "no_show":
                raise UserError(_("Tiket %s bukan tiket tidak hadir.") % ticket.name)
            elapsed = (now - (ticket.called_at or ticket.created_at)).total_seconds() / 60
            if elapsed > limit:
                raise UserError(
                    _("Tiket %(n)s sudah lewat %(m)s menit; pasien harus mengambil nomor baru.")
                    % {"n": ticket.name, "m": int(elapsed)}
                )
            ticket.write({"state": "waiting", "call_count": 0})
            ticket._log("no_show", "waiting", reason=_("Dipulihkan"))
            ticket._emit("qms.ticket.created")
        return True

    def action_finish(self):
        for ticket in self:
            if ticket.state not in ("called", "serving"):
                raise UserError(_("Tiket %s tidak sedang dilayani.") % ticket.name)
            previous = ticket.state
            ticket.write({"state": "finished", "finished_at": fields.Datetime.now()})
            ticket.counter_id.write({"current_ticket_id": False})
            ticket._log(previous, "finished")
            ticket._emit("qms.ticket.finished")
            ticket._advance_journey()
        return True

    def action_transfer(self, service, keep_number=False):
        """Send the patient to another service, optionally keeping the number."""
        self.ensure_one()
        if self.state in ("finished", "cancelled"):
            raise UserError(_("Tiket %s sudah selesai.") % self.name)
        new_ticket = self.issue(
            service,
            priority=self.priority,
            encounter=self.encounter_id,
            patient=self.patient_id,
            source="manual",
            stage_no=self.stage_no + 1,
            journey=self.journey_id,
        )
        if keep_number:
            new_ticket.sudo().write({"name": self.name})
        self.write({"state": "transferred"})
        self.counter_id.write({"current_ticket_id": False})
        self._log(self.state, "transferred", reason=service.name)
        self._emit("qms.ticket.transferred")
        return new_ticket

    def action_cancel(self):
        for ticket in self:
            ticket.write({"state": "cancelled"})
            ticket._log(ticket.state, "cancelled")
        return True

    def _advance_journey(self):
        """Issue the next stage when the service defines one."""
        self.ensure_one()
        if not self.journey_id or not self.service_id.next_service_id:
            return False
        return self.issue(
            self.service_id.next_service_id,
            priority=self.priority,
            encounter=self.encounter_id,
            patient=self.patient_id,
            source="clinical",
            stage_no=self.stage_no + 1,
            journey=self.journey_id,
        )

    @api.model
    def _cron_expire_bookings(self):
        """Bookings not checked in by the cutoff free their slot."""
        settings = self.env["hms.settings"].get_settings()
        cutoff = fields.Datetime.subtract(
            fields.Datetime.now(), minutes=settings.booking_checkin_before_minutes or 30
        )
        stale = self.search([
            ("state", "=", "booked"),
            ("date", "<=", fields.Date.context_today(self)),
            ("created_at", "<", cutoff),
        ])
        stale.write({"state": "expired"})
        return len(stale)


class HmsQmsTicketLog(models.Model):
    _name = "hms.qms.ticket.log"
    _description = "Riwayat Tiket Antrian"
    _order = "id desc"
    _log_access = False

    ticket_id = fields.Many2one("hms.qms.ticket", required=True, ondelete="cascade", index=True)
    service_id = fields.Many2one(related="ticket_id.service_id", store=True, index=True)
    from_state = fields.Char()
    to_state = fields.Char(required=True, index=True)
    counter_id = fields.Many2one("hms.qms.counter")
    user_id = fields.Many2one("res.users")
    at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    reason = fields.Char()
