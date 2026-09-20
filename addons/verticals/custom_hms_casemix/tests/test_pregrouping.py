# -*- coding: utf-8 -*-
"""Aturan pre-grouping yang bisa dihitung tanpa E-Klaim."""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestReadmission(CasemixCase):
    def _inpatient_episode(self, days_ago, icd10=None):
        """Satu episode rawat inap yang sudah selesai, sekian hari lalu."""
        arrival = fields.Datetime.subtract(fields.Datetime.now(), days=days_ago)
        encounter = self._encounter(
            type="inpatient", unit_id=self.ward.id, arrival_at=arrival,
        )
        diagnosis = self._complete_documents(encounter, icd10=icd10)
        encounter.action_close()
        encounter.write({
            "closed_at": arrival + relativedelta(days=2),
            "state": "discharged",
        })
        return encounter, diagnosis

    def test_a_readmission_inside_the_window_is_detected(self):
        settings = self.env["hms.settings"].get_settings()
        settings.readmission_window_days = 30
        self._inpatient_episode(days_ago=40)
        first, _dx = self._inpatient_episode(days_ago=20)
        second, diagnosis = self._inpatient_episode(days_ago=5)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_run_pregrouping()
        self.assertTrue(claim.is_readmission)
        self.assertEqual(claim.readmission_source_id, first)

    def test_a_readmission_needs_a_reason_before_coding_finishes(self):
        settings = self.env["hms.settings"].get_settings()
        settings.readmission_window_days = 30
        self._inpatient_episode(days_ago=20)
        second, diagnosis = self._inpatient_episode(days_ago=5)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        with self.assertRaises(UserError):
            claim.action_code_done()
        self.assertTrue(claim.is_readmission)
        self.assertEqual(claim.state, "coding")

        claim.write({"readmission_reason": "Pasien kembali dengan perburukan "
                                           "setelah pulang atas permintaan sendiri."})
        claim.action_code_done()
        self.assertEqual(claim.state, "internal_review")

    def test_a_visit_outside_the_window_is_not_a_readmission(self):
        settings = self.env["hms.settings"].get_settings()
        settings.readmission_window_days = 7
        self._inpatient_episode(days_ago=20)
        second, diagnosis = self._inpatient_episode(days_ago=1)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_code_done()
        self.assertFalse(claim.is_readmission)

    def test_a_different_primary_diagnosis_is_not_a_readmission(self):
        settings = self.env["hms.settings"].get_settings()
        settings.readmission_window_days = 30
        self._inpatient_episode(days_ago=10, icd10=self.icd_a)
        second, diagnosis = self._inpatient_episode(days_ago=2, icd10=self.icd_b)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_code_done()
        self.assertFalse(claim.is_readmission)

    def test_the_window_really_comes_from_the_parameter(self):
        """Ubah jendelanya, hasil deteksinya ikut berubah."""
        settings = self.env["hms.settings"].get_settings()
        self._inpatient_episode(days_ago=15)
        second, diagnosis = self._inpatient_episode(days_ago=2)
        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })

        settings.readmission_window_days = 7
        claim.action_run_pregrouping()
        self.assertFalse(claim.is_readmission)

        settings.readmission_window_days = 30
        claim.action_run_pregrouping()
        self.assertTrue(claim.is_readmission)


@tagged("post_install", "-at_install", "hms")
class TestFragmentation(CasemixCase):
    def _outpatient_visit(self, days_ago, unit=None):
        arrival = fields.Datetime.subtract(fields.Datetime.now(), days=days_ago)
        encounter = self._encounter(unit_id=(unit or self.unit).id, arrival_at=arrival)
        diagnosis = self._complete_documents(encounter)
        encounter.action_close()
        return encounter, diagnosis

    def test_repeat_outpatient_visits_inside_the_window_are_flagged(self):
        settings = self.env["hms.settings"].get_settings()
        settings.fragmentation_window_days = 7
        self._outpatient_visit(days_ago=3)
        second, diagnosis = self._outpatient_visit(days_ago=1)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_code_done()
        self.assertTrue(claim.is_fragmentation)

    def test_visits_in_a_different_unit_are_not_fragmentation(self):
        settings = self.env["hms.settings"].get_settings()
        settings.fragmentation_window_days = 7
        self._outpatient_visit(days_ago=3, unit=self.unit_b)
        second, diagnosis = self._outpatient_visit(days_ago=1)

        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_code_done()
        self.assertFalse(claim.is_fragmentation)

    def test_fragmentation_flags_but_never_blocks(self):
        """Sebagian kunjungan berulang memang sah; koder yang menjelaskan."""
        settings = self.env["hms.settings"].get_settings()
        settings.fragmentation_window_days = 7
        self._outpatient_visit(days_ago=2)
        second, diagnosis = self._outpatient_visit(days_ago=1)
        claim = self._claim(second)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        claim.action_code_done()
        self.assertTrue(claim.is_fragmentation)
        self.assertEqual(claim.state, "internal_review")
