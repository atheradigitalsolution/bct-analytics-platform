# -*- coding: utf-8 -*-
"""Slot generation, leave blocking, care team and consults."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class SchedulingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-SCH", "name": "Poli Jadwal", "type": "outpatient_clinic",
        })
        cls.unit2 = cls.env["hms.unit"].create({
            "code": "ZT-POLI-SCH2", "name": "Poli Jadwal 2", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Lukman Hakim", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101760001", "user_id": cls.env.user.id,
        })
        cls.other_doctor = cls.env["hms.practitioner"].create({
            "name": "Putri Ayu", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501760002",
        })
        # A Monday, so weekday arithmetic in the tests is unambiguous.
        today = fields.Date.context_today(cls.env["hms.unit"])
        cls.monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
        cls.template = cls.env["hms.schedule.template"].create({
            "practitioner_id": cls.doctor.id, "unit_id": cls.unit.id,
            "weekday": "0", "session": "morning",
            "time_from": 8.0, "time_to": 10.0, "slot_minutes": 30,
        })


@tagged("post_install", "-at_install", "hms")
class TestSlotGeneration(SchedulingCase):
    def test_slots_cover_the_session(self):
        slots = self.template.generate_slots(self.monday)
        self.assertEqual(len(slots), 4)
        self.assertAlmostEqual(min(slots.mapped("time_from")), 8.0)
        self.assertAlmostEqual(max(slots.mapped("time_to")), 10.0)

    def test_generation_is_idempotent(self):
        first = self.template.generate_slots(self.monday)
        second = self.template.generate_slots(self.monday)
        self.assertEqual(first, second)

    def test_no_slots_on_the_wrong_weekday(self):
        tuesday = self.monday + timedelta(days=1)
        self.assertFalse(self.template.generate_slots(tuesday))

    def test_no_slots_before_the_template_is_valid(self):
        self.template.valid_from = self.monday + timedelta(days=14)
        self.assertFalse(self.template.generate_slots(self.monday))

    def test_overlapping_templates_for_one_doctor_are_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.schedule.template"].create({
                "practitioner_id": self.doctor.id, "unit_id": self.unit2.id,
                "weekday": "0", "time_from": 9.0, "time_to": 11.0,
            })

    def test_non_overlapping_second_clinic_is_allowed(self):
        template = self.env["hms.schedule.template"].create({
            "practitioner_id": self.doctor.id, "unit_id": self.unit2.id,
            "weekday": "0", "time_from": 13.0, "time_to": 15.0,
        })
        self.assertTrue(template.id)

    def test_end_before_start_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.schedule.template"].create({
                "practitioner_id": self.other_doctor.id, "unit_id": self.unit.id,
                "weekday": "1", "time_from": 12.0, "time_to": 9.0,
            })


@tagged("post_install", "-at_install", "hms")
class TestScheduleException(SchedulingCase):
    def test_approved_leave_blocks_free_slots(self):
        self.template.generate_slots(self.monday)
        exception = self.env["hms.schedule.exception"].create({
            "practitioner_id": self.doctor.id, "type": "leave",
            "date_from": self.monday, "date_to": self.monday,
        })
        exception.action_approve()
        slots = self.env["hms.schedule.slot"].search([
            ("practitioner_id", "=", self.doctor.id), ("date", "=", self.monday),
        ])
        self.assertTrue(slots)
        self.assertTrue(all(s.state == "blocked" for s in slots))

    def test_booked_slots_are_surfaced_not_silently_blocked(self):
        slots = self.template.generate_slots(self.monday)
        slots[0].write({"state": "booked"})
        exception = self.env["hms.schedule.exception"].create({
            "practitioner_id": self.doctor.id, "type": "duty",
            "date_from": self.monday, "date_to": self.monday,
        })
        self.assertEqual(exception.affected_booked_count, 1)
        exception.action_approve()
        self.assertEqual(slots[0].state, "booked",
                         "Slot berisi pasien tidak boleh diblokir diam-diam.")

    def test_reassign_moves_booked_patients_to_the_replacement(self):
        slots = self.template.generate_slots(self.monday)
        slots[0].write({"state": "booked"})
        exception = self.env["hms.schedule.exception"].create({
            "practitioner_id": self.doctor.id, "type": "sick",
            "date_from": self.monday, "date_to": self.monday,
            "replacement_practitioner_id": self.other_doctor.id,
        })
        exception.action_approve()
        moved = exception.action_reassign()
        self.assertEqual(moved, 1)
        self.assertEqual(slots[0].practitioner_id, self.other_doctor)

    def test_reassign_without_a_replacement_is_refused(self):
        self.template.generate_slots(self.monday)
        exception = self.env["hms.schedule.exception"].create({
            "practitioner_id": self.doctor.id, "type": "sick",
            "date_from": self.monday, "date_to": self.monday,
        })
        with self.assertRaises(UserError):
            exception.action_reassign()

    def test_generation_after_an_approved_leave_produces_blocked_slots(self):
        exception = self.env["hms.schedule.exception"].create({
            "practitioner_id": self.doctor.id, "type": "training",
            "date_from": self.monday, "date_to": self.monday,
        })
        exception.action_approve()
        slots = self.template.generate_slots(self.monday)
        self.assertTrue(all(s.state == "blocked" for s in slots))


@tagged("post_install", "-at_install", "hms")
class TestCareTeamAndConsult(SchedulingCase):
    def setUp(self):
        super().setUp()
        self.patient = self.env["hms.patient"].create({
            "name": "Agus Wijaya", "nik": "3201010101940001",
            "birth_date": "1994-01-01", "gender": "male",
        })
        self.encounter = self.env["hms.encounter"].create({
            "patient_id": self.patient.id, "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })

    def test_registration_creates_the_dpjp_entry(self):
        dpjp = self.encounter.care_team_ids.filtered(lambda t: t.role == "dpjp")
        self.assertEqual(len(dpjp), 1)
        self.assertEqual(dpjp.practitioner_id, self.doctor)

    def test_changing_dpjp_retires_the_previous_one(self):
        self.env["hms.care.team"].assign(
            self.encounter, self.other_doctor, "dpjp", reason="Dokter cuti"
        )
        active = self.encounter.care_team_ids.filtered(
            lambda t: t.role == "dpjp" and t.is_active
        )
        self.assertEqual(len(active), 1)
        self.assertEqual(active.practitioner_id, self.other_doctor)
        self.assertEqual(self.encounter.practitioner_id, self.other_doctor)

    def test_audit_recognises_a_care_team_member(self):
        """With the real lookup installed, in-team access stops being flagged."""
        note = self.env["hms.clinical.note"].create({
            "encounter_id": self.encounter.id, "author_id": self.doctor.id,
            "assessment": "Observasi",
        })
        self.assertTrue(note._hms_audit_in_care_team())

    def test_consult_answer_lands_in_the_chart_as_a_signed_note(self):
        consult = self.env["hms.consult.request"].create({
            "encounter_id": self.encounter.id,
            "from_practitioner_id": self.doctor.id,
            "to_practitioner_id": self.other_doctor.id,
            "question": "Mohon evaluasi fungsi ginjal",
        })
        consult.action_accept()
        note = consult.action_answer("Fungsi ginjal masih baik, lanjutkan terapi.")
        self.assertEqual(consult.state, "answered")
        self.assertTrue(note.signed)
        self.assertEqual(note.note_type, "consult_answer")
        self.assertIn("ginjal", note.assessment)

    def test_accepting_a_consult_adds_the_consultant_to_the_care_team(self):
        consult = self.env["hms.consult.request"].create({
            "encounter_id": self.encounter.id,
            "from_practitioner_id": self.doctor.id,
            "to_practitioner_id": self.other_doctor.id,
            "question": "Mohon pendapat",
        })
        consult.action_accept()
        consultants = self.encounter.care_team_ids.filtered(lambda t: t.role == "consultant")
        self.assertEqual(consultants.practitioner_id, self.other_doctor)

    def test_declining_requires_a_reason(self):
        consult = self.env["hms.consult.request"].create({
            "encounter_id": self.encounter.id,
            "from_practitioner_id": self.doctor.id,
            "to_practitioner_id": self.other_doctor.id,
            "question": "Mohon pendapat",
        })
        with self.assertRaises(UserError):
            consult.action_decline()
