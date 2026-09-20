# -*- coding: utf-8 -*-
"""Pharmacy: allergy screening, high-alert double-check, FEFO stock movement."""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestPharmacy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-FAR", "name": "Poli Uji Farmasi", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Bayu Pratama", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101870001",
        })
        cls.pharmacist = cls.env["hms.practitioner"].create({
            "name": "Nurul Aini", "title_prefix": "apt.", "type": "pharmacist",
            "nik": "3201014501870002", "user_id": cls.env.user.id,
        })
        cls.witness = cls.env["hms.practitioner"].create({
            "name": "Rudi Hartono", "type": "pharmacy_tech", "nik": "3201010101870003",
        })

        cls.amoxicillin = cls.env["hms.ingredient"].create({"name": "ZT-Amoksisilin"})
        cls.paracetamol = cls.env["hms.ingredient"].create({"name": "ZT-Parasetamol"})

        warehouse = cls.env["stock.warehouse"].search([], limit=1)
        cls.stock_location = warehouse.lot_stock_id
        cls.depot = cls.env["hms.depot"].create({
            "code": "ZT-DEPO-RJ", "name": "Depo Rawat Jalan", "type": "outpatient",
            "location_id": cls.stock_location.id,
        })

        cls.med_amox = cls._make_medicine(cls, "Amoksisilin 500 mg", cls.amoxicillin)
        cls.med_para = cls._make_medicine(cls, "Parasetamol 500 mg", cls.paracetamol)
        cls.med_high = cls._make_medicine(cls, "Heparin 5000 IU", cls.paracetamol,
                                          high_alert=True)

        cls.patient = cls.env["hms.patient"].create({
            "name": "Rina Marlina", "nik": "3201014501930001",
            "birth_date": "1993-01-05", "gender": "female",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })
        cls.Rx = cls.env["hms.prescription"]

    def _make_medicine(self, name, ingredient, high_alert=False):
        template = self.env["product.template"].create({
            "name": name, "is_storable": True, "tracking": "lot",
            "use_expiration_date": True, "list_price": 5000.0,
        })
        return self.env["hms.medicine"].create({
            "product_tmpl_id": template.id,
            "generic_name": name,
            "item_type": "drug",
            "is_high_alert": high_alert,
            "ingredient_ids": [(0, 0, {"ingredient_id": ingredient.id, "strength": 500})],
        })

    def _stock_in(self, medicine, qty, expiry_days):
        """Put `qty` into the depot on a lot expiring in `expiry_days`."""
        lot = self.env["stock.lot"].create({
            "name": f"LOT-{medicine.id}-{expiry_days}",
            "product_id": medicine.product_id.id,
            "expiration_date": fields.Datetime.add(fields.Datetime.now(), days=expiry_days),
        })
        self.env["stock.quant"].with_context(inventory_mode=True).create({
            "product_id": medicine.product_id.id,
            "location_id": self.stock_location.id,
            "lot_id": lot.id,
            "inventory_quantity": qty,
        })._apply_inventory()
        return lot

    def _rx(self, medicine=None, qty=10):
        return self.Rx.create({
            "encounter_id": self.encounter.id,
            "practitioner_id": self.doctor.id,
            "depot_id": self.depot.id,
            "line_ids": [(0, 0, {
                "medicine_id": (medicine or self.med_para).id,
                "qty_prescribed": qty, "sig": "3x1 sesudah makan",
            })],
        })

    # --- numbering and workflow ------------------------------------------
    def test_prescription_number_is_generated(self):
        self.assertTrue(self._rx().name.startswith("RX-"))

    def test_full_workflow_reaches_dispensed(self):
        self._stock_in(self.med_para, 50, 365)
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        rx.action_prepare()
        rx.action_ready()
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")
        self.assertTrue(rx.picking_id)
        self.assertEqual(rx.picking_id.state, "done")

    def test_empty_prescription_cannot_be_submitted(self):
        rx = self.Rx.create({
            "encounter_id": self.encounter.id, "practitioner_id": self.doctor.id,
            "depot_id": self.depot.id,
        })
        with self.assertRaises(UserError):
            rx.action_submit()

    def test_rejection_requires_a_reason(self):
        rx = self._rx()
        rx.action_submit()
        with self.assertRaises(UserError):
            rx.action_reject()

    def test_dispensed_prescription_cannot_be_cancelled(self):
        self._stock_in(self.med_para, 50, 365)
        rx = self._rx()
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        with self.assertRaises(UserError):
            rx.action_cancel()

    # --- allergy screening ------------------------------------------------
    def test_allergy_is_detected_by_active_ingredient(self):
        self.env["hms.patient.allergy"].create({
            "patient_id": self.patient.id, "substance": "ZT-Amoksisilin",
            "ingredient_id": self.amoxicillin.id, "severity": "severe",
        })
        rx = self._rx(self.med_amox)
        self.assertIn("ZT-Amoksisilin", rx.allergy_warning)

    def test_allergy_recorded_only_as_free_text_is_still_detected(self):
        self.env["hms.patient.allergy"].create({
            "patient_id": self.patient.id, "substance": "zt-amoksisilin", "severity": "moderate",
        })
        rx = self._rx(self.med_amox)
        self.assertTrue(rx.allergy_warning)

    def test_allergy_warning_does_not_block_dispensing(self):
        """A warning is advice to the pharmacist, not a wall."""
        self._stock_in(self.med_amox, 20, 365)
        self.env["hms.patient.allergy"].create({
            "patient_id": self.patient.id, "substance": "ZT-Amoksisilin",
            "ingredient_id": self.amoxicillin.id, "severity": "mild",
        })
        rx = self._rx(self.med_amox)
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")

    def test_unrelated_allergy_produces_no_warning(self):
        self.env["hms.patient.allergy"].create({
            "patient_id": self.patient.id, "substance": "Udang", "substance_type": "food",
        })
        self.assertFalse(self._rx(self.med_para).allergy_warning)

    # --- high alert -------------------------------------------------------
    def test_high_alert_without_witness_is_refused(self):
        self._stock_in(self.med_high, 20, 365)
        rx = self._rx(self.med_high)
        rx.action_submit()
        rx.action_verify()
        with self.assertRaises(UserError):
            rx.action_dispense()

    def test_high_alert_with_witness_is_allowed(self):
        self._stock_in(self.med_high, 20, 365)
        rx = self._rx(self.med_high)
        rx.witness_id = self.witness
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        self.assertEqual(rx.state, "dispensed")

    def test_witness_cannot_be_the_dispensing_pharmacist(self):
        self._stock_in(self.med_high, 20, 365)
        rx = self._rx(self.med_high)
        rx.witness_id = self.pharmacist
        rx.action_submit()
        rx.action_verify()
        with self.assertRaises(UserError):
            rx.action_dispense()

    # --- stock ------------------------------------------------------------
    def test_dispensing_reduces_depot_stock(self):
        self._stock_in(self.med_para, 50, 365)
        before = self.env["stock.quant"]._get_available_quantity(
            self.med_para.product_id, self.stock_location
        )
        rx = self._rx(qty=10)
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        after = self.env["stock.quant"]._get_available_quantity(
            self.med_para.product_id, self.stock_location
        )
        self.assertAlmostEqual(before - after, 10.0)

    def test_fefo_takes_the_earliest_expiring_lot_first(self):
        far = self._stock_in(self.med_para, 20, 700)
        near = self._stock_in(self.med_para, 20, 30)
        rx = self._rx(qty=15)
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        used = rx.picking_id.move_ids.move_line_ids.mapped("lot_id")
        self.assertIn(near, used, "Lot kedaluwarsa terdekat harus dipakai lebih dulu.")
        self.assertNotIn(far, used)

    def test_fefo_spills_into_the_next_lot_when_needed(self):
        near = self._stock_in(self.med_para, 10, 30)
        far = self._stock_in(self.med_para, 20, 700)
        rx = self._rx(qty=15)
        rx.action_submit()
        rx.action_verify()
        rx.action_dispense()
        lines = rx.picking_id.move_ids.move_line_ids
        by_lot = {ml.lot_id: ml.quantity for ml in lines}
        self.assertAlmostEqual(by_lot[near], 10.0)
        self.assertAlmostEqual(by_lot[far], 5.0)

    def test_insufficient_stock_is_refused_loudly(self):
        self._stock_in(self.med_para, 3, 365)
        rx = self._rx(qty=10)
        rx.action_submit()
        rx.action_verify()
        with self.assertRaises(UserError):
            rx.action_dispense()

    # --- validation -------------------------------------------------------
    def test_dispensing_more_than_prescribed_is_refused(self):
        rx = self._rx(qty=10)
        with self.assertRaises(ValidationError):
            rx.line_ids.write({"qty_dispense": 20})

    def test_drug_without_lot_tracking_is_refused(self):
        template = self.env["product.template"].create({
            "name": "Obat tanpa lot", "is_storable": True, "tracking": "none",
            "use_expiration_date": False,
        })
        with self.assertRaises(ValidationError):
            self.env["hms.medicine"].create({
                "product_tmpl_id": template.id, "generic_name": "Obat tanpa lot",
                "item_type": "drug",
            })

    def test_pending_prescription_blocks_encounter_closing(self):
        rx = self._rx()
        rx.action_submit()
        with self.assertRaises(UserError):
            self.encounter.action_close()
