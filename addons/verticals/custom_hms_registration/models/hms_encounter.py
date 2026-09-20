# -*- coding: utf-8 -*-
"""The encounter — one visit, from arrival to a closed bill."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

# Triage levels in the order a nurse thinks about them, most urgent first.
TRIAGE_SELECTION = [
    ("red", "Merah — Resusitasi/Gawat Darurat"),
    ("yellow", "Kuning — Darurat Tidak Gawat"),
    ("green", "Hijau — Tidak Gawat Tidak Darurat"),
    ("black", "Hitam — Meninggal/Expectant"),
]


class HmsEncounter(models.Model):
    _name = "hms.encounter"
    _description = "Kunjungan (Encounter)"
    _inherit = ["mail.thread", "mail.activity.mixin", "hms.audited"]
    _order = "arrival_at desc, id desc"
    _rec_names_search = ["name", "patient_id.mrn", "patient_id.name"]

    name = fields.Char("No. Kunjungan", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, index=True,
                                 ondelete="restrict", tracking=True)
    mrn = fields.Char(related="patient_id.mrn", store=True, string="No. RM")
    type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("emergency", "Gawat Darurat"),
         ("inpatient", "Rawat Inap"), ("mcu", "Medical Check-Up"),
         ("daycare", "One Day Care"), ("telemedicine", "Telemedisin")],
        required=True, default="outpatient", tracking=True, index=True,
    )
    state = fields.Selection(
        [("registered", "Terdaftar"), ("in_progress", "Dilayani"),
         ("admitted", "Dirawat Inap"), ("finished", "Selesai Pelayanan"),
         ("discharged", "Pulang"), ("cancelled", "Batal")],
        default="registered", required=True, tracking=True, index=True,
    )
    unit_id = fields.Many2one("hms.unit", "Unit Layanan", required=True, tracking=True, index=True)
    practitioner_id = fields.Many2one("hms.practitioner", "DPJP", tracking=True,
                                      domain="[('can_be_dpjp', '=', True)]")
    payer_id = fields.Many2one("hms.payer", "Penjamin", required=True, tracking=True)
    payer_plan_id = fields.Many2one("hms.payer.plan", "Plan Penjamin",
                                    domain="[('payer_id', '=', payer_id)]")
    class_id = fields.Many2one("hms.care.class", "Hak Kelas")

    arrival_at = fields.Datetime("Waktu Kedatangan", required=True, default=fields.Datetime.now,
                                 tracking=True, index=True)
    arrival_mode = fields.Selection(
        [("walk_in", "Datang Sendiri"), ("ambulance", "Ambulans"),
         ("referral", "Rujukan"), ("transfer", "Transfer Antar Unit")],
        default="walk_in", required=True,
    )
    visit_type = fields.Selection(
        [("new", "Kunjungan Baru"), ("followup", "Kontrol Ulang"), ("control", "Kontrol Rutin")],
        default="new", required=True,
    )
    chief_complaint = fields.Char("Keluhan Utama", tracking=True)
    referral_id = fields.Many2one("hms.referral", "Rujukan")

    # Emergency-specific
    triage_level = fields.Selection(TRIAGE_SELECTION, string="Triase", tracking=True, index=True)
    triage_at = fields.Datetime("Waktu Triase")
    triage_by_id = fields.Many2one("hms.practitioner", "Petugas Triase")
    identity_pending = fields.Boolean(
        "Identitas Belum Lengkap",
        help="Diisi otomatis untuk pasien IGD tanpa identitas. Menjadi daftar kerja "
             "petugas rekam medis, bukan penghalang pelayanan.",
    )

    # Bridging
    sep_no = fields.Char("Nomor SEP", readonly=True, copy=False, tracking=True)
    sep_state = fields.Selection(
        [("none", "Tidak Perlu"), ("pending", "Menunggu"), ("issued", "Terbit"),
         ("failed", "Gagal"), ("cancelled", "Dibatalkan")],
        default="none", readonly=True, string="Status SEP",
    )
    sep_error = fields.Char("Keterangan SEP", readonly=True)
    ihs_encounter_id = fields.Char("ID Encounter SATUSEHAT", readonly=True, copy=False)
    sitb_register_no = fields.Char(
        "No. Register SITB", copy=False,
        help="Nomor register pasien pada SITB (Sistem Informasi Tuberkulosis). "
             "Diisi manual oleh petugas program TB; belum ada bridging otomatis "
             "ke SITB, jadi nomor ini adalah satu-satunya kaitan antara kunjungan "
             "di SIMRS dan catatan pasien TB di SITB.",
    )

    closed_at = fields.Datetime("Selesai Pada", readonly=True)
    closed_by_id = fields.Many2one("res.users", "Ditutup Oleh", readonly=True)
    reopen_count = fields.Integer("Jumlah Dibuka Ulang", readonly=True, default=0)
    discharge_disposition = fields.Selection(
        [("home", "Pulang"), ("referred", "Dirujuk"), ("deceased", "Meninggal"),
         ("against_advice", "Pulang Paksa"), ("transfer", "Pindah Rawat")],
        string="Cara Keluar",
    )
    is_locked = fields.Boolean(
        "Terkunci", readonly=True,
        help="Encounter yang sudah diklaim atau diaudit tidak boleh diubah lagi.",
    )
    note = fields.Text("Catatan Pendaftaran")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor kunjungan harus unik.")
    _open_encounter_idx = models.Index(
        "(patient_id, state) WHERE state IN ('registered', 'in_progress', 'admitted')"
    )

    # --- naming -----------------------------------------------------------
    @api.depends("name", "patient_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} — {rec.patient_id.name}" if rec.patient_id else rec.name

    # --- constraints ------------------------------------------------------
    @api.constrains("type", "triage_level")
    def _check_triage_present(self):
        for rec in self:
            if rec.type == "emergency" and not rec.triage_level:
                raise ValidationError(
                    _("Kunjungan IGD wajib memiliki level triase. "
                      "Triase adalah keputusan klinis pertama dan tidak boleh dilewati.")
                )

    @api.constrains("patient_id", "state", "type")
    def _check_single_open_outpatient(self):
        """One open outpatient encounter per patient per unit per day.

        Prevents the classic double registration: a patient sent back to the
        desk for a missing document gets registered again, and the second
        encounter quietly splits the bill in two.
        """
        for rec in self:
            if rec.type not in ("outpatient", "mcu") or rec.state in ("finished", "discharged", "cancelled"):
                continue
            day_start = fields.Datetime.start_of(rec.arrival_at, "day")
            day_end = fields.Datetime.end_of(rec.arrival_at, "day")
            twin = self.search([
                ("id", "!=", rec.id),
                ("patient_id", "=", rec.patient_id.id),
                ("unit_id", "=", rec.unit_id.id),
                ("type", "=", rec.type),
                ("state", "in", ("registered", "in_progress")),
                ("arrival_at", ">=", day_start),
                ("arrival_at", "<=", day_end),
            ], limit=1)
            if twin:
                raise ValidationError(
                    _("Pasien %(p)s sudah punya kunjungan terbuka di %(u)s hari ini (%(n)s). "
                      "Lanjutkan kunjungan tersebut, jangan membuat yang baru.")
                    % {"p": rec.patient_id.name, "u": rec.unit_id.name, "n": twin.name}
                )

    # --- CRUD -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.encounter") or "/"
        encounters = super().create(vals_list)
        for enc in encounters:
            enc._after_registration()
        return encounters

    def write(self, vals):
        locked = self.filtered("is_locked")
        if locked and set(vals) - {"is_locked", "message_follower_ids", "activity_ids"}:
            raise UserError(
                _("Kunjungan %s sudah terkunci (klaim/audit) dan tidak dapat diubah.")
                % ", ".join(locked.mapped("name"))
            )
        return super().write(vals)

    def unlink(self):
        if any(e.state != "cancelled" for e in self):
            raise UserError(
                _("Kunjungan tidak dapat dihapus. Batalkan kunjungan agar jejaknya tetap ada.")
            )
        return super().unlink()

    # --- registration side effects ---------------------------------------
    def _after_registration(self):
        """Everything that must happen in the same commit as the encounter."""
        self.ensure_one()
        self._update_patient_visit_stats()
        self._hms_issue_ticket()
        self._maybe_request_sep()
        self.env["hms.event"].emit("encounter.registered", {
            "encounter_id": self.id,
            "name": self.name,
            "patient": self.patient_id.name,
            "mrn": self.patient_id.mrn,
            "unit_id": self.unit_id.id,
            "unit": self.unit_id.name,
            "type": self.type,
            "triage": self.triage_level or "",
        })

    def _update_patient_visit_stats(self):
        patient = self.patient_id.sudo()
        today = fields.Date.context_today(self)
        patient.write({
            "first_visit_date": patient.first_visit_date or today,
            "last_visit_date": today,
            "visit_count": (patient.visit_count or 0) + 1,
        })

    def _hms_issue_ticket(self):
        """Hook. custom_hms_qms issues the queue ticket; base does nothing."""
        return False

    def _maybe_request_sep(self):
        """Queue the SEP job for payers that require one.

        Deliberately a job, never an inline call: BPJS response times are
        outside our control, and a registration desk cannot wait on them.
        """
        self.ensure_one()
        if not self.payer_id.requires_sep:
            return False
        if not self.patient_id.bpjs_no:
            self.write({
                "sep_state": "failed",
                "sep_error": _("Nomor kartu JKN pasien belum diisi."),
            })
            return False
        self.write({"sep_state": "pending"})
        self.env["hms.job"].enqueue(
            "bpjs.sep.create",
            payload={"encounter_id": self.id},
            model_name=self._name, res_id=self.id, priority=5,
        )
        return True

    # --- state transitions ------------------------------------------------
    def action_start_service(self):
        for enc in self:
            if enc.state != "registered":
                raise UserError(_("Hanya kunjungan berstatus Terdaftar yang dapat dimulai."))
            enc.write({"state": "in_progress"})
            enc.env["hms.event"].emit("encounter.started", {"encounter_id": enc.id})
        return True

    def action_close(self):
        """Close clinical service. Charges freeze; the bill can now be settled."""
        for enc in self:
            if enc.state not in ("registered", "in_progress"):
                raise UserError(
                    _("Kunjungan %s tidak dalam status yang bisa ditutup.") % enc.name
                )
            blockers = enc._closing_blockers()
            if blockers:
                raise UserError(
                    _("Kunjungan %(n)s belum dapat ditutup:\n- %(b)s")
                    % {"n": enc.name, "b": "\n- ".join(blockers)}
                )
            enc.write({
                "state": "finished",
                "closed_at": fields.Datetime.now(),
                "closed_by_id": self.env.uid,
            })
            enc.env["hms.event"].emit("encounter.finished", {
                "encounter_id": enc.id, "patient_id": enc.patient_id.id,
            })
        return True

    def _closing_blockers(self):
        """Reasons this encounter cannot close yet.

        Each downstream module appends its own (open orders, undispensed
        prescriptions). Returning strings rather than raising lets the UI show
        the whole list at once instead of one problem per attempt.
        """
        self.ensure_one()
        return []

    def action_reopen(self):
        for enc in self:
            if enc.state != "finished":
                raise UserError(_("Hanya kunjungan selesai yang dapat dibuka kembali."))
            if enc.is_locked:
                raise UserError(_("Kunjungan terkunci tidak dapat dibuka kembali."))
            enc.write({
                "state": "in_progress",
                "reopen_count": enc.reopen_count + 1,
                "closed_at": False,
            })
            enc.message_post(body=_("Kunjungan dibuka kembali oleh %s.") % self.env.user.name)
        return True

    def action_cancel(self):
        for enc in self:
            if enc.state in ("admitted", "discharged"):
                raise UserError(_("Kunjungan rawat inap tidak dapat dibatalkan; gunakan pemulangan."))
            enc.write({"state": "cancelled"})
            enc.env["hms.event"].emit("encounter.cancelled", {"encounter_id": enc.id})
        return True

    # --- audit hooks ------------------------------------------------------
    def _hms_audit_patient_id(self):
        self.ensure_one()
        return self.patient_id.id

    def _hms_audit_in_care_team(self):
        self.ensure_one()
        user_practitioner = self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        return bool(user_practitioner) and user_practitioner == self.practitioner_id

    @api.model
    def _hms_merge_patient(self, source, target):
        """Re-point encounters when two patient records are merged."""
        self.sudo().search([("patient_id", "=", source.id)]).write({"patient_id": target.id})
