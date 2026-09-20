# -*- coding: utf-8 -*-
"""Rekonsiliasi obat: yang diuji adalah gerbang penutupannya.

Sebuah rekonsiliasi yang bisa ditutup dengan baris tanpa keputusan adalah
daftar obat, bukan rekonsiliasi — dan pada laporan kepatuhan keduanya terlihat
persis sama.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestMedicationReconciliation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ward = cls.env["hms.unit"].create({
            "code": "ZT-RANAP-REK", "name": "Bangsal Uji Rekonsiliasi", "type": "inpatient",
        })
        cls.icu = cls.env["hms.unit"].create({
            "code": "ZT-ICU-REK", "name": "ICU Uji Rekonsiliasi", "type": "icu",
        })
        cls.pharmacist = cls.env["hms.practitioner"].create({
            "name": "Fitri Handayani", "title_prefix": "apt.", "type": "pharmacist",
            "nik": "3201014501850061",
        })
        template = cls.env["product.template"].create({
            "name": "Amlodipin 10 mg", "is_storable": True, "tracking": "lot",
            "use_expiration_date": True, "list_price": 1500.0,
        })
        cls.amlodipine = cls.env["hms.medicine"].create({
            "product_tmpl_id": template.id, "generic_name": "Amlodipin 10 mg",
            "item_type": "drug",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien Rekonsiliasi", "nik": "3201014501850062",
            "birth_date": "1985-06-06", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.ward.id, "type": "inpatient",
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
        })
        cls.Recon = cls.env["hms.medication.reconciliation"]

    def _recon(self, lines=None, **vals):
        base = {
            "encounter_id": self.encounter.id,
            "moment": "admission",
            "performed_by_id": self.pharmacist.id,
        }
        base.update(vals)
        if lines is not None:
            base["line_ids"] = [(0, 0, line) for line in lines]
        return self.Recon.create(base)

    # --- gerbang penutupan -------------------------------------------------
    def test_cannot_complete_with_an_undecided_line(self):
        recon = self._recon(lines=[{"home_medicine_name": "Amlodipin 10 mg dari apotek luar"}])
        recon.action_start()
        with self.assertRaises(UserError):
            recon.action_complete()

    def test_cannot_complete_a_stop_without_a_reason(self):
        recon = self._recon(lines=[{
            "home_medicine_name": "Jamu pegal linu", "decision": "stop",
        }])
        with self.assertRaises(UserError):
            recon.action_complete()

    def test_cannot_complete_a_substitution_without_the_substitute(self):
        recon = self._recon(lines=[{
            "home_medicine_name": "Norvask 10 mg",
            "decision": "substitute",
            "reason": "Merek tidak tersedia, diganti generik.",
        }])
        with self.assertRaises(UserError):
            recon.action_complete()

    def test_complete_succeeds_when_every_line_is_decided(self):
        recon = self._recon(lines=[
            {"home_medicine_name": "Norvask 10 mg", "decision": "substitute",
             "reason": "Merek tidak tersedia.",
             "substitute_medicine_id": self.amlodipine.id},
            {"home_medicine_name": "Vitamin B kompleks", "decision": "continue"},
            {"home_medicine_name": "Jamu pegal linu", "decision": "stop",
             "reason": "Kandungan tidak diketahui, berisiko interaksi."},
        ])
        recon.action_start()
        recon.action_complete()
        self.assertEqual(recon.state, "completed")
        self.assertTrue(recon.completed_at)
        self.assertEqual(recon.line_count, 3)
        self.assertEqual(recon.discrepancy_count, 2)

    def test_empty_reconciliation_must_say_so_explicitly(self):
        """Kosong-karena-tidak-ada-obat vs kosong-karena-belum-dikerjakan."""
        recon = self._recon()
        with self.assertRaises(UserError):
            recon.action_complete()
        recon.no_home_medication = True
        recon.action_complete()
        self.assertEqual(recon.state, "completed")

    def test_no_home_medication_cannot_coexist_with_lines(self):
        with self.assertRaises(ValidationError):
            self._recon(
                lines=[{"home_medicine_name": "Amlodipin", "decision": "continue"}],
                no_home_medication=True,
            )

    # --- tiga momen -------------------------------------------------------
    def test_all_three_moments_are_available(self):
        selection = dict(self.Recon._fields["moment"].selection)
        self.assertEqual(set(selection), {"admission", "transfer", "discharge"})

    def test_admission_reconciliation_happens_once_per_encounter(self):
        first = self._recon(no_home_medication=True)
        first.action_complete()
        with self.assertRaises(ValidationError):
            self._recon(no_home_medication=True)

    def test_transfer_reconciliation_may_repeat(self):
        first = self._recon(moment="transfer", no_home_medication=True,
                            from_unit_id=self.ward.id, to_unit_id=self.icu.id)
        first.action_complete()
        second = self._recon(moment="transfer", no_home_medication=True,
                             from_unit_id=self.icu.id, to_unit_id=self.ward.id)
        second.action_complete()
        self.assertEqual(second.state, "completed")

    def test_discharge_reconciliation_is_separate_from_admission(self):
        admission = self._recon(no_home_medication=True)
        admission.action_complete()
        discharge = self._recon(moment="discharge", no_home_medication=True)
        discharge.action_complete()
        self.assertEqual(discharge.state, "completed")

    # --- integritas -------------------------------------------------------
    def test_home_medicine_needs_no_formulary_match(self):
        """Obat warung dan jamu justru yang paling perlu tercatat."""
        recon = self._recon(lines=[{
            "home_medicine_name": "Obat herbal tanpa merek dari tetangga",
            "decision": "stop", "reason": "Kandungan tidak diketahui.",
        }])
        recon.action_complete()
        self.assertFalse(recon.line_ids.medicine_id)
        self.assertEqual(recon.state, "completed")

    def test_completed_reconciliation_cannot_be_cancelled(self):
        recon = self._recon(no_home_medication=True)
        recon.action_complete()
        with self.assertRaises(UserError):
            recon.action_cancel()

    def test_cancelled_reconciliation_frees_the_moment(self):
        first = self._recon(no_home_medication=True)
        first.action_cancel()
        second = self._recon(no_home_medication=True)
        second.action_complete()
        self.assertEqual(second.state, "completed")

    def test_patient_is_derived_from_the_encounter(self):
        recon = self._recon(no_home_medication=True)
        self.assertEqual(recon.patient_id, self.patient)

    def test_number_is_sequenced(self):
        recon = self._recon(no_home_medication=True)
        self.assertTrue(recon.name.startswith("REK-"), recon.name)
