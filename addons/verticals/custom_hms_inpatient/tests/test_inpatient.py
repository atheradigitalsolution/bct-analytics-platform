# -*- coding: utf-8 -*-
"""Admission, transfer, class-based billing history and the nightly charge."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestInpatient(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.class_1 = cls.env.ref("custom_hms_base.care_class_1")
        cls.class_2 = cls.env.ref("custom_hms_base.care_class_2")
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RANAP-T", "name": "Rawat Inap", "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-W-MELATI", "name": "Melati", "unit_id": cls.unit.id,
        })
        cls.room2 = cls.env["hms.room"].create({
            "code": "ZT-R201", "name": "201", "ward_id": cls.ward.id,
            "class_id": cls.class_2.id, "capacity": 2,
        })
        cls.room1 = cls.env["hms.room"].create({
            "code": "ZT-R101", "name": "101", "ward_id": cls.ward.id,
            "class_id": cls.class_1.id, "capacity": 1,
        })
        cls.bed_a = cls.env["hms.bed"].create({
            "code": "ZT-R201-A", "name": "A", "room_id": cls.room2.id,
        })
        cls.bed_b = cls.env["hms.bed"].create({
            "code": "ZT-R101-A", "name": "A", "room_id": cls.room1.id,
        })
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Fajar Nugroho", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101790001", "user_id": cls.env.user.id,
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Sutrisno", "nik": "3201010101700001",
            "birth_date": "1970-01-01", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.dpjp.id,
        })
        cls.Admission = cls.env["hms.admission"]

        # Room tariffs, one price row per class.
        cls.room_tariff = cls.env["hms.tariff"].create({
            "code": "ZT-KMR", "name": "Akomodasi Kamar",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_room").id,
            "price_ids": [
                (0, 0, {"class_id": cls.class_1.id, "price_total": 500000}),
                (0, 0, {"class_id": cls.class_2.id, "price_total": 300000}),
            ],
        })

    def _admit(self, bed=None, entitled=None):
        return self.Admission.admit(
            self.encounter, bed or self.bed_a, self.dpjp,
            entitled_class=entitled or self.class_2,
        )

    def test_admission_occupies_the_bed_and_moves_the_encounter(self):
        adm = self._admit()
        self.assertEqual(adm.state, "admitted")
        self.assertEqual(self.bed_a.state, "occupied")
        self.assertEqual(self.encounter.state, "admitted")
        self.assertEqual(self.encounter.type, "inpatient")
        self.assertEqual(adm.bed_id, self.bed_a)
        self.assertEqual(adm.class_id, self.class_2)

    def test_admission_into_an_occupied_bed_is_refused(self):
        self._admit()
        other_patient = self.env["hms.patient"].create({
            "name": "Warga Lain", "nik": "3201010101700002",
            "birth_date": "1975-01-01", "gender": "female",
        })
        other_encounter = self.env["hms.encounter"].create({
            "patient_id": other_patient.id, "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
        })
        with self.assertRaises(UserError):
            self.Admission.admit(other_encounter, self.bed_a, self.dpjp,
                                 entitled_class=self.class_2)

    def test_transfer_closes_the_old_assignment_and_opens_a_new_one(self):
        adm = self._admit()
        adm.action_transfer(self.bed_b, reason="upgrade")
        self.assertEqual(adm.bed_id, self.bed_b)
        self.assertEqual(adm.class_id, self.class_1)
        self.assertEqual(len(adm.assignment_ids), 2)
        old = adm.assignment_ids.filtered(lambda a: a.bed_id == self.bed_a)
        self.assertFalse(old.is_current)
        self.assertTrue(old.to_at)
        self.assertEqual(self.bed_b.state, "occupied")
        self.assertEqual(self.bed_a.state, "cleaning")

    def test_upgrade_keeps_billing_at_the_entitled_class(self):
        """A BPJS patient moving up a class is still billed their own class.

        The difference is the patient's to pay; charging the payer for the
        better room is exactly the claim that gets rejected.
        """
        adm = self._admit(entitled=self.class_2)
        adm.action_transfer(self.bed_b, reason="upgrade")
        current = adm.assignment_ids.filtered("is_current")
        self.assertEqual(current.class_id, self.class_1, "Bed benar-benar kelas I")
        self.assertEqual(current.charge_class_id, self.class_2, "Tagihan tetap kelas II")

    def test_transfer_to_the_same_bed_is_refused(self):
        adm = self._admit()
        with self.assertRaises(UserError):
            adm.action_transfer(self.bed_a)

    def test_one_current_assignment_per_bed(self):
        """The partial unique index is the real guard, not the Python check."""
        adm = self._admit()
        with self.assertRaises(Exception):
            self.env["hms.bed.assignment"].create({
                "admission_id": adm.id, "bed_id": self.bed_a.id,
                "class_id": self.class_2.id, "charge_class_id": self.class_2.id,
                "is_current": True,
            })
            self.env.flush_all()

    def test_discharge_is_blocked_while_work_is_open(self):
        adm = self._admit()
        blockers = adm.discharge_check()
        self.assertTrue(blockers, "Ringkasan pulang belum final harus menahan pemulangan.")
        with self.assertRaises(UserError):
            adm.action_discharge()

    def test_forced_discharge_releases_the_bed_to_cleaning(self):
        adm = self._admit()
        adm.action_discharge(force=True)
        self.assertEqual(adm.state, "discharged")
        self.assertEqual(self.encounter.state, "discharged")
        self.assertEqual(self.bed_a.state, "cleaning",
                         "Bed tidak boleh langsung kosong sebelum dibersihkan.")
        self.assertFalse(adm.assignment_ids.filtered("is_current"))

    def test_length_of_stay_counts_a_same_day_stay_as_one(self):
        adm = self._admit()
        adm.action_discharge(force=True)
        self.assertEqual(adm.length_of_stay, 1)

    # --- daily charges ----------------------------------------------------
    def test_daily_charge_creates_room_and_nursing_rows(self):
        adm = self._admit()
        today = fields.Date.context_today(adm)
        created = adm._generate_daily_charges(today)
        types = set(created.mapped("charge_type"))
        self.assertIn("room", types)
        self.assertIn("nursing", types)

    def test_room_charge_uses_the_billed_class_not_the_bed_class(self):
        adm = self._admit(entitled=self.class_2)
        adm.action_transfer(self.bed_b, reason="upgrade")
        today = fields.Date.context_today(adm)
        created = adm._generate_daily_charges(today)
        room = created.filtered(lambda c: c.charge_type == "room")
        self.assertEqual(room.class_id, self.class_2)

    def test_visit_charge_only_appears_when_a_doctor_wrote_a_note(self):
        adm = self._admit()
        today = fields.Date.context_today(adm)
        first = adm._generate_daily_charges(today)
        self.assertNotIn("visit", set(first.mapped("charge_type")))

        note = self.env["hms.clinical.note"].create({
            "encounter_id": self.encounter.id, "author_id": self.dpjp.id,
            "author_role": "doctor", "note_type": "progress",
            "assessment": "Perbaikan klinis",
        })
        note.action_sign()
        # Re-running only adds what was missing; the room charge is not doubled.
        second = adm._generate_daily_charges(today)
        self.assertIn("visit", set(second.mapped("charge_type")))

    def test_rerunning_the_cron_does_not_double_charge(self):
        adm = self._admit()
        today = fields.Date.context_today(adm)
        adm._generate_daily_charges(today)
        count_after_first = self.env["hms.daily.charge"].search_count([
            ("admission_id", "=", adm.id), ("charge_date", "=", today),
        ])
        adm._generate_daily_charges(today)
        count_after_second = self.env["hms.daily.charge"].search_count([
            ("admission_id", "=", adm.id), ("charge_date", "=", today),
        ])
        self.assertEqual(count_after_first, count_after_second)

    def test_census_reports_occupancy(self):
        self._admit()
        census = self.Admission.census()
        ward_row = next(r for r in census["wards"] if r["ward_id"] == self.ward.id)
        self.assertEqual(ward_row["beds"], 2)
        self.assertEqual(ward_row["occupied"], 1)
        self.assertAlmostEqual(ward_row["bor"], 50.0)
