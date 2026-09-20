# -*- coding: utf-8 -*-
"""Penjadwalan tindakan / operasi.

KENAPA PENUNDAAN HARUS BERUPA RECORD, BUKAN TANGGAL YANG BERUBAH
----------------------------------------------------------------
Indikator Nasional Mutu "penundaan operasi elektif" menghitung berapa banyak
operasi terencana yang tidak jadi dikerjakan pada jadwalnya, dan karena apa.
Bila penundaan dikerjakan dengan mengetik ulang ``planned_start``, angka itu
tidak pernah bisa dihitung: jadwal yang lama hilang tanpa bekas dan semua
operasi tampak selalu tepat waktu.

Karena itu ``postponed`` adalah status tersendiri dengan ``postpone_reason``
yang WAJIB, jumlah penundaan yang dicacah, dan jejak jadwal semula. Aturannya
ditegakkan di ``@api.constrains`` — bukan hanya di tombol — supaya jalur API
dan impor data tidak bisa melewatinya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PROCEDURE_STATES = [
    ("planned", "Direncanakan"),
    ("confirmed", "Dikonfirmasi"),
    ("in_progress", "Berlangsung"),
    ("done", "Selesai"),
    ("postponed", "Ditunda"),
    ("cancelled", "Dibatalkan"),
]

# Kategori penundaan. Dipilih, bukan diketik, karena INM menuntut
# pengelompokan sebab — dan sebab yang diketik bebas tidak bisa dikelompokkan.
POSTPONE_REASONS = [
    ("patient", "Faktor Pasien (belum puasa, menolak, tidak hadir)"),
    ("clinical", "Kondisi Klinis Belum Layak"),
    ("preparation", "Persiapan / Pemeriksaan Penunjang Belum Lengkap"),
    ("team", "Tim Operasi Tidak Tersedia"),
    ("facility", "Ruang / Alat Tidak Tersedia"),
    ("emergency", "Didahului Kasus Emergensi"),
    ("administrative", "Administrasi / Penjaminan Belum Selesai"),
    ("other", "Lainnya"),
]


class HmsProcedureSchedule(models.Model):
    _name = "hms.procedure.schedule"
    _description = "Jadwal Tindakan / Operasi"
    _inherit = ["hms.audited"]
    _order = "planned_start desc, id desc"

    name = fields.Char("Tindakan", compute="_compute_name", store=True, readonly=False)
    order_line_id = fields.Many2one(
        "hms.order.line", "Baris Order", required=True, ondelete="cascade", index=True,
        domain="[('order_type', '=', 'procedure')]",
    )
    order_id = fields.Many2one(related="order_line_id.order_id", store=True, index=True)
    encounter_id = fields.Many2one(related="order_line_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="order_line_id.patient_id", store=True, index=True)
    practitioner_id = fields.Many2one(
        "hms.practitioner", "Operator",
        help="Dokter pelaksana tindakan. Kosong berarti mengikuti dokter pemesan.",
    )
    unit_id = fields.Many2one(
        "hms.unit", "Unit Pelaksana", compute="_compute_unit_id", store=True, readonly=False,
        index=True,
    )
    room_id = fields.Many2one("hms.room", "Ruang / Kamar Operasi")

    planned_start = fields.Datetime("Rencana Mulai", index=True)
    planned_end = fields.Datetime("Rencana Selesai")
    actual_start = fields.Datetime("Mulai", readonly=True)
    actual_end = fields.Datetime("Selesai", readonly=True)
    duration_minutes = fields.Integer(
        "Durasi Nyata (menit)", compute="_compute_duration_minutes", store=True,
    )
    is_elective = fields.Boolean(
        "Elektif", default=True, index=True,
        help="Tindakan terencana, bukan emergensi. Hanya tindakan elektif yang "
             "masuk hitungan indikator mutu penundaan operasi.",
    )

    # Tim memakai hms.care.team yang sudah ada, bukan daftar praktisi baru:
    # peran DPJP/rawat-bersama/perawat primer sudah punya satu tempat, dan
    # menduplikasinya di sini akan membuat dua kebenaran tentang siapa yang
    # merawat pasien yang sama.
    team_ids = fields.Many2many(
        "hms.care.team", "hms_procedure_schedule_team_rel", "schedule_id", "team_id",
        string="Tim Tindakan",
        domain="[('encounter_id', '=', encounter_id)]",
    )

    state = fields.Selection(
        PROCEDURE_STATES, default="planned", required=True, index=True, tracking=False,
    )
    postpone_reason = fields.Selection(POSTPONE_REASONS, "Alasan Penundaan")
    postpone_note = fields.Char("Keterangan Penundaan")
    postponed_at = fields.Datetime("Ditunda Pada", readonly=True)
    postponed_by_id = fields.Many2one("res.users", "Ditunda Oleh", readonly=True)
    postpone_count = fields.Integer(
        "Jumlah Penundaan", readonly=True, default=0,
        help="Berapa kali jadwal ini pernah ditunda. Satu pasien yang ditunda "
             "tiga kali adalah tiga kejadian, bukan satu.",
    )
    original_planned_start = fields.Datetime(
        "Rencana Semula", readonly=True,
        help="Jadwal pertama sebelum penundaan mana pun. Tanpa ini, lama "
             "penundaan tidak bisa dihitung setelah jadwal diubah.",
    )
    cancel_reason = fields.Char("Alasan Pembatalan")
    note = fields.Text("Catatan")

    @api.depends("order_line_id.name")
    def _compute_name(self):
        for rec in self:
            if not rec.name or rec.order_line_id:
                rec.name = rec.order_line_id.name

    @api.depends("order_line_id.unit_id")
    def _compute_unit_id(self):
        for rec in self:
            rec.unit_id = rec.order_line_id.unit_id

    @api.depends("actual_start", "actual_end")
    def _compute_duration_minutes(self):
        for rec in self:
            if rec.actual_start and rec.actual_end:
                rec.duration_minutes = max(
                    0, int((rec.actual_end - rec.actual_start).total_seconds() // 60)
                )
            else:
                rec.duration_minutes = 0

    @api.constrains("state", "postpone_reason")
    def _check_postpone_reason(self):
        """Penundaan tanpa alasan ditolak, dari jalur mana pun.

        Diletakkan di constrains dan bukan hanya di ``action_postpone``
        karena ``write({'state': 'postponed'})`` adalah jalur yang paling
        mungkin dipakai impor data dan API.
        """
        for rec in self:
            if rec.state == "postponed" and not rec.postpone_reason:
                raise ValidationError(
                    _("Penundaan tindakan '%s' harus menyebutkan alasannya. "
                      "Penundaan tanpa alasan tidak dapat dihitung sebagai "
                      "indikator mutu.") % (rec.name or rec.order_line_id.name or "")
                )

    @api.constrains("order_line_id")
    def _check_order_type(self):
        for rec in self:
            if rec.order_line_id.order_type != "procedure":
                raise ValidationError(
                    _("Jadwal tindakan hanya dapat dibuat untuk baris order bertipe Tindakan.")
                )

    @api.constrains("planned_start", "planned_end")
    def _check_planned_window(self):
        for rec in self:
            if rec.planned_start and rec.planned_end and rec.planned_end <= rec.planned_start:
                raise ValidationError(_("Rencana selesai harus setelah rencana mulai."))

    @api.constrains("team_ids", "encounter_id")
    def _check_team_encounter(self):
        for rec in self:
            stray = rec.team_ids.filtered(lambda t: t.encounter_id != rec.encounter_id)
            if stray:
                raise ValidationError(
                    _("Anggota tim harus berasal dari tim perawatan kunjungan yang sama.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("original_planned_start", vals.get("planned_start"))
        return super().create(vals_list)

    # --- state machine ----------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if rec.state not in ("planned", "postponed"):
                raise UserError(
                    _("Tindakan '%s' tidak dapat dikonfirmasi dari status ini.") % rec.name
                )
            if not rec.planned_start:
                raise UserError(
                    _("Tindakan '%s' belum punya rencana waktu mulai.") % rec.name
                )
            rec.write({"state": "confirmed"})
        return True

    def action_start(self):
        for rec in self:
            if rec.state not in ("planned", "confirmed"):
                raise UserError(
                    _("Tindakan '%s' tidak dapat dimulai dari status ini.") % rec.name
                )
            rec.write({"state": "in_progress", "actual_start": fields.Datetime.now()})
            if rec.order_line_id.state == "ordered":
                rec.order_line_id.action_start()
        return True

    def action_done(self):
        for rec in self:
            if rec.state != "in_progress":
                raise UserError(_("Tindakan '%s' belum berlangsung.") % rec.name)
            rec.write({"state": "done", "actual_end": fields.Datetime.now()})
            if rec.order_line_id.state in ("ordered", "in_progress"):
                rec.order_line_id.action_done()
        return True

    def action_postpone(self, reason=None, note=None, new_start=None):
        """Tunda tindakan, dengan alasan, dan cacah kejadiannya."""
        for rec in self:
            if rec.state in ("done", "cancelled"):
                raise UserError(
                    _("Tindakan '%s' sudah selesai atau dibatalkan.") % rec.name
                )
            reason_value = reason or rec.postpone_reason
            if not reason_value:
                raise UserError(
                    _("Alasan penundaan wajib diisi untuk tindakan '%s'.") % rec.name
                )
            vals = {
                "state": "postponed",
                "postpone_reason": reason_value,
                "postponed_at": fields.Datetime.now(),
                "postponed_by_id": self.env.uid,
                "postpone_count": rec.postpone_count + 1,
                "original_planned_start": rec.original_planned_start or rec.planned_start,
            }
            if note:
                vals["postpone_note"] = note
            if new_start:
                vals["planned_start"] = new_start
                vals["planned_end"] = False
            rec.write(vals)
            rec.env["hms.event"].emit("procedure.postponed", {
                "schedule_id": rec.id,
                "encounter_id": rec.encounter_id.id,
                "patient_id": rec.patient_id.id,
                "reason": reason_value,
                "elective": rec.is_elective,
                "count": rec.postpone_count,
            })
        return True

    def action_cancel(self, reason=None):
        for rec in self:
            if rec.state == "done":
                raise UserError(
                    _("Tindakan '%s' sudah selesai dan tidak dapat dibatalkan.") % rec.name
                )
            rec.write({"state": "cancelled", "cancel_reason": reason or rec.cancel_reason})
        return True


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    procedure_schedule_ids = fields.One2many(
        "hms.procedure.schedule", "order_line_id", "Jadwal Tindakan",
    )

    def action_order(self):
        """Baris tindakan yang MEMANG dijadwalkan mendapat record jadwalnya.

        Sengaja hanya bila ``scheduled_at`` terisi. Tindakan kecil yang
        dikerjakan saat itu juga di poli (jahit luka, ekstraksi kuku) tidak
        pernah melewati meja penjadwalan; membuatkan record jadwal untuk
        semuanya akan mengisi papan operasi dengan baris yang tidak pernah
        dilihat siapa pun, dan membuat angka penundaan kehilangan artinya.
        Yang dijadwalkan dokter — itulah yang bisa tertunda.
        """
        res = super().action_order()
        schedulable = self.filtered(
            lambda l: l.order_type == "procedure" and l.scheduled_at
            and not l.procedure_schedule_ids
        )
        if not schedulable:
            return res
        Schedule = self.env["hms.procedure.schedule"]
        settings = self.env["hms.settings"].get_settings()
        for line in schedulable:
            minutes = (line.tariff_id.duration_minutes
                       or settings.procedure_default_minutes or 0)
            Schedule.create({
                "order_line_id": line.id,
                "planned_start": line.scheduled_at,
                "planned_end": (fields.Datetime.add(line.scheduled_at, minutes=minutes)
                                if minutes else False),
                "practitioner_id": line.performed_by_id.id or line.order_id.practitioner_id.id,
            })
        return res
