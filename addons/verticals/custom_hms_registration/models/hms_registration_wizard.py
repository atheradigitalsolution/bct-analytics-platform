# -*- coding: utf-8 -*-
"""One-screen registration: find or create the patient, open the encounter."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsRegistrationWizard(models.TransientModel):
    _name = "hms.registration.wizard"
    _description = "Registrasi Pasien"

    mode = fields.Selection(
        [("existing", "Pasien Lama"), ("new", "Pasien Baru")],
        default="existing", required=True,
    )
    encounter_type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("emergency", "Gawat Darurat"), ("mcu", "Medical Check-Up")],
        default="outpatient", required=True, string="Jenis Kunjungan",
    )

    # Existing patient
    patient_id = fields.Many2one("hms.patient", "Pasien")

    # New patient — the minimum a desk can collect without stalling the queue
    new_name = fields.Char("Nama Lengkap")
    new_nik = fields.Char("NIK")
    new_birth_date = fields.Date("Tanggal Lahir")
    new_gender = fields.Selection([("male", "Laki-laki"), ("female", "Perempuan")], "Jenis Kelamin")
    new_phone = fields.Char("Telepon/WA")
    new_address = fields.Char("Alamat")
    new_bpjs_no = fields.Char("No. Kartu JKN")
    new_is_anonymous = fields.Boolean("Identitas Belum Diketahui")

    # Visit
    unit_id = fields.Many2one("hms.unit", "Poli/Unit", required=True)
    practitioner_id = fields.Many2one(
        "hms.practitioner", "Dokter", domain="[('unit_ids', 'in', unit_id)]",
    )
    payer_id = fields.Many2one(
        "hms.payer", "Penjamin", required=True,
        default=lambda s: s.env.ref("custom_hms_base.payer_self", raise_if_not_found=False),
    )
    payer_plan_id = fields.Many2one("hms.payer.plan", "Plan", domain="[('payer_id', '=', payer_id)]")
    visit_type = fields.Selection(
        [("new", "Kunjungan Baru"), ("followup", "Kontrol Ulang")], default="new", required=True,
    )
    arrival_mode = fields.Selection(
        [("walk_in", "Datang Sendiri"), ("ambulance", "Ambulans"),
         ("referral", "Rujukan"), ("transfer", "Transfer Antar Unit")],
        default="walk_in", required=True, string="Cara Datang",
    )
    chief_complaint = fields.Char("Keluhan Utama")
    triage_level = fields.Selection(
        [("red", "Merah"), ("yellow", "Kuning"), ("green", "Hijau"), ("black", "Hitam")],
        string="Triase",
    )
    referral_no = fields.Char("Nomor Rujukan")
    referral_source = fields.Char("Asal Perujuk")

    @api.onchange("patient_id")
    def _onchange_patient(self):
        if self.patient_id:
            self.payer_id = self.patient_id.default_payer_id or self.payer_id
            if self.patient_id.visit_count:
                self.visit_type = "followup"

    @api.onchange("encounter_type")
    def _onchange_encounter_type(self):
        if self.encounter_type == "emergency":
            self.arrival_mode = "ambulance" if self.arrival_mode == "walk_in" else self.arrival_mode
            emergency = self.env["hms.unit"].search([("type", "=", "emergency")], limit=1)
            if emergency:
                self.unit_id = emergency

    def _prepare_patient(self):
        """Create the patient record for a walk-in stranger."""
        self.ensure_one()
        if not self.new_name and not self.new_is_anonymous:
            raise UserError(_("Nama pasien wajib diisi."))
        if not self.new_birth_date and not self.new_is_anonymous:
            raise UserError(_("Tanggal lahir wajib diisi."))
        vals = {
            "name": self.new_name or _("Tn/Ny X"),
            "nik": self.new_nik or False,
            "birth_date": self.new_birth_date or fields.Date.context_today(self),
            "gender": self.new_gender or "male",
            "phone": self.new_phone,
            "address_street": self.new_address,
            "bpjs_no": self.new_bpjs_no,
            "is_anonymous": self.new_is_anonymous,
            "identity_type": "none" if self.new_is_anonymous else "ktp",
            "default_payer_id": self.payer_id.id,
        }
        return self.env["hms.patient"].create(vals)

    def action_register(self):
        """Register in a single transaction and open the resulting encounter."""
        self.ensure_one()
        if self.encounter_type == "emergency" and not self.triage_level:
            raise UserError(_("Triase wajib diisi untuk pendaftaran IGD."))
        patient = self.patient_id if self.mode == "existing" else self._prepare_patient()
        if not patient:
            raise UserError(_("Pilih pasien lama atau isi data pasien baru."))

        referral = False
        if self.referral_no:
            referral = self.env["hms.referral"].create({
                "name": self.referral_no,
                "patient_id": patient.id,
                "source_name": self.referral_source or _("Tidak disebutkan"),
                "to_unit_id": self.unit_id.id,
                "to_practitioner_id": self.practitioner_id.id,
            })

        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id,
            "type": self.encounter_type,
            "unit_id": self.unit_id.id,
            "practitioner_id": self.practitioner_id.id,
            "payer_id": self.payer_id.id,
            "payer_plan_id": self.payer_plan_id.id,
            "class_id": self.payer_plan_id.class_id.id,
            "visit_type": self.visit_type,
            "arrival_mode": "referral" if referral else self.arrival_mode,
            "chief_complaint": self.chief_complaint,
            "triage_level": self.triage_level,
            "triage_at": fields.Datetime.now() if self.triage_level else False,
            "referral_id": referral.id if referral else False,
            "identity_pending": patient.is_anonymous or not patient.nik,
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "hms.encounter",
            "res_id": encounter.id,
            "view_mode": "form",
            "target": "current",
        }
