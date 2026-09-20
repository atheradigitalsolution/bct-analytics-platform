# -*- coding: utf-8 -*-
"""Wards, rooms and beds.

The bed is the scarcest resource in a hospital, so its state machine is the one
place where an optimistic write costs a real patient a place to sleep. Every
transition goes through `action_*`; nothing outside this file writes `state`
directly.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsWard(models.Model):
    _name = "hms.ward"
    _description = "Ruang Rawat (Instalasi)"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    type = fields.Selection(
        [("general", "Umum"), ("pediatric", "Anak"), ("maternity", "Kebidanan"),
         ("icu", "ICU"), ("nicu", "NICU"), ("picu", "PICU"), ("hcu", "HCU"),
         ("isolation", "Isolasi"), ("vk", "Kamar Bersalin"),
         ("ok_recovery", "Pemulihan OK"), ("er_observation", "Observasi IGD")],
        required=True, default="general",
    )
    unit_id = fields.Many2one("hms.unit", "Unit Layanan", required=True)
    floor = fields.Char("Lantai")
    building = fields.Char("Gedung")
    head_nurse_id = fields.Many2one("hms.practitioner", "Kepala Ruang")
    phone_ext = fields.Char("Ekstensi")
    gender_policy = fields.Selection(
        [("mixed", "Campur"), ("male", "Laki-laki"), ("female", "Perempuan"),
         ("by_room", "Per kamar")],
        default="by_room", required=True,
    )
    room_ids = fields.One2many("hms.room", "ward_id", "Kamar")
    bed_ids = fields.One2many("hms.bed", "ward_id", "Tempat Tidur")
    bed_count = fields.Integer("Jumlah Bed", compute="_compute_bed_stats")
    occupied_count = fields.Integer("Terisi", compute="_compute_bed_stats")
    available_count = fields.Integer("Kosong", compute="_compute_bed_stats")
    occupancy_rate = fields.Float("BOR (%)", compute="_compute_bed_stats")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode ruang rawat harus unik.",
    )

    @api.depends("bed_ids.state", "bed_ids.active")
    def _compute_bed_stats(self):
        for ward in self:
            beds = ward.bed_ids.filtered("active")
            ward.bed_count = len(beds)
            ward.occupied_count = len(beds.filtered(lambda b: b.state == "occupied"))
            ward.available_count = len(beds.filtered(lambda b: b.state == "vacant"))
            ward.occupancy_rate = (ward.occupied_count / ward.bed_count * 100.0) if ward.bed_count else 0.0


class HmsRoom(models.Model):
    _name = "hms.room"
    _description = "Kamar"
    _order = "ward_id, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    ward_id = fields.Many2one("hms.ward", "Ruang Rawat", required=True, ondelete="restrict")
    class_id = fields.Many2one("hms.care.class", "Kelas Perawatan", required=True)
    capacity = fields.Integer("Kapasitas", default=1)
    gender = fields.Selection(
        [("mixed", "Campur"), ("male", "Laki-laki"), ("female", "Perempuan"), ("none", "Belum ditetapkan")],
        default="none", required=True,
    )
    is_isolation = fields.Boolean("Kamar isolasi")
    isolation_type = fields.Selection(
        [("negative_pressure", "Tekanan negatif"), ("positive_pressure", "Tekanan positif"),
         ("standard", "Standar")],
    )
    facility_ids = fields.Many2many("hms.room.facility", string="Fasilitas")
    room_tariff_id = fields.Many2one(
        "hms.tariff", "Tarif Kamar (override)",
        help="Kosongkan agar memakai tarif kamar dari kelas perawatan.",
    )
    phone_ext = fields.Char("Ekstensi")
    is_kris_compliant = fields.Boolean(
        "Memenuhi KRIS",
        help="Kamar sudah memenuhi 12 kriteria Kelas Rawat Inap Standar "
             "(ventilasi, pencahayaan, kepadatan tempat tidur, nakas, suhu, "
             "tirai, kamar mandi dalam, dan seterusnya). Ditetapkan manual oleh "
             "tim sarana; tidak diturunkan dari fasilitas kamar.",
    )
    bed_ids = fields.One2many("hms.bed", "room_id", "Tempat Tidur")
    state = fields.Selection(
        [("active", "Aktif"), ("maintenance", "Pemeliharaan"), ("closed", "Ditutup")],
        default="active", required=True,
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode kamar harus unik.",
    )

    @api.constrains("gender", "class_id")
    def _check_class_iii_gender(self):
        """Kelas III wards are shared; a mixed-gender shared room is not allowed."""
        for room in self:
            if room.capacity > 1 and room.gender == "mixed" and room.class_id.code == "III":
                raise UserError(_("Kamar kelas III berisi lebih dari satu bed tidak boleh campur jenis kelamin."))


class HmsRoomFacility(models.Model):
    _name = "hms.room.facility"
    _description = "Fasilitas Kamar"

    name = fields.Char(required=True)
    code = fields.Char()


class HmsBed(models.Model):
    _name = "hms.bed"
    _description = "Tempat Tidur"
    _inherit = ["mail.thread"]
    _order = "room_id, code"

    code = fields.Char(required=True, tracking=True)
    name = fields.Char(required=True)
    room_id = fields.Many2one("hms.room", "Kamar", required=True, ondelete="restrict")
    ward_id = fields.Many2one("hms.ward", related="room_id.ward_id", store=True, readonly=True)
    class_id = fields.Many2one(
        "hms.care.class", "Kelas", compute="_compute_class_id", store=True, readonly=False,
        help="Diturunkan dari kamar; boleh di-override untuk bed yang ditarifkan berbeda.",
    )
    bed_type = fields.Selection(
        [("standard", "Standar"), ("electric", "Elektrik"), ("icu", "ICU"),
         ("pediatric_crib", "Boks Anak"), ("incubator", "Inkubator"),
         ("bariatric", "Bariatrik"), ("transport", "Transport")],
        default="standard", required=True,
    )
    state = fields.Selection(
        [("vacant", "Kosong"), ("reserved", "Dipesan"), ("occupied", "Terisi"),
         ("cleaning", "Dibersihkan"), ("maintenance", "Pemeliharaan"), ("blocked", "Diblokir")],
        default="vacant", required=True, tracking=True, index=True,
    )
    reserved_until = fields.Datetime("Dipesan Sampai")
    cleaning_started_at = fields.Datetime("Mulai Dibersihkan")
    cleaned_by_id = fields.Many2one("res.users", "Dibersihkan Oleh")
    last_occupied_at = fields.Datetime("Terakhir Terisi")
    has_oxygen = fields.Boolean("Oksigen sentral")
    has_suction = fields.Boolean("Suction")
    has_monitor = fields.Boolean("Monitor")
    has_ventilator_port = fields.Boolean("Port ventilator")
    aplicares_code = fields.Char("Kode Aplicares BPJS")
    note = fields.Char("Catatan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode bed harus unik.",
    )

    @api.depends("room_id.class_id")
    def _compute_class_id(self):
        for bed in self:
            if not bed.class_id or bed.room_id.class_id:
                bed.class_id = bed.room_id.class_id

    def _set_state(self, new_state, **vals):
        """The only writer of `state`. Keeps the audit trail in one place."""
        self.ensure_one()
        vals["state"] = new_state
        self.write(vals)
        # custom_hms_queue installs the outbox. hms_base must stay installable
        # without it, so the emit is conditional rather than a hard depend.
        if "hms.event" in self.env:
            self.env["hms.event"].sudo().emit("bed.changed", {
                "bed_id": self.id,
                "code": self.code,
                "ward_id": self.ward_id.id,
                "state": new_state,
            })
        return True

    def action_reserve(self, until=None):
        for bed in self:
            if bed.state != "vacant":
                raise UserError(_("Bed %s tidak kosong, tidak dapat dipesan.") % bed.code)
            bed._set_state("reserved", reserved_until=until)
        return True

    def action_occupy(self):
        for bed in self:
            if bed.state not in ("vacant", "reserved"):
                raise UserError(
                    _("Bed %(code)s berstatus %(state)s; hanya bed kosong atau dipesan yang dapat diisi.")
                    % {"code": bed.code, "state": dict(bed._fields["state"].selection).get(bed.state)}
                )
            bed._set_state("occupied", last_occupied_at=fields.Datetime.now(), reserved_until=False)
        return True

    def action_start_cleaning(self):
        for bed in self:
            bed._set_state("cleaning", cleaning_started_at=fields.Datetime.now())
        return True

    def action_set_vacant(self):
        for bed in self:
            bed._set_state(
                "vacant", cleaning_started_at=False, reserved_until=False,
                cleaned_by_id=self.env.user.id if bed.state == "cleaning" else bed.cleaned_by_id.id,
            )
        return True

    def action_set_maintenance(self):
        for bed in self:
            if bed.state == "occupied":
                raise UserError(_("Bed %s sedang terisi pasien.") % bed.code)
            bed._set_state("maintenance")
        return True
