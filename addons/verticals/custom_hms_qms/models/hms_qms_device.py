# -*- coding: utf-8 -*-
"""Kiosks, displays and printers."""
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..tools.escpos import EscposBuilder


def _token():
    return secrets.token_urlsafe(24)


class HmsQmsKiosk(models.Model):
    _name = "hms.qms.kiosk"
    _description = "Kiosk Antrian"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    token = fields.Char(required=True, default=lambda s: _token(), copy=False, index=True,
                        help="Dipakai di URL layar kiosk; ganti bila perangkat hilang.")
    service_ids = fields.Many2many(
        "hms.qms.service", "hms_qms_kiosk_service_rel", "kiosk_id", "service_id",
        string="Menu Layanan", required=True,
    )
    priority_enabled = fields.Boolean("Tombol Prioritas", default=True)
    booking_checkin_enabled = fields.Boolean("Check-in Booking", default=True)
    printer_id = fields.Many2one("hms.qms.printer", "Printer")
    header_lines = fields.Text("Kepala Struk")
    footer_lines = fields.Text("Kaki Struk", default="Terima kasih atas kunjungan Anda")
    allowed_ips = fields.Char("IP Diizinkan", help="Daftar dipisah koma; kosong berarti semua.")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode kiosk harus unik.")
    _token_uniq = models.Constraint("unique(token)", "Token kiosk harus unik.")

    def action_regenerate_token(self):
        for kiosk in self:
            kiosk.write({"token": _token()})
        return True

    def menu_payload(self):
        """What the kiosk screen renders. Never includes patient data."""
        self.ensure_one()
        settings = self.env["hms.settings"].get_settings()
        return {
            "kiosk": {"code": self.code, "name": self.name},
            "hospital": settings.hospital_name,
            "priority_enabled": self.priority_enabled,
            "booking_checkin_enabled": self.booking_checkin_enabled,
            "services": [{
                "id": service.id,
                "code": service.code,
                "name": service.display_label or service.name,
                "waiting": service.waiting_count,
                "estimated_minutes": service.estimated_wait_minutes(service.waiting_count),
                "color": service.color,
            } for service in self.service_ids.filtered("active").sorted("sequence")],
        }

    def issue_ticket(self, service_id, priority="none", booking_code=None):
        """Kiosk button press → a ticket plus everything needed to print it."""
        self.ensure_one()
        service = self.service_ids.filtered(lambda s: s.id == service_id)
        if not service:
            raise UserError(_("Layanan tidak tersedia di kiosk ini."))
        ticket = self.env["hms.qms.ticket"].issue(
            service, priority=priority, source="kiosk", kiosk=self, booking_code=booking_code,
        )
        return {
            "ticket": {
                "id": ticket.id,
                "number": ticket.name,
                "service": service.display_label or service.name,
                "position": ticket.position,
                "estimated_minutes": service.estimated_wait_minutes(ticket.position),
                "created_at": fields.Datetime.to_string(ticket.created_at),
            },
            "print": {
                "mode": self.printer_id.type or "browser",
                "printer_id": self.printer_id.id,
            },
        }

    def receipt_bytes(self, ticket):
        """Render the ticket as ESC/POS bytes for this kiosk's printer."""
        self.ensure_one()
        settings = self.env["hms.settings"].get_settings()
        width = 48 if (self.printer_id.paper_width_mm or 80) >= 80 else 32
        builder = EscposBuilder(width=width, codepage=self.printer_id.codepage or "cp437")
        builder.center(settings.hospital_name or "RUMAH SAKIT", bold=True)
        for line in (self.header_lines or "").splitlines():
            builder.center(line)
        builder.line()
        builder.center(ticket.service_id.display_label or ticket.service_id.name)
        builder.feed()
        builder.big(ticket.name)
        builder.feed()
        local = fields.Datetime.context_timestamp(ticket, ticket.created_at)
        builder.columns("Tanggal", local.strftime("%d/%m/%Y"))
        builder.columns("Jam", local.strftime("%H:%M"))
        builder.columns("Antrean di depan", str(max(ticket.position - 1, 0)))
        builder.columns(
            "Estimasi",
            f"{ticket.service_id.estimated_wait_minutes(ticket.position)} menit",
        )
        if ticket.priority != "none":
            builder.center(
                dict(ticket._fields["priority"].selection).get(ticket.priority, ""), bold=True
            )
        builder.line()
        builder.qr(f"{ticket.id}|{self.token}")
        for line in (self.footer_lines or "").splitlines():
            builder.center(line)
        builder.cut()
        return builder.build()


class HmsQmsDisplay(models.Model):
    _name = "hms.qms.display"
    _description = "Layar Antrian"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    token = fields.Char(required=True, default=lambda s: _token(), copy=False, index=True)
    layout = fields.Selection(
        [("single", "Satu Layanan"), ("multi", "Beberapa Layanan"), ("room", "Depan Ruang")],
        default="multi", required=True,
    )
    zone_ids = fields.One2many("hms.qms.display.zone", "display_id", "Zona")
    theme = fields.Text("Tema (JSON)", default='{"primary": "#0d6e74", "accent": "#f5a524"}')
    audio_enabled = fields.Boolean("Suara Panggilan", default=True)
    audio_from = fields.Float("Suara Aktif Dari", default=7.0)
    audio_to = fields.Float("Suara Aktif Sampai", default=20.0)
    running_text = fields.Char("Teks Berjalan")
    allowed_ips = fields.Char("IP Diizinkan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode display harus unik.")
    _token_uniq = models.Constraint("unique(token)", "Token display harus unik.")

    def action_regenerate_token(self):
        for display in self:
            display.write({"token": _token()})
        return True

    def state_payload(self):
        """Cold-start snapshot; afterwards the screen follows SSE events."""
        self.ensure_one()
        settings = self.env["hms.settings"].get_settings()
        Ticket = self.env["hms.qms.ticket"]
        today = fields.Date.context_today(self)
        zones = []
        for zone in self.zone_ids.sorted("position"):
            services = zone.service_ids or zone.counter_ids.mapped("service_ids")
            calling = Ticket.search([
                ("service_id", "in", services.ids), ("date", "=", today),
                ("state", "in", ("called", "serving")),
            ] + ([("counter_id", "in", zone.counter_ids.ids)] if zone.counter_ids else []),
                order="called_at desc", limit=zone.max_items or 4)
            upcoming = Ticket.search([
                ("service_id", "in", services.ids), ("date", "=", today),
                ("state", "=", "waiting"),
            ], order="sequence", limit=zone.max_items or 5)
            zones.append({
                "position": zone.position,
                "kind": zone.kind,
                "title": zone.title or "",
                "calling": [{
                    "number": t.name, "counter": t.counter_id.name,
                    "patient": t._masked_patient_name(),
                    "service": t.service_id.display_label or t.service_id.name,
                } for t in calling],
                "next": [{"number": t.name, "service": t.service_id.code} for t in upcoming],
                "stats": [{
                    "service": s.display_label or s.name,
                    "waiting": s.waiting_count,
                    "estimated_minutes": s.estimated_wait_minutes(s.waiting_count),
                } for s in services],
                "running_text": self.running_text or "",
            })
        return {
            "display": {"code": self.code, "name": self.name, "layout": self.layout},
            "hospital": settings.hospital_name,
            "theme": self.theme,
            "audio": {
                "enabled": self.audio_enabled,
                "from": self.audio_from,
                "to": self.audio_to,
            },
            "zones": zones,
        }


class HmsQmsDisplayZone(models.Model):
    _name = "hms.qms.display.zone"
    _description = "Zona Layar Antrian"
    _order = "position"

    display_id = fields.Many2one("hms.qms.display", required=True, ondelete="cascade")
    position = fields.Integer("Posisi", default=1, required=True)
    kind = fields.Selection(
        [("calling", "Panggilan Aktif"), ("next_list", "Antrian Berikutnya"),
         ("stats", "Statistik"), ("media", "Media"), ("clock", "Jam")],
        required=True, default="calling",
    )
    title = fields.Char("Judul")
    service_ids = fields.Many2many("hms.qms.service", string="Layanan")
    counter_ids = fields.Many2many("hms.qms.counter", string="Loket")
    max_items = fields.Integer("Maks Item", default=5)


class HmsQmsPrinter(models.Model):
    _name = "hms.qms.printer"
    _description = "Printer Antrian"
    _order = "name"

    name = fields.Char(required=True)
    type = fields.Selection(
        [("escpos_network", "ESC/POS Jaringan (TCP 9100)"),
         ("escpos_usb_agent", "ESC/POS USB lewat Agen"),
         ("browser", "Cetak lewat Browser")],
        required=True, default="browser",
    )
    host = fields.Char("Alamat IP")
    port = fields.Integer("Port", default=9100)
    agent_id = fields.Many2one("hms.qms.print.agent", "Agen Cetak")
    paper_width_mm = fields.Selection(
        [("58", "58 mm"), ("80", "80 mm")], default="80", required=True,
    )
    codepage = fields.Char("Code Page", default="cp437")
    cut = fields.Boolean("Potong Kertas", default=True)
    active = fields.Boolean(default=True)

    def send(self, payload):
        """Deliver ESC/POS bytes, by whichever route this printer uses."""
        self.ensure_one()
        if self.type == "escpos_network":
            return self._send_socket(payload)
        if self.type == "escpos_usb_agent":
            return self._queue_for_agent(payload)
        # Browser printing is handled entirely on the kiosk page.
        return False

    def _send_socket(self, payload):
        import socket
        if not self.host:
            raise UserError(_("Printer %s belum punya alamat IP.") % self.name)
        try:
            with socket.create_connection((self.host, self.port or 9100), timeout=5) as sock:
                sock.sendall(payload)
        except OSError as exc:
            raise UserError(
                _("Printer %(n)s tidak dapat dihubungi di %(h)s:%(p)s — %(e)s")
                % {"n": self.name, "h": self.host, "p": self.port, "e": exc}
            ) from exc
        return True

    def _queue_for_agent(self, payload):
        if not self.agent_id:
            raise UserError(_("Printer %s belum terhubung ke agen cetak.") % self.name)
        return self.env["hms.qms.print.job"].create({
            "printer_id": self.id,
            "agent_id": self.agent_id.id,
            "payload": payload.hex(),
        })

    def action_test_print(self):
        self.ensure_one()
        builder = EscposBuilder(width=48 if self.paper_width_mm == "80" else 32)
        builder.center("TES CETAK", bold=True).line()
        builder.big("A-000")
        builder.center("Printer siap digunakan")
        builder.cut()
        self.send(builder.build())
        return True


class HmsQmsPrintAgent(models.Model):
    _name = "hms.qms.print.agent"
    _description = "Agen Cetak Kiosk"

    name = fields.Char(required=True)
    token = fields.Char(required=True, default=lambda s: _token(), copy=False, index=True)
    last_seen = fields.Datetime("Terakhir Terlihat", readonly=True)
    version = fields.Char(readonly=True)
    printer_ids = fields.One2many("hms.qms.printer", "agent_id", "Printer")
    is_online = fields.Boolean("Online", compute="_compute_online")
    active = fields.Boolean(default=True)

    _token_uniq = models.Constraint("unique(token)", "Token agen cetak harus unik.")

    def _compute_online(self):
        """Two minutes without a heartbeat counts as offline.

        The agent polls every second, so anything beyond a couple of minutes
        means the kiosk PC is off or the network is down — and a kiosk that
        cannot print must stop offering to.
        """
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), minutes=2)
        for agent in self:
            agent.is_online = bool(agent.last_seen and agent.last_seen >= cutoff)

    def heartbeat(self, version=None):
        self.ensure_one()
        self.sudo().write({"last_seen": fields.Datetime.now(), "version": version})
        return True


class HmsQmsPrintJob(models.Model):
    _name = "hms.qms.print.job"
    _description = "Antrian Cetak Agen"
    _order = "id"

    printer_id = fields.Many2one("hms.qms.printer", required=True, ondelete="cascade")
    agent_id = fields.Many2one("hms.qms.print.agent", required=True, ondelete="cascade", index=True)
    payload = fields.Text("Payload (hex)", required=True)
    state = fields.Selection(
        [("pending", "Menunggu"), ("sent", "Dikirim"), ("acked", "Selesai"), ("failed", "Gagal")],
        default="pending", required=True, index=True,
    )
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    acked_at = fields.Datetime()
    error = fields.Char()

    @api.model
    def _gc(self, keep_days=2):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=keep_days)
        old = self.search([("created_at", "<", cutoff)])
        count = len(old)
        old.unlink()
        return count
