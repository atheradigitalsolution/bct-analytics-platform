# -*- coding: utf-8 -*-
"""TBaK: urutan tulis - baca ulang - konfirmasi tidak boleh dilompati.

Yang diuji bukan tombolnya. Sebuah aksi yang menolak lompatan tidak berarti
apa-apa bila ``write({'state': 'confirmed'})`` lewat API atau impor data bisa
melakukannya — jadi lompatan diuji dari kedua arah.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestVerbalOrder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-VO-IGD", "name": "IGD Uji TBaK", "type": "emergency",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Hendra Gunawan", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101880031",
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Dewi Lestari", "type": "nurse", "nik": "3201014501880032",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien TBaK", "nik": "3201014501880033",
            "birth_date": "1988-03-03", "gender": "female",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "type": "emergency", "triage_level": "yellow",
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
        })
        cls.settings = cls.env["hms.settings"].get_settings()
        cls.VO = cls.env["hms.verbal.order"]

    def _order(self, **vals):
        base = {
            "encounter_id": self.encounter.id,
            "prescriber_id": self.doctor.id,
            "receiver_id": self.nurse.id,
            "medium": "phone",
            "content": "Berikan furosemid 20 mg IV bolus pelan sekarang.",
        }
        base.update(vals)
        return self.VO.create(base)

    # --- lompatan state ---------------------------------------------------
    def test_cannot_confirm_without_read_back_via_action(self):
        order = self._order()
        self.assertEqual(order.state, "spoken")
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_cannot_confirm_without_read_back_via_write(self):
        """Aksi menjaga tombol; constraint menjaga datanya."""
        order = self._order()
        with self.assertRaises(ValidationError):
            order.write({"state": "confirmed"})

    def test_cannot_stamp_a_confirmation_time_without_read_back(self):
        order = self._order()
        with self.assertRaises(ValidationError):
            order.write({"confirmed_at": fields.Datetime.now()})

    def test_happy_path_records_all_three_timestamps(self):
        order = self._order()
        order.action_read_back()
        self.assertEqual(order.state, "read_back")
        self.assertTrue(order.read_back_at)
        order.action_confirm()
        self.assertEqual(order.state, "confirmed")
        self.assertTrue(order.confirmed_at)
        self.assertLessEqual(order.spoken_at, order.read_back_at)
        self.assertLessEqual(order.read_back_at, order.confirmed_at)

    def test_read_back_twice_is_refused(self):
        order = self._order()
        order.action_read_back()
        with self.assertRaises(UserError):
            order.action_read_back()

    # --- tenggat parametrik ----------------------------------------------
    def test_confirm_deadline_comes_from_settings(self):
        spoken = fields.Datetime.now() - timedelta(minutes=5)
        self.settings.verbal_order_confirm_hours = 24
        first = self._order(spoken_at=spoken)
        self.assertEqual(first.confirm_hours_applied, 24)
        self.assertEqual(first.confirm_due_at, spoken + timedelta(hours=24))

        self.settings.verbal_order_confirm_hours = 6
        second = self._order(spoken_at=spoken)
        self.assertEqual(second.confirm_due_at, spoken + timedelta(hours=6))

    def test_zero_parameter_falls_back_to_one_day(self):
        self.settings.verbal_order_confirm_hours = 0
        order = self._order()
        self.assertEqual(order.confirm_hours_applied, 24)

    # --- lewat tenggat: ditandai, tidak diblokir ---------------------------
    def test_cron_marks_overdue_orders_expired(self):
        self.settings.verbal_order_confirm_hours = 24
        order = self._order(spoken_at=fields.Datetime.now() - timedelta(hours=30))
        order.action_read_back()
        self.VO._cron_flag_expired()
        self.assertEqual(order.state, "expired")
        self.assertTrue(order.is_overdue)

    def test_expired_order_can_still_be_signed_late(self):
        """Memblokir tanda tangan terlambat hanya menghasilkan order tanpa tanda tangan."""
        self.settings.verbal_order_confirm_hours = 24
        order = self._order(spoken_at=fields.Datetime.now() - timedelta(hours=30))
        order.action_read_back()
        self.VO._cron_flag_expired()
        order.action_confirm()
        self.assertEqual(order.state, "confirmed")

    def test_expired_order_without_read_back_still_cannot_be_confirmed(self):
        self.settings.verbal_order_confirm_hours = 1
        order = self._order(spoken_at=fields.Datetime.now() - timedelta(hours=5))
        self.VO._cron_flag_expired()
        self.assertEqual(order.state, "expired")
        with self.assertRaises(UserError):
            order.action_confirm()

    def test_cron_leaves_confirmed_orders_alone(self):
        self.settings.verbal_order_confirm_hours = 24
        order = self._order(spoken_at=fields.Datetime.now() - timedelta(hours=30))
        order.action_read_back()
        order.action_confirm()
        self.VO._cron_flag_expired()
        self.assertEqual(order.state, "confirmed")

    # --- integritas -------------------------------------------------------
    def test_prescriber_and_receiver_must_differ(self):
        with self.assertRaises(ValidationError):
            self._order(receiver_id=self.doctor.id)

    def test_read_back_cannot_precede_the_instruction(self):
        order = self._order()
        order.action_read_back()
        with self.assertRaises(ValidationError):
            order.write({"spoken_at": fields.Datetime.now() + timedelta(hours=1)})

    def test_confirmed_order_cannot_be_cancelled(self):
        order = self._order()
        order.action_read_back()
        order.action_confirm()
        order.cancel_reason = "Salah pasien."
        with self.assertRaises(UserError):
            order.action_cancel()

    def test_cancel_requires_a_reason(self):
        order = self._order()
        with self.assertRaises(UserError):
            order.action_cancel()

    def test_number_is_sequenced(self):
        order = self._order()
        self.assertTrue(order.name.startswith("VO-"), order.name)

    def test_patient_is_derived_from_the_encounter(self):
        order = self._order()
        self.assertEqual(order.patient_id, self.patient)
