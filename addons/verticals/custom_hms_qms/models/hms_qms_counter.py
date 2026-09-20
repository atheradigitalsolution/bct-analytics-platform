# -*- coding: utf-8 -*-
"""Counters: the desks, rooms and windows that call tickets."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsQmsCounter(models.Model):
    _name = "hms.qms.counter"
    _description = "Loket / Counter Antrian"
    _order = "sequence, code"

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    service_ids = fields.Many2many(
        "hms.qms.service", "hms_qms_counter_service_rel", "counter_id", "service_id",
        string="Melayani", required=True,
    )
    location = fields.Char("Lokasi", help="Lantai/area, ditampilkan di layar TV.")
    state = fields.Selection(
        [("closed", "Tutup"), ("open", "Buka"), ("paused", "Istirahat")],
        default="closed", required=True, index=True,
    )
    current_user_id = fields.Many2one("res.users", "Petugas", readonly=True)
    current_ticket_id = fields.Many2one("hms.qms.ticket", "Tiket Sekarang", readonly=True)
    session_started_at = fields.Datetime(readonly=True)
    device_token = fields.Char(
        "Token Perangkat", copy=False,
        help="Dipakai tablet di pintu ruang yang tidak login penuh.",
    )
    regular_streak = fields.Integer(
        "Reguler Berturut-turut", default=0, readonly=True,
        help="Berapa tiket reguler dipanggil sejak tiket prioritas terakhir. "
             "Dipakai untuk menyisipkan prioritas tanpa menghentikan antrian reguler.",
    )
    is_clinical = fields.Boolean(
        "Buka Encounter saat Memanggil",
        help="Untuk ruang periksa: memanggil pasien langsung membuka layar kunjungannya.",
    )
    served_today = fields.Integer("Dilayani Hari Ini", compute="_compute_stats")
    avg_service_seconds = fields.Integer("Rerata Layanan (detik)", compute="_compute_stats")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode loket harus unik.")

    def _compute_stats(self):
        today = fields.Date.context_today(self)
        for counter in self:
            tickets = self.env["hms.qms.ticket"].search([
                ("counter_id", "=", counter.id), ("date", "=", today),
                ("state", "=", "finished"),
            ])
            counter.served_today = len(tickets)
            durations = [t.service_seconds for t in tickets if t.service_seconds]
            counter.avg_service_seconds = int(sum(durations) / len(durations)) if durations else 0

    # --- session ----------------------------------------------------------
    def action_open(self):
        for counter in self:
            if counter.state == "open":
                raise UserError(_("Loket %s sudah terbuka.") % counter.name)
            counter.write({
                "state": "open",
                "current_user_id": self.env.uid,
                "session_started_at": fields.Datetime.now(),
                # A priority ticket is due first thing: when a counter opens,
                # whoever has been waiting with a priority flag goes first.
                # Starting the streak at the largest interleave among this
                # counter's services expresses exactly that.
                "regular_streak": max(
                    counter.service_ids.mapped("priority_interleave") or [0]
                ),
            })
            counter._emit("qms.counter.opened")
        return True

    def action_pause(self):
        for counter in self:
            if counter.state != "open":
                raise UserError(_("Loket %s tidak sedang terbuka.") % counter.name)
            counter.write({"state": "paused"})
            counter._emit("qms.counter.paused")
        return True

    def action_close(self):
        for counter in self:
            if counter.current_ticket_id.state in ("called", "serving"):
                raise UserError(
                    _("Selesaikan dulu tiket %s sebelum menutup loket.")
                    % counter.current_ticket_id.name
                )
            counter.write({
                "state": "closed", "current_user_id": False, "current_ticket_id": False,
            })
            counter._emit("qms.counter.closed")
        return True

    def _emit(self, topic):
        for counter in self:
            counter.env["hms.event"].emit(topic, {
                "counter_id": counter.id,
                "code": counter.code,
                "name": counter.name,
                "state": counter.state,
                "service_ids": counter.service_ids.ids,
            })

    # --- calling ----------------------------------------------------------
    def action_call_next(self):
        """Take the next ticket for this counter, honouring priority interleave."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Buka loket terlebih dahulu."))
        if self.current_ticket_id.state in ("called", "serving"):
            raise UserError(
                _("Tiket %s masih aktif. Selesaikan, tahan, atau lewati dulu.")
                % self.current_ticket_id.name
            )
        ticket = self._pick_next()
        if not ticket:
            raise UserError(_("Tidak ada antrian menunggu untuk loket ini."))
        ticket.action_call(self)
        self.write({
            "regular_streak": 0 if ticket.priority != "none" else self.regular_streak + 1,
        })
        return ticket

    def _pick_next(self):
        """Choose the next ticket across every service this counter handles.

        Services are consulted in their configured order, so a counter serving
        both KAS and KAS-RANAP drains the first before the second rather than
        alternating unpredictably.
        """
        self.ensure_one()
        Ticket = self.env["hms.qms.ticket"]
        today = fields.Date.context_today(self)
        for service in self.service_ids.sorted("sequence"):
            waiting = Ticket.search([
                ("service_id", "=", service.id),
                ("date", "=", today),
                ("state", "=", "waiting"),
            ], order="sequence")
            if not waiting:
                continue
            priority = waiting.filtered(lambda t: t.priority != "none")
            regular = waiting.filtered(lambda t: t.priority == "none")
            if not priority:
                return regular[:1]
            if not regular:
                return priority[:1]
            interleave = service.priority_interleave
            if interleave <= 0:
                return priority[:1]
            # The streak is kept on the counter rather than derived from
            # timestamps. fields.Datetime.now() truncates to whole seconds, so
            # several calls share one called_at value, and the obvious
            # tie-breaker (id) reflects the order tickets were ISSUED, not the
            # order they were CALLED — which silently starved priority tickets.
            if self.regular_streak >= interleave:
                return priority[:1]
            return regular[:1]
        return Ticket

    def action_recall(self):
        self.ensure_one()
        if not self.current_ticket_id:
            raise UserError(_("Tidak ada tiket yang sedang dipanggil."))
        self.current_ticket_id.action_recall()
        return True

    def action_finish(self):
        self.ensure_one()
        if not self.current_ticket_id:
            raise UserError(_("Tidak ada tiket aktif di loket ini."))
        ticket = self.current_ticket_id
        ticket.action_finish()
        self.write({"current_ticket_id": False})
        return ticket
