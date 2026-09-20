# -*- coding: utf-8 -*-
"""Komplain: target tanggap dari parameter, dan KPI yang tidak bisa dipalsukan.

INM "Kecepatan Waktu Tanggap Komplain" hanya bermakna bila tenggatnya berasal
dari kebijakan RS dan ``responded_at`` benar-benar menandai tanggapan yang
ditulis, bukan tombol yang ditekan.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestComplaint(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-KMP-POLI", "name": "Poli Uji Komplain", "type": "outpatient_clinic",
        })
        cls.settings = cls.env["hms.settings"].get_settings()
        cls.Complaint = cls.env["hms.complaint"]

    def _complaint(self, **vals):
        base = {
            "complainant_name": "Ny. Uji",
            "subject": "Antrian terlalu lama",
            "channel": "verbal",
            "category": "waiting_time",
            "unit_id": self.unit.id,
            "grade": "green",
        }
        base.update(vals)
        return self.Complaint.create(base)

    # --- tenggat parametrik ----------------------------------------------
    def test_target_hours_come_from_settings_per_grade(self):
        received = fields.Datetime.now()
        self.settings.write({
            "complaint_response_red_hours": 24,
            "complaint_response_yellow_hours": 72,
            "complaint_response_green_hours": 168,
        })
        for grade, hours in (("red", 24), ("yellow", 72), ("green", 168)):
            complaint = self._complaint(grade=grade, received_at=received)
            self.assertEqual(complaint.target_hours, hours)
            self.assertEqual(complaint.due_at, received + timedelta(hours=hours))

    def test_changing_the_parameter_moves_the_target(self):
        received = fields.Datetime.now()
        self.settings.complaint_response_red_hours = 4
        complaint = self._complaint(grade="red", received_at=received)
        self.assertEqual(complaint.target_hours, 4)
        self.assertEqual(complaint.due_at, received + timedelta(hours=4))

    def test_regrading_moves_the_deadline_before_a_response(self):
        received = fields.Datetime.now()
        self.settings.write({
            "complaint_response_red_hours": 24,
            "complaint_response_green_hours": 168,
        })
        complaint = self._complaint(grade="green", received_at=received)
        complaint.grade = "red"
        self.assertEqual(complaint.due_at, received + timedelta(hours=24))

    def test_deadline_is_frozen_once_responded(self):
        """Setelah ditanggapi, tenggatnya sudah menjadi bukti KPI."""
        self.settings.complaint_response_green_hours = 168
        complaint = self._complaint(grade="green")
        complaint.action_receive()
        complaint.response = "Kami mohon maaf, jadwal dibenahi."
        complaint.action_respond()
        frozen = complaint.due_at
        complaint.grade = "red"
        self.assertEqual(complaint.due_at, frozen)

    def test_zero_parameter_falls_back_to_inm_definition(self):
        self.settings.complaint_response_red_hours = 0
        complaint = self._complaint(grade="red")
        self.assertEqual(complaint.target_hours, 24)

    # --- KPI --------------------------------------------------------------
    def test_on_time_response_is_measured_against_due_at(self):
        self.settings.complaint_response_red_hours = 24
        complaint = self._complaint(grade="red")
        complaint.action_receive()
        complaint.response = "Sudah ditindaklanjuti kepala unit."
        complaint.action_respond()
        self.assertTrue(complaint.is_on_time)
        self.assertLess(complaint.response_hours, 1.0)

    def test_late_response_is_not_counted_as_on_time(self):
        self.settings.complaint_response_red_hours = 24
        complaint = self._complaint(
            grade="red", received_at=fields.Datetime.now() - timedelta(hours=48)
        )
        complaint.action_receive()
        complaint.response = "Terlambat ditanggapi."
        complaint.action_respond()
        self.assertFalse(complaint.is_on_time)
        self.assertGreater(complaint.response_hours, 47.0)

    # --- state machine ----------------------------------------------------
    def test_response_text_is_required(self):
        complaint = self._complaint()
        complaint.action_receive()
        with self.assertRaises(UserError):
            complaint.action_respond()

    def test_cannot_close_before_responding(self):
        complaint = self._complaint()
        complaint.action_receive()
        with self.assertRaises(UserError):
            complaint.action_close()

    def test_close_requires_an_outcome(self):
        complaint = self._complaint()
        complaint.action_receive()
        complaint.response = "Tanggapan diberikan langsung."
        complaint.action_respond()
        with self.assertRaises(UserError):
            complaint.action_close()
        complaint.outcome = "resolved"
        complaint.action_close()
        self.assertEqual(complaint.state, "closed")
        self.assertTrue(complaint.closed_at)

    def test_handler_is_recorded_when_work_starts(self):
        complaint = self._complaint()
        complaint.action_start()
        self.assertEqual(complaint.state, "in_progress")
        self.assertEqual(complaint.handler_id, self.env.user)

    def test_number_is_sequenced(self):
        complaint = self._complaint()
        self.assertTrue(complaint.name.startswith("KMP-"), complaint.name)

    def test_complaint_access_is_logged_unlike_incidents(self):
        """Komplain membawa data pasien dan BUKAN dokumen rahasia PMK 11/2017.

        Kebalikan dari hms.incident.report: di sini jejak akses justru harus
        ada, karena tidak ada kerahasiaan pelapor yang dirusaknya.
        """
        self.assertTrue(hasattr(self.Complaint, "_hms_log_access"))
