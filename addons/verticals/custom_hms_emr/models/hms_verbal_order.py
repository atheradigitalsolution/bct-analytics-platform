# -*- coding: utf-8 -*-
"""Perintah lisan / lewat telepon dengan alur TBaK (Tulis - Baca ulang - Konfirmasi).

Sasaran Keselamatan Pasien 2 (komunikasi efektif) menuntut tiga langkah yang
berurutan dan bertanda waktu, bukan satu kotak centang: penerima **menulis**
instruksi, **membacakan ulang** kepada pemberi, lalu pemberi **mengonfirmasi**
— dan tanda tangan pemberi menyusul paling lambat sesuai kebijakan RS.

Dua keputusan yang membentuk model ini:

**Lompatan dari `spoken` langsung ke `confirmed` ditutup di dua tempat.**
Bukan hanya di `action_confirm()`, tetapi juga sebagai ``@api.constrains``,
karena aksi hanya menjaga tombol sementara ``write()`` lewat API atau impor
data melewatinya begitu saja. Read-back yang bisa dilewati bukan read-back.

**Lewat tenggat TIDAK memblokir apa pun.** Perintah lisan yang belum
ditandatangani tetap bisa ditandatangani setelah lewat batas; state `expired`
adalah penanda mutu, bukan gerbang. Memblokir konfirmasi terlambat hanya akan
menghasilkan perintah yang tidak pernah ditandatangani sama sekali, dan
pasiennya sudah telanjur menerima obatnya.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsVerbalOrder(models.Model):
    _name = "hms.verbal.order"
    _description = "Perintah Lisan / Telepon (TBaK)"
    _inherit = ["hms.audited"]
    _order = "spoken_at desc, id desc"

    name = fields.Char("Nomor", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)

    prescriber_id = fields.Many2one(
        "hms.practitioner", "Pemberi Perintah", required=True, index=True,
        help="Dokter yang memberikan instruksi secara lisan atau lewat telepon.",
    )
    receiver_id = fields.Many2one(
        "hms.practitioner", "Penerima Perintah", required=True,
        help="Perawat atau tenaga kesehatan yang menerima dan menuliskan instruksi.",
    )
    medium = fields.Selection(
        [("verbal", "Lisan Langsung"), ("phone", "Telepon"), ("radio", "Radio Medik")],
        string="Media", default="phone", required=True,
    )
    content = fields.Text("Isi Instruksi", required=True)
    lasa_spelled = fields.Boolean(
        "Nama Obat LASA Dieja",
        help="Obat rupa/ucapan mirip (LASA) wajib dieja huruf per huruf saat "
             "dibacakan ulang.",
    )

    spoken_at = fields.Datetime("Waktu Instruksi", required=True,
                                default=fields.Datetime.now, index=True)
    read_back_at = fields.Datetime("Waktu Baca Ulang", readonly=True, copy=False)
    read_back_by_id = fields.Many2one("hms.practitioner", "Dibacakan Ulang Oleh",
                                      readonly=True, copy=False)
    confirm_due_at = fields.Datetime(
        "Batas Konfirmasi", readonly=True, copy=False, index=True,
        help="Waktu instruksi + hms.settings.verbal_order_confirm_hours.",
    )
    confirm_hours_applied = fields.Integer("Tenggat Terpakai (jam)", readonly=True, copy=False)
    confirmed_at = fields.Datetime("Waktu Konfirmasi", readonly=True, copy=False)
    confirmed_by_id = fields.Many2one("hms.practitioner", "Dikonfirmasi Oleh",
                                      readonly=True, copy=False)

    state = fields.Selection(
        [("spoken", "Diucapkan"), ("read_back", "Sudah Dibaca Ulang"),
         ("confirmed", "Dikonfirmasi"), ("expired", "Lewat Batas Tanda Tangan"),
         ("cancelled", "Dibatalkan")],
        default="spoken", required=True, index=True,
    )
    # TIDAK ADA `order_id` DI SINI — dan itu bukan kelalaian.
    #
    # `hms.order` milik `custom_hms_order`, yang DEPENDS pada modul ini.
    # Sebuah Many2one ke sana dari sini membalik arah grafik dependensi dan
    # membuat registry gagal dimuat sama sekali ("unknown comodel_name
    # 'hms.order'"), bukan gagal diam-diam. Kaitan ke order nyata karena itu
    # harus ditulis dari sisi `hms.order` oleh modul yang memilikinya —
    # gelombang yang menyentuh custom_hms_order, bukan gelombang ini.
    # Alternatif yang sengaja ditolak: `Many2oneReference` tanpa comodel, yang
    # menyimpan id tanpa integritas referensial dan membuat order terhapus
    # meninggalkan angka yatim pada catatan perintah lisan.
    is_overdue = fields.Boolean("Lewat Batas", compute="_compute_is_overdue")
    cancel_reason = fields.Char("Alasan Pembatalan")

    _name_uniq = models.Constraint("unique(name)", "Nomor perintah lisan harus unik.")
    _pending_idx = models.Index(
        "(confirm_due_at) WHERE state IN ('spoken', 'read_back')"
    )

    # --- computes ---------------------------------------------------------
    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for rec in self:
            rec.is_overdue = bool(
                rec.confirm_due_at
                and rec.state in ("spoken", "read_back", "expired")
                and now > rec.confirm_due_at
            )

    # --- constraints ------------------------------------------------------
    @api.constrains("state", "read_back_at", "confirmed_at")
    def _check_read_back_precedes_confirmation(self):
        """TBaK tanpa 'Ba' bukan TBaK.

        Dijaga di lapisan data, bukan hanya di aksi: impor data dan panggilan
        API menulis langsung ke ``state``.
        """
        for rec in self:
            if rec.state == "confirmed" and not rec.read_back_at:
                raise ValidationError(_(
                    "Perintah lisan %s tidak dapat dikonfirmasi sebelum dibacakan "
                    "ulang (read-back). Alur TBaK wajib berurutan: tulis, baca "
                    "ulang, konfirmasi."
                ) % (rec.name or ""))
            if rec.confirmed_at and not rec.read_back_at:
                raise ValidationError(_(
                    "Waktu konfirmasi tercatat tanpa waktu baca ulang pada %s."
                ) % (rec.name or ""))

    @api.constrains("spoken_at", "read_back_at", "confirmed_at")
    def _check_chronology(self):
        for rec in self:
            if rec.read_back_at and rec.spoken_at and rec.read_back_at < rec.spoken_at:
                raise ValidationError(_("Baca ulang tidak boleh mendahului instruksi."))
            if rec.confirmed_at and rec.read_back_at and rec.confirmed_at < rec.read_back_at:
                raise ValidationError(_("Konfirmasi tidak boleh mendahului baca ulang."))

    @api.constrains("prescriber_id", "receiver_id")
    def _check_two_different_people(self):
        for rec in self:
            if rec.prescriber_id and rec.prescriber_id == rec.receiver_id:
                raise ValidationError(_(
                    "Pemberi dan penerima perintah lisan harus dua orang berbeda."
                ))

    # --- create -----------------------------------------------------------
    def _confirm_due_hours(self):
        hours = self.env["hms.settings"].get_settings().verbal_order_confirm_hours
        # Nol berarti parameter belum diisi; jatuh ke norma STARKES 1x24 jam.
        return hours if hours and hours > 0 else 24

    @api.model_create_multi
    def create(self, vals_list):
        hours = self._confirm_due_hours()
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.verbal.order") or "/"
            vals.setdefault("confirm_hours_applied", hours)
            if not vals.get("confirm_due_at"):
                spoken = fields.Datetime.to_datetime(
                    vals.get("spoken_at") or fields.Datetime.now()
                )
                vals["confirm_due_at"] = spoken + timedelta(
                    hours=vals["confirm_hours_applied"]
                )
        return super().create(vals_list)

    # --- alur TBaK --------------------------------------------------------
    def _current_practitioner(self):
        practitioner = self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        return practitioner

    def action_read_back(self):
        for rec in self:
            if rec.state != "spoken":
                raise UserError(_(
                    "Hanya perintah berstatus Diucapkan yang dapat dibacakan ulang."
                ))
            rec.write({
                "state": "read_back",
                "read_back_at": fields.Datetime.now(),
                "read_back_by_id": (rec._current_practitioner() or rec.receiver_id).id,
            })
        return True

    def action_confirm(self):
        """Tanda tangan pemberi perintah.

        Diizinkan juga dari ``expired``: perintah yang terlambat ditandatangani
        tetap harus bisa ditandatangani — yang diukur adalah keterlambatannya,
        bukan ketiadaan tanda tangannya.
        """
        for rec in self:
            if rec.state not in ("read_back", "expired"):
                raise UserError(_(
                    "Perintah lisan %s belum dibacakan ulang. Alur TBaK tidak "
                    "boleh dilompati: tulis, baca ulang, baru konfirmasi."
                ) % rec.name)
            if not rec.read_back_at:
                raise UserError(_(
                    "Perintah lisan %s tidak memiliki catatan baca ulang."
                ) % rec.name)
            rec.write({
                "state": "confirmed",
                "confirmed_at": fields.Datetime.now(),
                "confirmed_by_id": (
                    rec._current_practitioner() or rec.prescriber_id
                ).id,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "confirmed":
                raise UserError(_(
                    "Perintah lisan yang sudah dikonfirmasi tidak dibatalkan; "
                    "buat instruksi baru yang menghentikannya."
                ))
            if not rec.cancel_reason:
                raise UserError(_("Alasan pembatalan wajib diisi."))
            rec.state = "cancelled"
        return True

    @api.model
    def _cron_flag_expired(self):
        """Tandai perintah yang lewat batas tanda tangan.

        Hanya menandai. Tidak ada yang dihentikan, tidak ada order yang
        dibatalkan: daftar inilah yang dipakai komite medik menagih tanda
        tangan, dan daftar yang menghapus dirinya sendiri tidak menagih siapa pun.
        """
        pending = self.search([
            ("state", "in", ["spoken", "read_back"]),
            ("confirm_due_at", "<", fields.Datetime.now()),
        ])
        pending.write({"state": "expired"})
        return len(pending)
