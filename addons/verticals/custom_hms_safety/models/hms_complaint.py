# -*- coding: utf-8 -*-
"""Komplain pasien dan keluarga.

Berbeda dari IKP, komplain BUKAN dokumen rahasia yang dilindungi PMK 11/2017:
ia adalah interaksi pelayanan yang wajib dijawab dalam tenggat, dan angkanya
menjadi salah satu dari 13 Indikator Nasional Mutu (Permenkes 30/2022):
"Kecepatan Waktu Tanggap Komplain". Karena itu model ini justru mewarisi
``hms.audited`` (komplain membawa data pasien, dan siapa membukanya harus
terlacak) dan ``mail.thread`` (percakapan tindak lanjut adalah bagian dari
penyelesaiannya).

Tenggat tanggap diambil dari ``hms.settings`` per band grading, bukan dari
konstanta di kode — lihat ``models/hms_settings.py``.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

COMPLAINT_GRADES = [
    ("green", "Hijau — Ringan"),
    ("yellow", "Kuning — Sedang"),
    ("red", "Merah — Berat"),
]


class HmsComplaint(models.Model):
    _name = "hms.complaint"
    _description = "Komplain Pasien"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "received_at desc, id desc"

    name = fields.Char("Nomor Komplain", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)

    # --- siapa yang komplain ---------------------------------------------
    patient_id = fields.Many2one("hms.patient", "Pasien", index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan Terkait")
    complainant_name = fields.Char("Nama Pelapor", required=True)
    complainant_relation = fields.Selection(
        [("patient", "Pasien Sendiri"), ("family", "Keluarga"), ("companion", "Pengantar"),
         ("other", "Lainnya")],
        string="Hubungan", default="patient", required=True,
    )
    contact = fields.Char("Kontak yang Dapat Dihubungi")

    # --- isi komplain -----------------------------------------------------
    channel = fields.Selection(
        [("verbal", "Lisan Langsung"), ("phone", "Telepon"), ("whatsapp", "WhatsApp"),
         ("email", "Surel"), ("letter", "Surat"), ("suggestion_box", "Kotak Saran"),
         ("survey", "Survei Kepuasan"), ("social_media", "Media Sosial"),
         ("regulator", "Instansi / Regulator")],
        string="Kanal", required=True, default="verbal", index=True,
    )
    category = fields.Selection(
        [("waiting_time", "Waktu Tunggu"), ("service_attitude", "Sikap Petugas"),
         ("communication", "Komunikasi / Informasi"), ("clinical", "Mutu Pelayanan Klinis"),
         ("cost", "Biaya & Administrasi"), ("facility", "Fasilitas & Kebersihan"),
         ("food", "Makanan Pasien"), ("queue", "Antrian & Pendaftaran"),
         ("other", "Lain-lain")],
        string="Kategori", required=True, default="other", index=True,
    )
    unit_id = fields.Many2one("hms.unit", "Unit yang Dikeluhkan", index=True)
    subject = fields.Char("Pokok Komplain", required=True)
    detail = fields.Text("Uraian Komplain")

    grade = fields.Selection(
        COMPLAINT_GRADES, string="Grading", required=True, default="green", index=True,
        help="Menentukan target waktu tanggap. Merah: berdampak luas atau "
             "berpotensi hukum/pemberitaan; kuning: lintas unit; hijau: dapat "
             "diselesaikan unit setempat.",
    )

    # --- tenggat ----------------------------------------------------------
    received_at = fields.Datetime("Waktu Diterima", required=True,
                                  default=fields.Datetime.now, index=True)
    target_hours = fields.Integer(
        "Target Tanggap (jam)", readonly=True, copy=False,
        help="Diambil dari parameter mutu per grading saat komplain dicatat.",
    )
    due_at = fields.Datetime("Batas Tanggap", readonly=True, copy=False, index=True)
    responded_at = fields.Datetime("Waktu Ditanggapi", readonly=True, copy=False)
    response_hours = fields.Float("Lama Tanggap (jam)", compute="_compute_response",
                                  store=True)
    is_on_time = fields.Boolean("Tanggap Tepat Waktu", compute="_compute_response",
                                store=True)

    # --- penanganan -------------------------------------------------------
    state = fields.Selection(
        [("draft", "Draf"), ("received", "Diterima"), ("in_progress", "Ditangani"),
         ("responded", "Sudah Ditanggapi"), ("closed", "Ditutup")],
        default="draft", required=True, index=True, tracking=True,
    )
    handler_id = fields.Many2one("res.users", "Penanggung Jawab", readonly=True, copy=False)
    response = fields.Text("Tanggapan kepada Pelapor")
    corrective_action = fields.Text("Tindakan Perbaikan")
    outcome = fields.Selection(
        [("resolved", "Selesai — Pelapor Menerima"),
         ("partially_resolved", "Selesai Sebagian"),
         ("escalated", "Dieskalasi ke Manajemen/Regulator"),
         ("withdrawn", "Ditarik Pelapor"),
         ("unresolved", "Tidak Terselesaikan")],
        string="Hasil Akhir",
    )
    incident_report_id = fields.Many2one(
        "hms.incident.report", "Laporan IKP Terkait", copy=False,
        help="Komplain yang ternyata memuat insiden keselamatan pasien tetap "
             "dilaporkan sebagai IKP tersendiri — dua alur yang berbeda "
             "pembacanya, bukan satu record yang dipakai dua-duanya.",
    )
    closed_at = fields.Datetime("Waktu Ditutup", readonly=True, copy=False)
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor komplain harus unik.")
    _open_complaint_idx = models.Index(
        "(state, due_at) WHERE state IN ('draft', 'received', 'in_progress')"
    )

    # --- computes ---------------------------------------------------------
    @api.depends("received_at", "responded_at", "due_at")
    def _compute_response(self):
        for rec in self:
            if rec.responded_at and rec.received_at:
                rec.response_hours = (
                    rec.responded_at - rec.received_at
                ).total_seconds() / 3600.0
                rec.is_on_time = bool(rec.due_at) and rec.responded_at <= rec.due_at
            else:
                rec.response_hours = 0.0
                rec.is_on_time = False

    # --- tenggat dari parameter -------------------------------------------
    @api.model
    def _target_hours_for(self, grade):
        settings = self.env["hms.settings"].get_settings()
        mapping = {
            "red": settings.complaint_response_red_hours,
            "yellow": settings.complaint_response_yellow_hours,
            "green": settings.complaint_response_green_hours,
        }
        hours = mapping.get(grade or "green")
        # Parameter kosong berarti belum diputuskan RS; pakai definisi
        # operasional INM daripada menerbitkan tenggat nol.
        fallback = {"red": 24, "yellow": 72, "green": 168}
        return hours if hours and hours > 0 else fallback.get(grade or "green", 168)

    def _apply_target(self):
        for rec in self:
            hours = self._target_hours_for(rec.grade)
            rec.target_hours = hours
            rec.due_at = (rec.received_at or fields.Datetime.now()) + timedelta(hours=hours)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.complaint") or "/"
        records = super().create(vals_list)
        records._apply_target()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Grading yang dikoreksi menggeser tenggat selama komplain belum
        # ditanggapi; setelah ditanggapi, tenggatnya sudah menjadi bukti KPI.
        if ("grade" in vals or "received_at" in vals):
            self.filtered(lambda c: not c.responded_at)._apply_target()
        return res

    # --- state machine ----------------------------------------------------
    def action_receive(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Komplain %s sudah tercatat.") % rec.name)
            rec.state = "received"
        return True

    def action_start(self):
        for rec in self:
            if rec.state not in ("draft", "received"):
                raise UserError(_("Komplain %s sudah dalam penanganan.") % rec.name)
            rec.write({"state": "in_progress", "handler_id": self.env.uid})
        return True

    def action_respond(self):
        for rec in self:
            if rec.state not in ("received", "in_progress"):
                raise UserError(_(
                    "Tanggapan hanya dapat dicatat pada komplain yang sudah diterima."
                ))
            if not rec.response:
                raise UserError(_(
                    "Isi tanggapan wajib ditulis — indikator mutu mengukur "
                    "tanggapan yang sampai ke pelapor, bukan status yang diubah."
                ))
            rec.write({"state": "responded", "responded_at": fields.Datetime.now()})
        return True

    def action_close(self):
        for rec in self:
            if rec.state != "responded":
                raise UserError(_(
                    "Komplain hanya dapat ditutup setelah tanggapan diberikan."
                ))
            if not rec.outcome:
                raise UserError(_("Hasil akhir wajib dipilih sebelum penutupan."))
            rec.write({"state": "closed", "closed_at": fields.Datetime.now()})
        return True
