# -*- coding: utf-8 -*-
"""IKP: tenggat dari parameter, alur state, dan batas anonimitas.

Yang diuji di sini bukan "apakah field-nya ada", melainkan tiga hal yang bisa
rusak diam-diam:

1. ``due_at`` yang terlihat parametrik padahal angkanya tertanam di kode —
   satu-satunya cara membedakannya adalah MENGUBAH parameternya dan melihat
   tenggatnya ikut bergeser;
2. state machine yang bisa dilompati lewat ``write()`` langsung;
3. "anonim" yang ternyata tetap menyimpan pelapor di kolom, sehingga bocor
   pada ekspor pertama.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestIncidentReport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-KP-IGD", "name": "IGD Uji KP", "type": "emergency",
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Sri Wahyuni", "type": "nurse", "nik": "3201014501900011",
        })
        cls.settings = cls.env["hms.settings"].get_settings()
        cls.Incident = cls.env["hms.incident.report"]

    def _incident(self, **vals):
        base = {
            "unit_id": self.unit.id,
            "reporter_id": self.nurse.id,
            "incident_type": "knc",
            "chronology": "Kronologi uji.",
        }
        base.update(vals)
        return self.Incident.create(base)

    # --- tenggat dari kebijakan, bukan dari kode --------------------------
    def test_due_at_follows_settings_parameter(self):
        """Mengubah parameter harus menggeser tenggat laporan berikutnya."""
        occurred = fields.Datetime.now() - timedelta(hours=1)
        self.settings.incident_report_due_hours = 48
        first = self._incident(occurred_at=occurred)
        self.assertEqual(first.due_hours_applied, 48)
        self.assertEqual(first.due_at, occurred + timedelta(hours=48))

        self.settings.incident_report_due_hours = 12
        second = self._incident(occurred_at=occurred)
        self.assertEqual(second.due_hours_applied, 12)
        self.assertEqual(
            second.due_at, occurred + timedelta(hours=12),
            "due_at tidak ikut parameter: angkanya tertanam di kode, bukan kebijakan",
        )

    def test_due_at_is_frozen_after_submission(self):
        """Tenggat sebuah insiden adalah kebijakan saat insiden itu terjadi."""
        occurred = fields.Datetime.now() - timedelta(hours=2)
        self.settings.incident_report_due_hours = 48
        incident = self._incident(occurred_at=occurred)
        incident.action_report()
        frozen = incident.due_at
        self.settings.incident_report_due_hours = 6
        incident.invalidate_recordset()
        self.assertEqual(incident.due_at, frozen)

    def test_due_at_moves_while_still_draft(self):
        """Koreksi jam kejadian pada draf menggeser tenggatnya."""
        self.settings.incident_report_due_hours = 48
        incident = self._incident(occurred_at=fields.Datetime.now() - timedelta(hours=1))
        corrected = fields.Datetime.now() - timedelta(hours=5)
        incident.occurred_at = corrected
        self.assertEqual(incident.due_at, corrected + timedelta(hours=48))

    def test_zero_parameter_falls_back_to_pmk_norm(self):
        """Parameter kosong tidak boleh melahirkan tenggat yang sudah lewat."""
        occurred = fields.Datetime.now()
        self.settings.incident_report_due_hours = 0
        incident = self._incident(occurred_at=occurred)
        self.assertEqual(incident.due_hours_applied, 48)
        self.assertGreater(incident.due_at, occurred)

    def test_late_report_is_flagged_with_hours(self):
        self.settings.incident_report_due_hours = 48
        incident = self._incident(occurred_at=fields.Datetime.now() - timedelta(hours=72))
        incident.action_report()
        self.assertTrue(incident.is_late)
        self.assertGreater(incident.late_hours, 23.0)

    def test_report_within_deadline_is_not_late(self):
        self.settings.incident_report_due_hours = 48
        incident = self._incident(occurred_at=fields.Datetime.now() - timedelta(hours=3))
        incident.action_report()
        self.assertFalse(incident.is_late)
        self.assertEqual(incident.late_hours, 0.0)

    # --- anonimitas -------------------------------------------------------
    def test_anonymous_report_must_not_store_a_reporter(self):
        """Anonim = tidak dicatat. Dicatat-lalu-disembunyikan bocor saat ekspor."""
        with self.assertRaises(ValidationError):
            self._incident(is_anonymous=True)

    def test_anonymous_report_without_reporter_is_accepted(self):
        incident = self._incident(is_anonymous=True, reporter_id=False)
        self.assertFalse(incident.reporter_id)
        self.assertIn("Anonim", incident.reporter_display)

    def test_incident_report_is_not_audited(self):
        """Keputusan sadar: mengaudit IKP akan membongkar pelapor anonim.

        ``hms.access.log`` menyimpan user_id + res_id; satu join sudah cukup
        memetakan laporan anonim kembali ke pembuatnya. Karena itu model ini
        tidak mewarisi ``hms.audited`` — dan itu harus tetap begitu.
        """
        self.assertFalse(
            hasattr(self.Incident, "_hms_log_access"),
            "hms.incident.report mewarisi hms.audited — pelapor anonim jadi terlacak",
        )
        incident = self._incident(is_anonymous=True, reporter_id=False)
        logs = self.env["hms.access.log"].search([
            ("model_name", "=", "hms.incident.report"),
            ("res_id", "=", incident.id),
        ])
        self.assertFalse(logs, "laporan insiden tidak boleh masuk jejak akses rekam medis")

    # --- state machine ----------------------------------------------------
    def test_report_requires_chronology(self):
        incident = self._incident(chronology=False)
        with self.assertRaises(UserError):
            incident.action_report()

    def test_cannot_investigate_before_reported(self):
        incident = self._incident()
        with self.assertRaises(UserError):
            incident.action_start_investigation()

    def test_cannot_grade_before_investigation(self):
        incident = self._incident()
        incident.action_report()
        with self.assertRaises(UserError):
            incident.action_grade()

    def test_grade_requires_root_cause_and_recommendation(self):
        incident = self._incident()
        incident.action_report()
        incident.action_start_investigation()
        incident.grade = "yellow"
        with self.assertRaises(UserError):
            incident.action_grade()
        incident.root_cause = "Rak LASA tidak dipisah."
        with self.assertRaises(UserError):
            incident.action_grade()
        incident.recommendation = "Pisahkan rak dan beri penanda LASA."
        incident.action_grade()
        self.assertEqual(incident.state, "graded")

    def test_cannot_close_before_grading(self):
        incident = self._incident()
        incident.action_report()
        incident.action_start_investigation()
        with self.assertRaises(UserError):
            incident.action_close()

    def test_full_cycle_records_who_and_when(self):
        incident = self._incident()
        incident.action_report()
        incident.action_start_investigation()
        incident.write({
            "grade": "red",
            "root_cause": "Tidak ada pengecekan ganda.",
            "recommendation": "Terapkan double-check.",
        })
        incident.action_grade()
        incident.action_close()
        self.assertEqual(incident.state, "closed")
        self.assertTrue(incident.reported_at)
        self.assertTrue(incident.investigation_started_at)
        self.assertTrue(incident.graded_at and incident.graded_by_id)
        self.assertTrue(incident.closed_at and incident.closed_by_id)

    def test_red_and_yellow_grade_demand_rca(self):
        incident = self._incident()
        incident.grade = "red"
        self.assertEqual(incident.investigation_method, "rca")
        incident.grade = "yellow"
        self.assertEqual(incident.investigation_method, "rca")
        incident.grade = "green"
        self.assertEqual(incident.investigation_method, "simple")
        incident.grade = "blue"
        self.assertEqual(incident.investigation_method, "simple")

    # --- integritas data --------------------------------------------------
    def test_incident_may_have_no_patient(self):
        """KPC dan insiden yang menimpa staf tetap wajib dilaporkan."""
        incident = self._incident(incident_type="kpc", patient_id=False)
        incident.action_report()
        self.assertFalse(incident.patient_id)
        self.assertEqual(incident.state, "reported")

    def test_encounter_must_belong_to_the_linked_patient(self):
        patient_a = self.env["hms.patient"].create({
            "name": "Pasien KP A", "nik": "3201014501900012",
            "birth_date": "1990-01-05", "gender": "female",
        })
        patient_b = self.env["hms.patient"].create({
            "name": "Pasien KP B", "nik": "3201014501900013",
            "birth_date": "1991-02-06", "gender": "male",
        })
        encounter_b = self.env["hms.encounter"].create({
            "patient_id": patient_b.id, "unit_id": self.unit.id,
            "type": "emergency", "triage_level": "green",
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
        })
        with self.assertRaises(ValidationError):
            self._incident(patient_id=patient_a.id, encounter_id=encounter_b.id)

    def test_number_is_sequenced(self):
        incident = self._incident()
        self.assertTrue(incident.name.startswith("IKP-"), incident.name)
