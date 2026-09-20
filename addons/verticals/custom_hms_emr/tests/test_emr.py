# -*- coding: utf-8 -*-
"""The append-only guarantee is the whole point of this module, so it is
tested from several directions: direct write, unlink, and the revision path."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


class EmrCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-EMR", "name": "Poli Uji", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Rina Hartati", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501850001", "unit_ids": [(4, cls.unit.id)],
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Joko Susilo", "nik": "3201010101880001",
            "birth_date": "1988-01-01", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id,
            "unit_id": cls.unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })
        cls.Note = cls.env["hms.clinical.note"]

    def _note(self, **kw):
        vals = {
            "encounter_id": self.encounter.id,
            "author_id": self.doctor.id,
            "note_type": "soap",
            "subjective": "Demam tiga hari",
            "assessment": "Suspek demam dengue",
            "plan": "Cek darah lengkap",
        }
        vals.update(kw)
        return self.Note.create(vals)


@tagged("post_install", "-at_install", "hms")
class TestClinicalNoteAppendOnly(EmrCase):
    def test_unsigned_note_is_editable(self):
        note = self._note()
        note.write({"assessment": "Demam dengue"})
        self.assertEqual(note.assessment, "Demam dengue")

    def test_signing_stores_a_hash(self):
        note = self._note()
        note.action_sign()
        self.assertTrue(note.signed)
        self.assertTrue(note.signature_hash)
        self.assertEqual(len(note.signature_hash), 64)
        self.assertTrue(note.verify_signature())

    def test_signed_note_refuses_content_change(self):
        note = self._note()
        note.action_sign()
        with self.assertRaises(UserError):
            note.write({"assessment": "diubah diam-diam"})

    def test_signed_note_refuses_deletion(self):
        note = self._note()
        note.action_sign()
        with self.assertRaises(UserError):
            note.unlink()

    def test_signed_note_refuses_change_even_with_sudo(self):
        """sudo() is not an escape hatch — the guard lives in write()."""
        note = self._note()
        note.action_sign()
        with self.assertRaises(UserError):
            note.sudo().write({"plan": "diubah lewat sudo"})

    def test_signing_twice_is_refused(self):
        note = self._note()
        note.action_sign()
        with self.assertRaises(UserError):
            note.action_sign()

    def test_revision_creates_a_new_version_and_retires_the_old(self):
        note = self._note()
        note.action_sign()
        action = note.action_revise(reason="Salah ketik diagnosis")
        new = self.Note.browse(action["res_id"])
        self.assertEqual(new.revises_id, note)
        self.assertTrue(new.is_current)
        self.assertFalse(note.is_current)
        self.assertEqual(note.revised_by_id, new)
        self.assertFalse(new.signed)
        self.assertEqual(new.revision_reason, "Salah ketik diagnosis")

    def test_old_version_is_still_readable_after_revision(self):
        note = self._note(assessment="Asesmen asli")
        note.action_sign()
        note.action_revise(reason="perbaikan")
        self.assertEqual(note.assessment, "Asesmen asli")
        self.assertTrue(note.verify_signature())

    def test_cannot_revise_twice(self):
        note = self._note()
        note.action_sign()
        note.action_revise()
        with self.assertRaises(UserError):
            note.action_revise()

    def test_cannot_revise_an_unsigned_note(self):
        note = self._note()
        with self.assertRaises(UserError):
            note.action_revise()

    def test_tampering_breaks_signature_verification(self):
        """Direct SQL bypasses the ORM guard — the hash is what catches it."""
        note = self._note()
        note.action_sign()
        self.env.cr.execute(
            "UPDATE hms_clinical_note SET assessment = %s WHERE id = %s",
            ("diubah lewat SQL", note.id),
        )
        note.invalidate_recordset()
        self.assertFalse(note.verify_signature())

    def test_empty_note_is_refused(self):
        with self.assertRaises(ValidationError):
            self.Note.create({
                "encounter_id": self.encounter.id, "author_id": self.doctor.id,
            })

    def test_encounter_cannot_close_with_unsigned_notes(self):
        self._note()
        with self.assertRaises(UserError):
            self.encounter.action_close()

    def test_encounter_closes_once_notes_are_signed(self):
        note = self._note()
        note.action_sign()
        self.encounter.action_close()
        self.assertEqual(self.encounter.state, "finished")


@tagged("post_install", "-at_install", "hms")
class TestObservation(EmrCase):
    def test_bmi_is_computed(self):
        obs = self.env["hms.observation"].create({
            "encounter_id": self.encounter.id, "weight_kg": 70.0, "height_cm": 170.0,
        })
        self.assertAlmostEqual(obs.bmi, 24.2, places=1)

    def test_gcs_total_sums_components(self):
        obs = self.env["hms.observation"].create({
            "encounter_id": self.encounter.id,
            "gcs_eye": 4, "gcs_verbal": 5, "gcs_motor": 6,
        })
        self.assertEqual(obs.gcs_total, 15)

    def test_diastolic_above_systolic_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.observation"].create({
                "encounter_id": self.encounter.id, "systolic": 80, "diastolic": 120,
            })

    def test_impossible_temperature_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.observation"].create({
                "encounter_id": self.encounter.id, "temperature": 65.0,
            })

    def test_fall_risk_bands(self):
        Obs = self.env["hms.observation"]
        low = Obs.create({"encounter_id": self.encounter.id, "fall_risk_score": 10})
        mid = Obs.create({"encounter_id": self.encounter.id, "fall_risk_score": 30})
        high = Obs.create({"encounter_id": self.encounter.id, "fall_risk_score": 50})
        self.assertEqual((low.fall_risk_level, mid.fall_risk_level, high.fall_risk_level),
                         ("low", "medium", "high"))

    def test_latest_measurements_are_copied_to_the_patient_header(self):
        self.env["hms.observation"].create({
            "encounter_id": self.encounter.id, "weight_kg": 68.0, "height_cm": 165.0,
        })
        self.assertAlmostEqual(self.patient.weight_kg_last, 68.0)
        self.assertAlmostEqual(self.patient.height_cm_last, 165.0)


@tagged("post_install", "-at_install", "hms")
class TestDiagnosisAndSummary(EmrCase):
    def test_only_one_final_primary_diagnosis_per_encounter(self):
        Dx = self.env["hms.diagnosis"]
        icd = self.env["hms.icd10"].create({"code": "ZT-A90", "name_en": "Dengue fever"})
        icd2 = self.env["hms.icd10"].create({"code": "ZT-A91", "name_en": "Dengue haemorrhagic fever"})
        Dx.create({"encounter_id": self.encounter.id, "icd10_id": icd.id,
                   "rank": "primary", "stage": "final"})
        with self.assertRaises(Exception):
            Dx.create({"encounter_id": self.encounter.id, "icd10_id": icd2.id,
                       "rank": "primary", "stage": "final"})
            self.env.flush_all()

    def test_final_diagnosis_cannot_be_deleted(self):
        icd = self.env["hms.icd10"].create({"code": "ZT-J18", "name_en": "Pneumonia"})
        dx = self.env["hms.diagnosis"].create({
            "encounter_id": self.encounter.id, "icd10_id": icd.id,
            "rank": "primary", "stage": "final",
        })
        with self.assertRaises(UserError):
            dx.unlink()

    def test_summary_is_generated_from_recorded_data(self):
        icd = self.env["hms.icd10"].create({"code": "ZT-I10", "name_en": "Hypertension"})
        self.env["hms.diagnosis"].create({
            "encounter_id": self.encounter.id, "icd10_id": icd.id, "rank": "primary",
        })
        note = self._note(subjective="Pusing", plan="Amlodipin 5mg")
        note.action_sign()
        summary = self.env["hms.summary"].generate_for(self.encounter)
        self.assertEqual(summary.diagnosis_primary_id, icd)
        self.assertIn("Pusing", summary.history)
        self.assertIn("Amlodipin", summary.treatment)

    def test_summary_cannot_be_finalised_without_a_primary_diagnosis(self):
        summary = self.env["hms.summary"].generate_for(self.encounter)
        with self.assertRaises(UserError):
            summary.action_finalize()

    def test_final_summary_is_immutable(self):
        icd = self.env["hms.icd10"].create({"code": "ZT-E11", "name_en": "Type 2 diabetes"})
        summary = self.env["hms.summary"].create({
            "encounter_id": self.encounter.id, "diagnosis_primary_id": icd.id,
        })
        summary.action_finalize()
        with self.assertRaises(UserError):
            summary.write({"treatment": "diubah"})


@tagged("post_install", "-at_install", "hms")
class TestConsent(EmrCase):
    def test_signing_snapshots_the_text_the_patient_read(self):
        template = self.env["hms.consent.template"].create({
            "code": "ZT-IC-01", "name": "Informed Consent Tindakan",
            "type": "procedure", "body": "<p>Teks versi satu</p>",
        })
        consent = self.env["hms.consent"].create({
            "patient_id": self.patient.id, "encounter_id": self.encounter.id,
            "template_id": template.id, "signer_name": "Joko Susilo",
        })
        consent.action_sign()
        template.body = "<p>Teks versi dua</p>"
        self.assertIn("versi satu", consent.body_snapshot)

    def test_procedure_requiring_consent_refuses_to_save_without_one(self):
        cat = self.env.ref("custom_hms_base.tariff_cat_procedure")
        tariff = self.env["hms.tariff"].create({
            "code": "ZT-OP-01", "name": "Apendektomi", "category_id": cat.id,
            "requires_consent": True,
        })
        with self.assertRaises(ValidationError):
            self.env["hms.procedure"].create({
                "encounter_id": self.encounter.id, "name": "Apendektomi",
                "tariff_id": tariff.id,
            })
