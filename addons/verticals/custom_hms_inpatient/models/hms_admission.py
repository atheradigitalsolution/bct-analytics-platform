# -*- coding: utf-8 -*-
"""Admission: the inpatient stay from bed assignment to discharge."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsAdmission(models.Model):
    _name = "hms.admission"
    _description = "Admisi Rawat Inap"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "admitted_at desc, id desc"

    name = fields.Char("No. Admisi", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    payer_id = fields.Many2one(related="encounter_id.payer_id", store=True)

    admitted_at = fields.Datetime("Waktu Masuk", required=True, default=fields.Datetime.now,
                                  index=True, tracking=True)
    discharged_at = fields.Datetime("Waktu Keluar", readonly=True, tracking=True)
    source = fields.Selection(
        [("emergency", "Dari IGD"), ("outpatient", "Dari Poliklinik"),
         ("referral", "Rujukan Langsung"), ("ok", "Pasca Operasi"),
         ("transfer", "Pindah dari RS Lain")],
        required=True, default="emergency",
    )
    dpjp_id = fields.Many2one("hms.practitioner", "DPJP", required=True, tracking=True,
                              domain="[('can_be_dpjp', '=', True)]")
    ward_id = fields.Many2one("hms.ward", "Ruang", compute="_compute_current_bed", store=True)
    room_id = fields.Many2one("hms.room", "Kamar", compute="_compute_current_bed", store=True)
    bed_id = fields.Many2one("hms.bed", "Bed", compute="_compute_current_bed", store=True,
                             index=True)
    class_id = fields.Many2one("hms.care.class", "Kelas Saat Ini",
                               compute="_compute_current_bed", store=True)
    entitled_class_id = fields.Many2one(
        "hms.care.class", "Hak Kelas", required=True,
        help="Kelas yang menjadi hak pasien menurut penjamin. Selisih ke kelas "
             "aktual ditagihkan kepada pasien.",
    )

    assignment_ids = fields.One2many("hms.bed.assignment", "admission_id", "Riwayat Bed")
    daily_charge_ids = fields.One2many("hms.daily.charge", "admission_id", "Charge Harian")

    length_of_stay = fields.Integer("Hari Rawat", compute="_compute_los", store=True)
    state = fields.Selection(
        [("planned", "Direncanakan"), ("admitted", "Dirawat"),
         ("discharge_planned", "Rencana Pulang"), ("discharged", "Pulang"),
         ("cancelled", "Batal")],
        default="admitted", required=True, tracking=True, index=True,
    )
    discharge_disposition = fields.Selection(
        [("home", "Pulang"), ("referred", "Dirujuk"), ("deceased", "Meninggal"),
         ("against_advice", "Pulang Paksa"), ("transfer", "Pindah Rawat")],
        string="Cara Keluar",
    )
    discharge_note = fields.Text("Catatan Pemulangan")
    diet = fields.Char("Diet")
    is_isolation = fields.Boolean("Isolasi")
    note = fields.Text()

    _name_uniq = models.Constraint("unique(name)", "Nomor admisi harus unik.")
    _encounter_uniq = models.Constraint(
        "unique(encounter_id)", "Satu kunjungan hanya boleh punya satu admisi.",
    )

    @api.depends("assignment_ids.is_current", "assignment_ids.bed_id")
    def _compute_current_bed(self):
        for adm in self:
            current = adm.assignment_ids.filtered("is_current")[:1]
            adm.bed_id = current.bed_id
            adm.room_id = current.bed_id.room_id
            adm.ward_id = current.bed_id.ward_id
            adm.class_id = current.class_id

    @api.depends("admitted_at", "discharged_at", "state")
    def _compute_los(self):
        now = fields.Datetime.now()
        for adm in self:
            if not adm.admitted_at:
                adm.length_of_stay = 0
                continue
            end = adm.discharged_at or now
            # Hospital convention: a stay that starts and ends the same day is
            # still one billable day, never zero.
            adm.length_of_stay = max((end.date() - adm.admitted_at.date()).days, 1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.admission") or "/"
        return super().create(vals_list)

    # --- admission --------------------------------------------------------
    @api.model
    def admit(self, encounter, bed, dpjp, entitled_class=None, charge_class=None, source="emergency"):
        """Create an admission and put the patient in the bed, atomically."""
        if bed.state not in ("vacant", "reserved"):
            raise UserError(
                _("Bed %(code)s berstatus %(state)s dan tidak dapat dipakai.")
                % {"code": bed.code, "state": bed.state}
            )
        entitled = entitled_class or encounter.class_id or bed.class_id
        admission = self.create({
            "encounter_id": encounter.id,
            "dpjp_id": dpjp.id,
            "entitled_class_id": entitled.id,
            "source": source,
        })
        self.env["hms.bed.assignment"].create({
            "admission_id": admission.id,
            "bed_id": bed.id,
            "class_id": bed.class_id.id,
            "charge_class_id": (charge_class or entitled).id,
            "from_at": admission.admitted_at,
            "reason": "admit",
            "is_current": True,
        })
        bed.action_occupy()
        encounter.write({"state": "admitted", "type": "inpatient"})
        admission.env["hms.event"].emit("admission.created", {
            "admission_id": admission.id,
            "encounter_id": encounter.id,
            "patient": encounter.patient_id.name,
            "bed_id": bed.id,
            "ward_id": bed.ward_id.id,
        })
        return admission

    def action_transfer(self, new_bed, reason="transfer_medical", charge_class=None):
        """Move the patient, closing the current assignment cleanly."""
        self.ensure_one()
        if self.state != "admitted":
            raise UserError(_("Hanya pasien yang sedang dirawat yang dapat dipindahkan."))
        if new_bed.state not in ("vacant", "reserved"):
            raise UserError(_("Bed tujuan %s tidak kosong.") % new_bed.code)
        current = self.assignment_ids.filtered("is_current")[:1]
        if current.bed_id == new_bed:
            raise UserError(_("Pasien sudah berada di bed tersebut."))
        now = fields.Datetime.now()
        old_bed = current.bed_id
        current.write({"to_at": now, "is_current": False})
        # Flush before inserting the successor: the partial unique index on
        # (admission_id) WHERE is_current allows exactly one open assignment,
        # and the ORM would otherwise send the INSERT before the UPDATE.
        current.flush_recordset(["is_current", "to_at"])
        self.env["hms.bed.assignment"].create({
            "admission_id": self.id,
            "bed_id": new_bed.id,
            "class_id": new_bed.class_id.id,
            "charge_class_id": (charge_class or self.entitled_class_id).id,
            "from_at": now,
            "reason": reason,
            "is_current": True,
        })
        new_bed.action_occupy()
        if old_bed:
            old_bed.action_start_cleaning()
        self.env["hms.event"].emit("bed.changed", {
            "admission_id": self.id,
            "from_bed_id": old_bed.id,
            "to_bed_id": new_bed.id,
            "ward_id": new_bed.ward_id.id,
        })
        return True

    # --- discharge --------------------------------------------------------
    def discharge_check(self):
        """List everything standing between this patient and the door."""
        self.ensure_one()
        blockers = []
        open_orders = self.encounter_id.order_line_ids.filtered(
            lambda l: l.state in ("ordered", "in_progress")
        )
        if open_orders:
            blockers.append(
                _("%(n)s order belum selesai: %(items)s")
                % {"n": len(open_orders), "items": ", ".join(open_orders.mapped("name")[:5])}
            )
        unsigned = self.encounter_id.note_ids.filtered(lambda n: not n.signed)
        if unsigned:
            blockers.append(_("%s catatan klinis belum ditandatangani.") % len(unsigned))
        summary = self.encounter_id.summary_ids.filtered(
            lambda s: s.type == "discharge" and s.state == "final"
        )
        if not summary:
            blockers.append(_("Ringkasan pulang belum difinalkan DPJP."))
        blockers.extend(self._extra_discharge_blockers())
        return blockers

    def _extra_discharge_blockers(self):
        """Hook. custom_hms_billing adds the unpaid-bill check."""
        return []

    def action_plan_discharge(self):
        for adm in self:
            if adm.state != "admitted":
                raise UserError(_("Admisi tidak dalam status dirawat."))
            adm.write({"state": "discharge_planned"})
            adm.env["hms.event"].emit("discharge.planned", {"admission_id": adm.id})
        return True

    def action_discharge(self, force=False):
        for adm in self:
            if adm.state not in ("admitted", "discharge_planned"):
                raise UserError(_("Admisi %s tidak dapat dipulangkan.") % adm.name)
            blockers = adm.discharge_check()
            if blockers and not (force or self.env.context.get("hms_force_discharge")):
                raise UserError(
                    _("Pasien %(p)s belum dapat dipulangkan:\n- %(b)s")
                    % {"p": adm.patient_id.name, "b": "\n- ".join(blockers)}
                )
            now = fields.Datetime.now()
            current = adm.assignment_ids.filtered("is_current")[:1]
            bed = current.bed_id
            current.write({"to_at": now, "is_current": False, "reason": "discharge"})
            adm.write({"state": "discharged", "discharged_at": now})
            adm.encounter_id.write({
                "state": "discharged",
                "discharge_disposition": adm.discharge_disposition or "home",
                "closed_at": now,
            })
            if bed:
                # Straight to cleaning, never to vacant: a bed that looks free
                # before housekeeping has touched it will be filled by the next
                # admission within minutes.
                bed.action_start_cleaning()
            adm.env["hms.event"].emit("admission.discharged", {
                "admission_id": adm.id,
                "bed_id": bed.id,
                "ward_id": bed.ward_id.id,
                "patient": adm.patient_id.name,
            })
        return True

    def action_cancel(self):
        for adm in self:
            if adm.state == "discharged":
                raise UserError(_("Admisi yang sudah pulang tidak dapat dibatalkan."))
            current = adm.assignment_ids.filtered("is_current")[:1]
            if current.bed_id:
                current.bed_id.action_set_vacant()
            current.write({"is_current": False, "to_at": fields.Datetime.now()})
            adm.write({"state": "cancelled"})
        return True

    # --- census -----------------------------------------------------------
    @api.model
    def census(self, date=None):
        """Occupancy snapshot for a given day."""
        date = date or fields.Date.context_today(self)
        wards = self.env["hms.ward"].search([])
        rows = []
        for ward in wards:
            beds = ward.bed_ids.filtered("active")
            occupied = len(beds.filtered(lambda b: b.state == "occupied"))
            rows.append({
                "ward_id": ward.id,
                "ward": ward.name,
                "beds": len(beds),
                "occupied": occupied,
                "available": len(beds.filtered(lambda b: b.state == "vacant")),
                "bor": round(occupied / len(beds) * 100.0, 1) if beds else 0.0,
            })
        return {"date": fields.Date.to_string(date), "wards": rows}


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    admission_id = fields.One2many("hms.admission", "encounter_id", "Admisi")
