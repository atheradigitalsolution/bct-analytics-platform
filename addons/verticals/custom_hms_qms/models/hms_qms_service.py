# -*- coding: utf-8 -*-
"""Service points — anything with its own queue."""
from odoo import _, api, fields, models


class HmsQmsService(models.Model):
    _name = "hms.qms.service"
    _description = "Layanan Antrian"
    _order = "sequence, code"

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    prefix = fields.Char("Prefiks Nomor", required=True, default="A",
                         help="Huruf di depan nomor antrian, mis. A untuk A-012.")
    priority_prefix = fields.Char(
        "Prefiks Prioritas", default="P",
        help="Antrian prioritas memakai deret nomor terpisah agar urutannya tidak "
             "bercampur dengan antrian reguler.",
    )
    unit_id = fields.Many2one("hms.unit", "Unit Layanan")
    per_practitioner = fields.Boolean(
        "Antrian per Dokter",
        help="Bila aktif, setiap dokter punya deret nomornya sendiri di layanan ini.",
    )
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter")
    kind = fields.Selection(
        [("registration", "Pendaftaran"), ("clinic", "Poliklinik"), ("lab", "Laboratorium"),
         ("radiology", "Radiologi"), ("pharmacy", "Apotek"), ("cashier", "Kasir"),
         ("triage", "Triase IGD"), ("records", "Rekam Medis"), ("other", "Lainnya")],
        required=True, default="clinic", index=True,
    )
    daily_reset = fields.Boolean("Reset Harian", default=True)
    sla_minutes = fields.Integer("Target Waktu Tunggu (menit)", default=30)
    priority_interleave = fields.Integer(
        "Sisipan Prioritas", default=3,
        help="Satu tiket prioritas dipanggil setiap N tiket reguler. "
             "Nol berarti prioritas selalu didahulukan.",
    )
    avg_service_seconds = fields.Integer(
        "Rerata Layanan (detik)", compute="_compute_avg_service", store=True,
        help="Rata-rata bergerak dari 20 tiket terakhir yang selesai.",
    )
    next_service_id = fields.Many2one(
        "hms.qms.service", "Tahap Berikutnya Default",
        help="Dipakai bila tidak ada aturan yang lebih spesifik.",
    )
    antrol_task_id = fields.Integer(
        "Task ID Antrol BPJS",
        help="1 mulai tunggu admisi, 2 selesai admisi, 3 mulai tunggu poli, "
             "4 mulai layanan poli, 5 selesai poli, 6 mulai farmasi, 7 selesai farmasi.",
    )
    color = fields.Integer("Warna")
    display_label = fields.Char("Label Display")
    active = fields.Boolean(default=True)

    ticket_ids = fields.One2many("hms.qms.ticket", "service_id", "Tiket")
    waiting_count = fields.Integer("Menunggu", compute="_compute_live")
    serving_ticket_id = fields.Many2one("hms.qms.ticket", compute="_compute_live",
                                        string="Sedang Dilayani")

    _code_uniq = models.Constraint("unique(code)", "Kode layanan antrian harus unik.")

    @api.depends("ticket_ids.service_seconds", "ticket_ids.state")
    def _compute_avg_service(self):
        for service in self:
            done = self.env["hms.qms.ticket"].search([
                ("service_id", "=", service.id),
                ("state", "=", "finished"),
                ("service_seconds", ">", 0),
            ], order="finished_at desc", limit=20)
            durations = done.mapped("service_seconds")
            service.avg_service_seconds = int(sum(durations) / len(durations)) if durations else 0

    def _compute_live(self):
        today = fields.Date.context_today(self)
        for service in self:
            tickets = self.env["hms.qms.ticket"].search([
                ("service_id", "=", service.id), ("date", "=", today),
            ])
            service.waiting_count = len(tickets.filtered(lambda t: t.state == "waiting"))
            service.serving_ticket_id = tickets.filtered(
                lambda t: t.state in ("called", "serving")
            )[:1]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"

    def estimated_wait_minutes(self, position):
        """Rough wait for someone `position` places back in the queue."""
        self.ensure_one()
        per_ticket = self.avg_service_seconds or 300
        return int(position * per_ticket / 60)
