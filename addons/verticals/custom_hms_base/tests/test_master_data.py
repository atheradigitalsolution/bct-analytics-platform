# -*- coding: utf-8 -*-
"""Tests for the pieces of hms_base that other modules trust blindly."""
import threading

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestPatient(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Patient = cls.env["hms.patient"]

    def _patient_vals(self, **kw):
        vals = {
            "name": "Budi Santoso",
            "nik": "3201010101900001",
            "birth_date": "1990-01-01",
            "gender": "male",
        }
        vals.update(kw)
        return vals

    def test_mrn_is_generated_and_formatted(self):
        patient = self.Patient.create(self._patient_vals())
        year = fields.Date.context_today(patient).strftime("%Y")
        self.assertTrue(patient.mrn.startswith(f"RM-{year}-"))
        self.assertEqual(len(patient.mrn.rsplit("-", 1)[1]), 6)

    def test_mrn_is_unique_across_many_creates(self):
        """Twenty registrations in one transaction must not collide."""
        patients = self.Patient.create([
            self._patient_vals(name=f"Pasien {i}", nik=f"32010101019{i:05d}")
            for i in range(20)
        ])
        self.assertEqual(len(set(patients.mapped("mrn"))), 20)

    def test_billing_partner_is_created_and_kept_in_sync(self):
        patient = self.Patient.create(self._patient_vals())
        self.assertTrue(patient.partner_id)
        self.assertEqual(patient.partner_id.name, "Budi Santoso")
        patient.write({"name": "Budi Santosa"})
        self.assertEqual(patient.partner_id.name, "Budi Santosa")

    def test_nik_must_be_sixteen_digits(self):
        with self.assertRaises(ValidationError):
            self.Patient.create(self._patient_vals(nik="12345"))

    def test_nik_optional_for_newborn(self):
        patient = self.Patient.create(
            self._patient_vals(nik=False, is_newborn=True, mother_name="Siti")
        )
        self.assertTrue(patient.mrn)

    def test_nik_required_for_ordinary_adult(self):
        with self.assertRaises(ValidationError):
            self.Patient.create(self._patient_vals(nik=False))

    def test_birth_date_cannot_be_in_the_future(self):
        future = fields.Date.add(fields.Date.context_today(self.Patient), days=1)
        with self.assertRaises(ValidationError):
            self.Patient.create(self._patient_vals(birth_date=future))

    def test_merge_marks_duplicate_and_points_forward(self):
        keep = self.Patient.create(self._patient_vals())
        dup = self.Patient.create(self._patient_vals(name="Budi S", nik="3201010101900002"))
        dup.action_merge_into(keep.id)
        self.assertEqual(dup.state, "merged")
        self.assertEqual(dup.merged_into_id, keep)
        self.assertFalse(dup.active)


@tagged("post_install", "-at_install", "hms")
class TestTariffResolution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cat = cls.env.ref("custom_hms_base.tariff_cat_procedure")
        cls.class_1 = cls.env.ref("custom_hms_base.care_class_1")
        cls.class_3 = cls.env.ref("custom_hms_base.care_class_3")
        cls.payer_bpjs = cls.env["hms.payer"].create({
            "code": "ZT-BPJS", "name": "BPJS Kesehatan", "type": "bpjs",
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-TND-001", "name": "Hecting", "category_id": cls.cat.id,
        })
        Price = cls.env["hms.tariff.price"]
        cls.generic = Price.create({"tariff_id": cls.tariff.id, "price_total": 100000})
        cls.by_class = Price.create({
            "tariff_id": cls.tariff.id, "class_id": cls.class_1.id, "price_total": 150000,
        })
        cls.by_payer = Price.create({
            "tariff_id": cls.tariff.id, "payer_id": cls.payer_bpjs.id, "price_total": 80000,
        })
        cls.by_both = Price.create({
            "tariff_id": cls.tariff.id, "class_id": cls.class_1.id,
            "payer_id": cls.payer_bpjs.id, "price_total": 90000,
        })

    def test_most_specific_row_wins(self):
        got = self.tariff.resolve_price(self.class_1.id, self.payer_bpjs.id)
        self.assertEqual(got, self.by_both)

    def test_payer_beats_class_when_both_are_not_available(self):
        got = self.tariff.resolve_price(self.class_3.id, self.payer_bpjs.id)
        self.assertEqual(got, self.by_payer)

    def test_falls_back_to_generic(self):
        got = self.tariff.resolve_price(self.class_3.id, None)
        self.assertEqual(got, self.generic)

    def test_expired_price_is_ignored(self):
        self.by_both.valid_to = "2000-01-01"
        got = self.tariff.resolve_price(self.class_1.id, self.payer_bpjs.id)
        self.assertEqual(got, self.by_payer)

    def test_components_must_reconcile_with_total(self):
        with self.assertRaises(ValidationError):
            self.env["hms.tariff.price"].create({
                "tariff_id": self.tariff.id,
                "class_id": self.class_3.id,
                "price_total": 100000,
                "amount_facility": 50000,
                "amount_medical": 30000,
            })

    def test_effective_amounts_apply_cito_multiplier(self):
        self.generic.write({
            "amount_facility": 60000, "amount_medical": 40000, "cito_multiplier": 1.5,
        })
        plain = self.tariff.resolve_price(self.class_3.id, None).effective_amounts(qty=1)
        self.assertAlmostEqual(plain["price_subtotal"], 100000)
        cito = self.tariff.resolve_price(self.class_3.id, None, cito=True).effective_amounts(qty=1)
        self.assertAlmostEqual(cito["price_subtotal"], 150000)
        self.assertAlmostEqual(cito["amount_medical"], 60000)

    def test_unsplit_price_credits_everything_to_facility(self):
        amounts = self.tariff.resolve_price(self.class_3.id, None).effective_amounts(qty=2)
        self.assertAlmostEqual(amounts["amount_facility"], 200000)
        self.assertAlmostEqual(amounts["amount_medical"], 0.0)


@tagged("post_install", "-at_install", "hms")
class TestBedStateMachine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        unit = cls.env["hms.unit"].create({
            "code": "ZT-RANAP", "name": "Rawat Inap", "type": "inpatient",
        })
        ward = cls.env["hms.ward"].create({
            "code": "ZT-W1", "name": "Melati", "unit_id": unit.id,
        })
        room = cls.env["hms.room"].create({
            "code": "ZT-R101", "name": "101", "ward_id": ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id, "capacity": 2,
        })
        cls.ward = ward
        cls.bed = cls.env["hms.bed"].create({
            "code": "ZT-R101-A", "name": "A", "room_id": room.id,
        })

    def test_bed_inherits_class_from_room(self):
        self.assertEqual(self.bed.class_id, self.env.ref("custom_hms_base.care_class_2"))

    def test_occupy_then_discharge_cycle(self):
        self.bed.action_occupy()
        self.assertEqual(self.bed.state, "occupied")
        self.assertTrue(self.bed.last_occupied_at)
        self.bed.action_start_cleaning()
        self.assertEqual(self.bed.state, "cleaning")
        self.bed.action_set_vacant()
        self.assertEqual(self.bed.state, "vacant")

    def test_cannot_occupy_an_occupied_bed(self):
        self.bed.action_occupy()
        from odoo.exceptions import UserError
        with self.assertRaises(UserError):
            self.bed.action_occupy()

    def test_ward_occupancy_counts_follow_bed_state(self):
        self.assertEqual(self.ward.bed_count, 1)
        self.assertEqual(self.ward.available_count, 1)
        self.bed.action_occupy()
        self.ward.invalidate_recordset()
        self.assertEqual(self.ward.occupied_count, 1)
        self.assertAlmostEqual(self.ward.occupancy_rate, 100.0)
