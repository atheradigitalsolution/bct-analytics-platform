# -*- coding: utf-8 -*-
"""Nightly charges: room, doctor visit, nursing care."""
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class HmsDailyChargeRule(models.Model):
    _name = "hms.daily.charge.rule"
    _description = "Aturan Charge Harian"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    charge_type = fields.Selection(
        [("room", "Akomodasi Kamar"), ("visit", "Visite DPJP"),
         ("nursing", "Asuhan Keperawatan"), ("other", "Lainnya")],
        required=True, default="room",
    )
    tariff_id = fields.Many2one(
        "hms.tariff", "Item Tarif",
        help="Kosongkan untuk akomodasi kamar: tarifnya diambil dari kelas yang "
             "ditagihkan pada hari bersangkutan.",
    )
    class_id = fields.Many2one("hms.care.class", "Khusus Kelas",
                               help="Kosong berarti berlaku untuk semua kelas.")
    ward_type = fields.Selection(
        [("general", "Umum"), ("pediatric", "Anak"), ("maternity", "Kebidanan"),
         ("icu", "ICU"), ("isolation", "Isolasi")],
        string="Khusus Tipe Ruang",
    )
    requires_doctor_note = fields.Boolean(
        "Hanya bila ada CPPT dokter",
        help="Visite hanya ditagih bila dokter benar-benar menulis catatan hari itu.",
    )
    active = fields.Boolean(default=True)


class HmsDailyCharge(models.Model):
    _name = "hms.daily.charge"
    _description = "Charge Harian Rawat Inap"
    _order = "charge_date desc, id desc"

    admission_id = fields.Many2one("hms.admission", required=True, ondelete="cascade", index=True)
    encounter_id = fields.Many2one(related="admission_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="admission_id.patient_id", store=True, index=True)
    charge_date = fields.Date("Tanggal", required=True, index=True)
    charge_type = fields.Selection(
        [("room", "Akomodasi Kamar"), ("visit", "Visite DPJP"),
         ("nursing", "Asuhan Keperawatan"), ("other", "Lainnya")],
        required=True, index=True,
    )
    rule_id = fields.Many2one("hms.daily.charge.rule", "Aturan")
    tariff_id = fields.Many2one("hms.tariff", "Item Tarif", required=True)
    class_id = fields.Many2one("hms.care.class", "Kelas Ditagihkan")
    practitioner_id = fields.Many2one("hms.practitioner", "Praktisi")
    qty = fields.Float(default=1.0)
    note = fields.Char()

    # The guard that makes the cron safe to run twice.
    _daily_uniq = models.Constraint(
        "unique(admission_id, charge_date, charge_type, tariff_id)",
        "Charge harian untuk kombinasi ini sudah pernah dibuat.",
    )

    def _post_charge(self):
        """Hook. custom_hms_billing turns the row into a bill line."""
        return False

    @api.model
    def _cron_generate(self, for_date=None):
        """Charge the day that has just begun, for everyone still in a bed.

        Runs at 00:05. Indonesian hospitals bill accommodation by midnight
        occupancy, so a patient present when the date rolls over owes that
        day — which is also why a discharge at 09:00 still carries a room
        charge.

        Re-running is harmless: the unique constraint refuses duplicates, so an
        operator retrying after a failure does not double-bill a whole ward.
        """
        target = for_date or fields.Date.context_today(self)
        admissions = self.env["hms.admission"].search([("state", "in", ("admitted", "discharge_planned"))])
        created = 0
        for admission in admissions:
            created += len(admission._generate_daily_charges(target))
        _logger.info("SIMRS charge harian %s: %s baris dibuat", target, created)
        self.env["ir.config_parameter"].sudo().set_param(
            "hms.daily_charge.last_run", fields.Datetime.to_string(fields.Datetime.now())
        )
        return created


class HmsAdmission(models.Model):
    _inherit = "hms.admission"

    def _generate_daily_charges(self, date):
        """Create the day's charges for this admission."""
        self.ensure_one()
        Charge = self.env["hms.daily.charge"]
        rules = self.env["hms.daily.charge.rule"].search([])
        assignment = self.assignment_ids.filtered(lambda a: a.class_on(date))[:1]
        if not assignment:
            return Charge
        created = Charge
        for rule in rules:
            if rule.class_id and rule.class_id != assignment.charge_class_id:
                continue
            if rule.ward_type and rule.ward_type != assignment.ward_id.type:
                continue
            tariff = rule.tariff_id or self._room_tariff(assignment)
            if not tariff:
                continue
            practitioner = False
            if rule.charge_type == "visit":
                practitioner = self._visiting_doctor(date)
                if rule.requires_doctor_note and not practitioner:
                    continue
                practitioner = practitioner or self.dpjp_id
            vals = {
                "admission_id": self.id,
                "charge_date": date,
                "charge_type": rule.charge_type,
                "rule_id": rule.id,
                "tariff_id": tariff.id,
                "class_id": assignment.charge_class_id.id,
                "practitioner_id": practitioner.id if practitioner else False,
            }
            try:
                with self.env.cr.savepoint():
                    charge = Charge.create(vals)
                    charge._post_charge()
                    created |= charge
            except Exception:  # noqa: BLE001 — duplicate is the expected case
                # Already charged for this day; the unique constraint did its
                # job and the savepoint keeps the rest of the ward going.
                continue
        return created

    def _room_tariff(self, assignment):
        """Room tariff for the class actually being billed."""
        self.ensure_one()
        room_category = self.env.ref("custom_hms_base.tariff_cat_room", raise_if_not_found=False)
        if not room_category:
            return False
        domain = [("category_id", "=", room_category.id)]
        override = assignment.room_id.room_tariff_id
        if override:
            return override
        tariffs = self.env["hms.tariff"].search(domain)
        # A room tariff is matched by having a price row for the billed class;
        # this keeps one tariff item per class rather than per room.
        for tariff in tariffs:
            if tariff.price_ids.filtered(lambda p: p.class_id == assignment.charge_class_id):
                return tariff
        return tariffs[:1]

    def _visiting_doctor(self, date):
        """The doctor who actually wrote a note that day, if any."""
        self.ensure_one()
        notes = self.env["hms.clinical.note"].search([
            ("encounter_id", "=", self.encounter_id.id),
            ("author_role", "=", "doctor"),
            ("noted_at", ">=", fields.Datetime.to_datetime(f"{date} 00:00:00")),
            ("noted_at", "<=", fields.Datetime.to_datetime(f"{date} 23:59:59")),
        ], limit=1)
        return notes.author_id
