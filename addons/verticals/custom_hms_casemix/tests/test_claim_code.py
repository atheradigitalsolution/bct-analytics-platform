# -*- coding: utf-8 -*-
"""Bukti bahwa koding klaim tidak pernah mencemari diagnosis dokter."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestClaimCodeIsolation(CasemixCase):
    def test_coding_a_different_code_leaves_the_doctors_diagnosis_alone(self):
        """Keputusan arsitektur inti modul ini, diuji dari dua arah."""
        encounter, diagnosis = self._claimable_encounter()
        original_code = diagnosis.icd10_id
        diagnosis_count_before = self.env["hms.diagnosis"].search_count([
            ("encounter_id", "=", encounter.id),
        ])

        claim = self._claim(encounter)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id,
            "kind": "icd10",
            "icd10_id": self.icd_b.id,
            "role": "principal",
            "source_diagnosis_id": diagnosis.id,
            "change_reason": "Resume menyebut kondisi B sebagai penyebab utama "
                             "perawatan; kondisi A hanya komorbid.",
        })

        # Arah pertama: diagnosis dokter tidak berubah nilainya.
        diagnosis.invalidate_recordset()
        self.assertEqual(diagnosis.icd10_id, original_code)
        self.assertNotEqual(diagnosis.icd10_id, self.icd_b)
        # Arah kedua: tidak ada baris diagnosis baru yang lahir diam-diam.
        self.assertEqual(
            self.env["hms.diagnosis"].search_count([("encounter_id", "=", encounter.id)]),
            diagnosis_count_before,
        )
        # Dan kode klaimnya memang yang dipilih koder.
        self.assertEqual(claim.code_ids.icd10_id, self.icd_b)
        self.assertTrue(claim.code_ids.changed_by_coder)

    def test_a_reason_is_mandatory_when_the_code_differs(self):
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(ValidationError):
            self.Code.create({
                "claim_id": claim.id,
                "kind": "icd10",
                "icd10_id": self.icd_b.id,
                "role": "principal",
                "source_diagnosis_id": diagnosis.id,
            })

    def test_no_reason_needed_when_the_code_matches_the_doctor(self):
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        code = self.Code.create({
            "claim_id": claim.id,
            "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id,
            "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        self.assertFalse(code.changed_by_coder)

    def test_a_code_without_any_source_always_counts_as_changed(self):
        """Kode yang tidak ada di catatan klinis adalah perubahan terbesar."""
        encounter, _diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(ValidationError):
            self.Code.create({
                "claim_id": claim.id,
                "kind": "icd10",
                "icd10_id": self.icd_b.id,
                "role": "comorbidity",
            })
        code = self.Code.create({
            "claim_id": claim.id,
            "kind": "icd10",
            "icd10_id": self.icd_b.id,
            "role": "comorbidity",
            "change_reason": "Tertulis pada CPPT hari ke-2 tetapi tidak dientri "
                             "sebagai diagnosis.",
        })
        self.assertTrue(code.changed_by_coder)

    def test_a_source_diagnosis_from_another_encounter_is_refused(self):
        encounter, _diagnosis = self._claimable_encounter()
        other_encounter, other_diagnosis = self._claimable_encounter(
            unit_id=self.unit_b.id
        )
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(ValidationError):
            self.Code.create({
                "claim_id": claim.id,
                "kind": "icd10",
                "icd10_id": other_diagnosis.icd10_id.id,
                "role": "principal",
                "source_diagnosis_id": other_diagnosis.id,
            })

    def test_codes_cannot_be_touched_after_finalization(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        with self.assertRaises(ValidationError):
            claim.code_ids[0].write({"change_reason": "dirapikan belakangan"})


@tagged("post_install", "-at_install", "hms")
class TestClaimCodeShape(CasemixCase):
    def test_icd10_and_icd9_columns_do_not_mix(self):
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(ValidationError):
            self.Code.create({
                "claim_id": claim.id, "kind": "icd10",
                "icd10_id": diagnosis.icd10_id.id, "icd9_id": self.icd9_a.id,
                "role": "principal", "source_diagnosis_id": diagnosis.id,
            })

    def test_a_diagnosis_role_is_refused_on_a_procedure_code(self):
        encounter, _diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(ValidationError):
            self.Code.create({
                "claim_id": claim.id, "kind": "icd9", "icd9_id": self.icd9_a.id,
                "role": "comorbidity", "change_reason": "uji",
            })

    def test_a_claim_may_hold_a_principal_diagnosis_and_a_principal_procedure(self):
        """Keduanya ada pada episode rawat inap; index unik harus per jenis."""
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        procedure_code = self.Code.create({
            "claim_id": claim.id, "kind": "icd9", "icd9_id": self.icd9_a.id,
            "role": "principal", "change_reason": "Tindakan tercatat di laporan "
                                                  "operasi tanpa entri prosedur.",
        })
        claim.code_ids.flush_recordset()
        self.assertEqual(len(claim.code_ids), 2)
        self.assertTrue(procedure_code.is_primary)

    def test_is_primary_follows_the_role(self):
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        code = self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        self.assertTrue(code.is_primary)
        code.write({"role": "comorbidity"})
        self.assertFalse(code.is_primary)

    def test_coding_cannot_finish_without_a_principal_diagnosis(self):
        encounter, _diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.action_start_coding()
        with self.assertRaises(UserError):
            claim.action_code_done()
