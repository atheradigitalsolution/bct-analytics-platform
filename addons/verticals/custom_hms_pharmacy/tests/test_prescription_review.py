# -*- coding: utf-8 -*-
"""Telaah resep 3 aspek dan intervensi apoteker.

Berkas ini ditambahkan **di samping** ``test_pharmacy.py``, yang tidak diubah
satu baris pun. Tes pertama di bawah menjaga justru hal itu: gerbang
verifikasi lama harus tetap berperilaku persis seperti sebelum telaah tiga
aspek ada, supaya "hijau" tidak dicapai dengan menggeser artinya.
"""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestPrescriptionReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-TLH", "name": "Poli Uji Telaah", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Yusuf Maulana", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101870051",
        })
        cls.pharmacist = cls.env["hms.practitioner"].create({
            "name": "Laila Rahma", "title_prefix": "apt.", "type": "pharmacist",
            "nik": "3201014501870052", "user_id": cls.env.user.id,
        })
        warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.depot = cls.env["hms.depot"].create({
            "code": "ZT-DEPO-TLH", "name": "Depo Uji Telaah", "type": "outpatient",
            "location_id": warehouse.lot_stock_id.id,
        })
        ingredient = cls.env["hms.ingredient"].create({"name": "ZT-Metformin"})
        template = cls.env["product.template"].create({
            "name": "Metformin 500 mg", "is_storable": True, "tracking": "lot",
            "use_expiration_date": True, "list_price": 2000.0,
        })
        cls.medicine = cls.env["hms.medicine"].create({
            "product_tmpl_id": template.id, "generic_name": "Metformin 500 mg",
            "item_type": "drug",
            "ingredient_ids": [(0, 0, {"ingredient_id": ingredient.id, "strength": 500})],
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien Telaah", "nik": "3201014501870053",
            "birth_date": "1987-05-05", "gender": "female",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })
        cls.Rx = cls.env["hms.prescription"]
        cls.Intervention = cls.env["hms.prescription.intervention"]

    def _rx(self):
        return self.Rx.create({
            "encounter_id": self.encounter.id,
            "practitioner_id": self.doctor.id,
            "depot_id": self.depot.id,
            "line_ids": [(0, 0, {
                "medicine_id": self.medicine.id,
                "qty_prescribed": 10, "sig": "2x1 sesudah makan",
            })],
        })

    def _stock_in(self, qty=50):
        lot = self.env["stock.lot"].create({
            "name": f"LOT-TLH-{self.medicine.id}",
            "product_id": self.medicine.product_id.id,
            "expiration_date": fields.Datetime.add(fields.Datetime.now(), days=180),
        })
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": self.medicine.product_id.id,
            "location_id": self.depot.location_id.id,
            "lot_id": lot.id,
            "inventory_quantity": qty,
        })._apply_inventory()

    # --- gerbang lama tidak berubah maknanya ------------------------------
    def test_verify_gate_still_works_without_any_review(self):
        """``action_verify`` tidak diberi prasyarat baru.

        Kalau telaah tiga aspek dijadikan syarat verifikasi, kolom
        ``verified_by_id`` yang sudah terisi di basis data akan mendadak
        berarti sesuatu yang tidak pernah terjadi.
        """
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        self.assertEqual(rx.state, "verified")
        self.assertEqual(rx.verified_by_id, self.pharmacist)
        self.assertTrue(rx.verified_at)
        self.assertEqual(rx.review_state, "pending")

    def test_dispense_still_works_without_any_review(self):
        self._stock_in()
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")

    # --- telaah tiga aspek ------------------------------------------------
    def test_review_state_tracks_the_three_aspects(self):
        rx = self._rx()
        self.assertEqual(rx.review_state, "pending")
        rx.review_admin_result = "ok"
        self.assertEqual(rx.review_state, "partial")
        rx.review_pharmaceutic_result = "ok"
        self.assertEqual(rx.review_state, "partial")
        rx.review_clinical_result = "ok"
        self.assertEqual(rx.review_state, "complete")

    def test_any_issue_makes_the_review_an_issue(self):
        rx = self._rx()
        rx.write({
            "review_admin_result": "ok",
            "review_pharmaceutic_result": "ok",
            "review_clinical_result": "issue",
            "review_clinical_note": "Dosis melebihi maksimum untuk eGFR pasien.",
        })
        self.assertEqual(rx.review_state, "issue")

    def test_recording_a_partial_review_is_refused(self):
        rx = self._rx()
        rx.review_admin_result = "ok"
        with self.assertRaises(UserError):
            rx.action_record_review()

    def test_recording_a_complete_review_stamps_who_and_when(self):
        rx = self._rx()
        rx.write({
            "review_admin_result": "ok",
            "review_pharmaceutic_result": "ok",
            "review_clinical_result": "na",
        })
        rx.action_record_review()
        self.assertEqual(rx.reviewed_by_id, self.pharmacist)
        self.assertTrue(rx.reviewed_at)

    def test_review_does_not_move_the_prescription_state(self):
        """Telaah dan verifikasi adalah dua ukuran, bukan satu."""
        rx = self._rx()
        rx.action_submit()
        rx.write({
            "review_admin_result": "ok",
            "review_pharmaceutic_result": "ok",
            "review_clinical_result": "ok",
        })
        rx.action_record_review()
        self.assertEqual(rx.state, "submitted")
        self.assertFalse(rx.verified_by_id)

    # --- intervensi apoteker ----------------------------------------------
    def _hold(self, rx):
        return self.Intervention.create({
            "prescription_id": rx.id,
            "issue_type": "dose",
            "finding": "Dosis metformin tidak sesuai fungsi ginjal pasien.",
            "action_taken": "hold",
            "pharmacist_id": self.pharmacist.id,
        })

    def test_an_open_hold_blocks_dispensing(self):
        self._stock_in()
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        self._hold(rx)
        self.assertTrue(rx.has_blocking_intervention)
        with self.assertRaises(UserError):
            rx.action_dispense()

    def test_resolving_the_intervention_releases_the_prescription(self):
        self._stock_in()
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        intervention = self._hold(rx)
        intervention.outcome = "accepted"
        intervention.action_resolve()
        self.assertFalse(rx.has_blocking_intervention)
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")

    def test_withdrawing_a_hold_requires_a_reason(self):
        rx = self._rx()
        intervention = self._hold(rx)
        with self.assertRaises(UserError):
            intervention.action_withdraw()
        intervention.withdraw_reason = "Dokter sudah menjawab lewat telepon."
        intervention.action_withdraw()
        self.assertEqual(intervention.state, "withdrawn")
        self.assertFalse(rx.has_blocking_intervention)

    def test_resolving_requires_an_outcome(self):
        rx = self._rx()
        intervention = self._hold(rx)
        with self.assertRaises(UserError):
            intervention.action_resolve()

    def test_a_non_holding_intervention_does_not_block_dispensing(self):
        """Mencatat temuan tidak boleh menghentikan pelayanan dengan sendirinya."""
        self._stock_in()
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        self.Intervention.create({
            "prescription_id": rx.id,
            "issue_type": "formulary",
            "finding": "Obat di luar Fornas, pasien membayar sendiri.",
            "action_taken": "education",
            "pharmacist_id": self.pharmacist.id,
        })
        self.assertEqual(rx.open_intervention_count, 1)
        self.assertFalse(rx.has_blocking_intervention)
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")
