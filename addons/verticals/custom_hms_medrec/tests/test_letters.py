# -*- coding: utf-8 -*-
"""Surat bernomor, dan sertifikat kematian yang menghitung penyebab dasarnya."""
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestMedicalLetter(MedrecCase):
    def _letter(self, **kw):
        today = fields.Date.context_today(self.env.user)
        vals = {
            "type": "sick_leave",
            "patient_id": self.patient.id,
            "practitioner_id": self.doctor.id,
            "body": "Memerlukan istirahat.",
            "rest_from": today,
            "rest_to": today + timedelta(days=2),
        }
        vals.update(kw)
        return self.env["hms.medical.letter"].create(vals)

    def test_a_draft_has_no_number_yet(self):
        letter = self._letter()
        self.assertFalse(letter.name)

    def test_signing_issues_the_number(self):
        letter = self._letter()
        letter.action_sign()
        self.assertTrue(letter.name)
        self.assertTrue(letter.name.startswith("SKM-"))
        self.assertEqual(letter.state, "signed")
        self.assertEqual(letter.signed_by_id, self.doctor)
        self.assertEqual(letter.signed_uid, self.env.user)

    def test_rest_days_are_computed_inclusively(self):
        letter = self._letter()
        self.assertEqual(letter.rest_days, 3)

    def test_sick_leave_without_a_date_range_is_refused(self):
        letter = self._letter(rest_from=False, rest_to=False)
        with self.assertRaises(UserError):
            letter.action_sign()

    def test_a_nurse_cannot_be_the_signing_practitioner(self):
        """Kewenangan profesi, bukan kewenangan layar."""
        letter = self._letter(practitioner_id=self.nurse.id)
        with self.assertRaises(UserError):
            letter.action_sign()

    def test_reversed_rest_range_is_refused(self):
        today = fields.Date.context_today(self.env.user)
        with self.assertRaises(ValidationError):
            self._letter(rest_from=today, rest_to=today - timedelta(days=1))

    def test_a_numbered_letter_cannot_be_deleted(self):
        letter = self._letter()
        letter.action_sign()
        with self.assertRaises(UserError):
            letter.unlink()

    def test_cancelling_requires_a_reason(self):
        letter = self._letter()
        letter.action_sign()
        with self.assertRaises(UserError):
            letter.action_cancel()
        letter.cancel_reason = "Salah pasien."
        letter.action_cancel()
        self.assertEqual(letter.state, "cancelled")

    def test_a_letter_for_another_patients_encounter_is_refused(self):
        other = self.env["hms.patient"].create({
            "name": "Pasien Lain Surat", "nik": "3201010101870077",
            "birth_date": "1987-03-03", "gender": "female",
        })
        encounter = self._encounter(patient_id=other.id)
        with self.assertRaises(ValidationError):
            self._letter(encounter_id=encounter.id)


@tagged("post_install", "-at_install", "hms")
class TestDeathCertificate(MedrecCase):
    def _certificate(self, **kw):
        vals = {
            "patient_id": self.patient.id,
            "died_at": fields.Datetime.subtract(fields.Datetime.now(), hours=2),
            "admitted_at": fields.Datetime.subtract(fields.Datetime.now(), hours=6),
            "place_of_death": "hospital",
            "manner": "natural",
            "cause_a_id": self.icd_a.id,
            "certified_by_id": self.doctor.id,
        }
        vals.update(kw)
        return self.env["hms.death.certificate"].create(vals)

    def test_underlying_cause_is_the_deepest_filled_line_not_line_a(self):
        """Statistik mortalitas memakai penyebab dasar, bukan penyebab langsung."""
        certificate = self._certificate(cause_b_id=self.icd_b.id, cause_c_id=self.icd_c.id)
        self.assertEqual(certificate.underlying_cause_id, self.icd_c)
        self.assertNotEqual(certificate.underlying_cause_id, certificate.cause_a_id)

    def test_underlying_cause_falls_back_to_line_a_alone(self):
        certificate = self._certificate()
        self.assertEqual(certificate.underlying_cause_id, self.icd_a)

    def test_a_gap_in_the_causal_chain_is_refused(self):
        with self.assertRaises(ValidationError):
            self._certificate(cause_c_id=self.icd_c.id)

    def test_contributing_conditions_never_become_the_underlying_cause(self):
        certificate = self._certificate(contributing_ids=[(6, 0, [self.icd_c.id])])
        self.assertEqual(certificate.underlying_cause_id, self.icd_a)

    def test_ndr_needs_forty_eight_hours(self):
        short = self._certificate()
        self.assertFalse(short.is_ndr)
        long_stay = self._certificate(
            patient_id=self.env["hms.patient"].create({
                "name": "Pasien NDR", "nik": "3201010101870088",
                "birth_date": "1987-04-04", "gender": "male",
            }).id,
            admitted_at=fields.Datetime.subtract(fields.Datetime.now(), days=4),
        )
        self.assertTrue(long_stay.is_ndr)
        self.assertGreater(long_stay.hours_since_admission, 48)

    def test_signing_issues_a_number(self):
        certificate = self._certificate()
        certificate.action_sign()
        self.assertTrue(certificate.name.startswith("SKK-"))
        self.assertEqual(certificate.state, "signed")

    def test_a_nurse_cannot_certify_a_death(self):
        certificate = self._certificate(certified_by_id=self.nurse.id)
        with self.assertRaises(UserError):
            certificate.action_sign()

    def test_a_future_date_of_death_is_refused(self):
        with self.assertRaises(ValidationError):
            self._certificate(died_at=fields.Datetime.add(fields.Datetime.now(), days=1))

    def test_an_encounter_that_says_the_patient_went_home_is_refused(self):
        """Dua catatan yang membantah hidup-matinya pasien tidak boleh berdampingan."""
        encounter = self._encounter()
        encounter.discharge_disposition = "home"
        with self.assertRaises(ValidationError):
            self._certificate(encounter_id=encounter.id)

    def test_only_one_signed_certificate_per_patient(self):
        """Dua sertifikat kematian bertanda tangan untuk satu orang mustahil.

        Dijaga index unik parsial di Postgres, bukan hanya oleh kode Python:
        di Odoo 19, ``_sql_constraints`` diabaikan diam-diam, jadi penjaga
        seperti ini harus dibuktikan benar-benar ada di basis data.
        """
        first = self._certificate()
        first.action_sign()
        second = self._certificate()
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.cr.savepoint():
                second.action_sign()
                second.flush_recordset()
