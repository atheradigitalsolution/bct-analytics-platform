# -*- coding: utf-8 -*-
"""The demo scenarios are the integration test: they cross every module."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestDemoScenario(TransactionCase):
    def test_outpatient_journey_runs_end_to_end(self):
        result = self.env["hms.demo.scenario"].run_outpatient()
        labels = [step[0] for step in result["steps"]]
        for expected in ("Pendaftaran", "TTV", "CPPT", "Diagnosis", "Laboratorium",
                         "E-resep", "Apotek", "Kunjungan"):
            self.assertIn(expected, labels, f"Langkah '{expected}' tidak terjadi.")

    def test_outpatient_journey_produces_a_priced_bill(self):
        result = self.env["hms.demo.scenario"].run_outpatient()
        bill = self.env["hms.bill"].browse(result["bill_id"])
        self.assertTrue(bill.exists())
        self.assertGreater(bill.amount_total, 0)
        self.assertTrue(bill.line_ids)

    def test_dispensing_in_the_journey_really_moves_stock(self):
        encounter_id = self.env["hms.demo.scenario"].run_outpatient()["encounter_id"]
        prescription = self.env["hms.prescription"].search(
            [("encounter_id", "=", encounter_id)], limit=1
        )
        self.assertEqual(prescription.state, "dispensed")
        self.assertTrue(prescription.picking_id)
        self.assertEqual(prescription.picking_id.state, "done")
        self.assertTrue(prescription.picking_id.move_ids.move_line_ids.lot_id,
                        "Penyerahan harus memilih lot, bukan stok tanpa lot.")

    def test_lab_flag_is_computed_against_the_patients_own_range(self):
        encounter_id = self.env["hms.demo.scenario"].run_outpatient()["encounter_id"]
        results = self.env["hms.lab.result"].search([("encounter_id", "=", encounter_id)])
        wbc = results.filtered(lambda r: r.parameter_id.code == "WBC")
        self.assertEqual(wbc.flag, "high")
        self.assertEqual(wbc.state, "verified")

    def test_inpatient_journey_occupies_a_bed_and_charges_the_day(self):
        result = self.env["hms.demo.scenario"].run_inpatient()
        admission = self.env["hms.admission"].browse(result["admission_id"])
        self.assertEqual(admission.state, "admitted")
        self.assertEqual(admission.bed_id.state, "occupied")
        self.assertTrue(admission.daily_charge_ids)

    def test_inpatient_journey_reports_what_blocks_discharge(self):
        result = self.env["hms.demo.scenario"].run_inpatient()
        self.assertTrue(result["blockers"],
                        "Pasien baru masuk tidak boleh langsung bisa dipulangkan.")

    def test_doctor_instruction_becomes_a_nursing_task(self):
        result = self.env["hms.demo.scenario"].run_inpatient()
        tasks = self.env["hms.nursing.task"].search([
            ("admission_id", "=", result["admission_id"]), ("type", "=", "instruction"),
        ])
        self.assertTrue(tasks)
        self.assertIn("infus", tasks[0].detail.lower())
