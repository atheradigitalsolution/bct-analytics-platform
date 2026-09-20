# -*- coding: utf-8 -*-
"""Analytic tagging, doctor fee accrual, overhead allocation and the P&L view."""
import json

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class PnlCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-PNL", "name": "Poli P&L", "type": "outpatient_clinic", "area_m2": 60,
        })
        cls.lab = cls.env["hms.unit"].create({
            "code": "ZT-LAB-PNL", "name": "Lab P&L", "type": "lab", "area_m2": 40,
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Sinta Dewi", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501850055", "user_id": cls.env.user.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-TND-PNL", "name": "Tindakan P&L",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": cls.clinic.id,
            "price_ids": [(0, 0, {
                "price_total": 200000, "amount_facility": 120000,
                "amount_medical": 60000, "amount_consumable": 20000,
            })],
        })
        cls.lab_tariff = cls.env["hms.tariff"].create({
            "code": "ZT-LAB-PNL1", "name": "Lab P&L",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_lab").id,
            "unit_id": cls.lab.id,
            "price_ids": [(0, 0, {"price_total": 100000, "amount_facility": 100000})],
        })

    def _closed_bill(self, tariff=None):
        patient = self.env["hms.patient"].create({
            "name": "Pasien PNL %s" % self.env["hms.patient"].search_count([]),
            "gender": "male", "birth_date": "1985-01-01",
            "nik": f"32018801010{self.env['hms.patient'].search_count([]) + 300:05d}",
        })
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "line_ids": [(0, 0, {"tariff_id": (tariff or self.tariff).id})],
        })
        order.action_submit()
        order.line_ids.action_done()
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.action_open()
        bill.action_close()
        return bill


@tagged("post_install", "-at_install", "hms")
class TestAnalyticTagging(PnlCase):
    def test_unit_gets_an_analytic_account_on_demand(self):
        self.assertFalse(self.clinic.analytic_account_id)
        account = self.clinic._ensure_analytic()
        self.assertTrue(account)
        self.assertEqual(account.code, self.clinic.code)

    def test_invoice_lines_carry_the_delivering_units_analytic_account(self):
        bill = self._closed_bill()
        move_line = bill.move_ids.invoice_line_ids[0]
        account = self.clinic.analytic_account_id
        self.assertTrue(account)
        self.assertIn(str(account.id), move_line.analytic_distribution or {})

    def test_lab_revenue_is_credited_to_the_lab(self):
        bill = self._closed_bill(tariff=self.lab_tariff)
        move_line = bill.move_ids.invoice_line_ids[0]
        self.assertIn(str(self.lab.analytic_account_id.id), move_line.analytic_distribution)


@tagged("post_install", "-at_install", "hms")
class TestMedicalFee(PnlCase):
    def test_closing_a_bill_accrues_the_doctor_fee(self):
        # A tariff-specific rule so the assertion does not depend on whatever
        # hospital-wide split happens to be configured.
        self.env["hms.medical.fee.rule"].create({
            "name": "Uji — penuh untuk tarif ini",
            "tariff_id": self.tariff.id, "percent": 100.0, "sequence": 1,
        })
        bill = self._closed_bill()
        fees = self.env["hms.medical.fee"].search([("bill_id", "=", bill.id)])
        self.assertEqual(len(fees), 1)
        self.assertAlmostEqual(fees.gross_amount, 60000)
        self.assertAlmostEqual(fees.amount, 60000)
        self.assertEqual(fees.state, "accrued")

    def test_a_rule_can_give_the_doctor_a_share(self):
        self.env["hms.medical.fee.rule"].create({
            "name": "Bagi hasil tindakan 70%",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "percent": 70.0,
        })
        bill = self._closed_bill()
        fee = self.env["hms.medical.fee"].search([("bill_id", "=", bill.id)])
        self.assertAlmostEqual(fee.amount, 42000)

    def test_the_more_specific_rule_wins(self):
        self.env["hms.medical.fee.rule"].create({
            "name": "Umum 50%",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "percent": 50.0,
        })
        self.env["hms.medical.fee.rule"].create({
            "name": "Dokter ini 80%",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "practitioner_id": self.doctor.id,
            "percent": 80.0,
        })
        bill = self._closed_bill()
        fee = self.env["hms.medical.fee"].search([("bill_id", "=", bill.id)])
        self.assertAlmostEqual(fee.amount, 48000)

    def test_lines_without_a_medical_component_accrue_nothing(self):
        bill = self._closed_bill(tariff=self.lab_tariff)
        self.assertFalse(self.env["hms.medical.fee"].search([("bill_id", "=", bill.id)]))

    def test_accrual_is_not_duplicated(self):
        bill = self._closed_bill()
        self.env["hms.medical.fee"].accrue_for_bill(bill)
        self.assertEqual(
            self.env["hms.medical.fee"].search_count([("bill_id", "=", bill.id)]), 1
        )

    def test_batch_collects_accrued_fees_for_a_period(self):
        bill = self._closed_bill()
        fee = self.env["hms.medical.fee"].search([("bill_id", "=", bill.id)])
        period = fields.Date.context_today(self.env["hms.unit"]).strftime("%Y-%m")
        batch = self.env["hms.medical.fee.batch"].build(period, self.doctor)
        self.assertIn(fee, batch.fee_ids)
        self.assertAlmostEqual(batch.total, sum(batch.fee_ids.mapped("amount")))
        self.assertEqual(fee.state, "batched")

    def test_building_an_empty_batch_is_refused(self):
        with self.assertRaises(UserError):
            self.env["hms.medical.fee.batch"].build("1999-01")


@tagged("post_install", "-at_install", "hms")
class TestAllocationAndPnl(PnlCase):
    def _run_allocation(self, driver="area", amount=10000000):
        period = fields.Date.context_today(self.env["hms.unit"]).strftime("%Y-%m")
        pool = self.env["hms.cost.pool"].create({"name": "Listrik", "driver": driver})
        run = self.env["hms.cost.allocation.run"].create({
            "name": "Alokasi Listrik",
            "period": period,
            "pool_ids": [(4, pool.id)],
            "amount_by_pool": json.dumps({"Listrik": amount}),
        })
        run.action_run()
        return run, period

    def test_area_driver_splits_in_proportion_to_floor_space(self):
        run, _period = self._run_allocation()
        by_unit = {
            line.account_id.code: line.amount for line in run.analytic_line_ids
        }
        # Other units in the database also have floor area, so the assertion
        # is about the RATIO between this test's two units, not their share of
        # the whole pool.
        self.assertAlmostEqual(
            by_unit[self.clinic.code] / by_unit[self.lab.code], 60 / 40, places=3
        )

    def test_allocation_is_negative_because_it_is_a_cost(self):
        run, _period = self._run_allocation()
        self.assertTrue(all(line.amount < 0 for line in run.analytic_line_ids))

    def test_rerunning_replaces_rather_than_accumulates(self):
        run, _period = self._run_allocation()
        first_total = sum(run.analytic_line_ids.mapped("amount"))
        run.action_run()
        second_total = sum(run.analytic_line_ids.mapped("amount"))
        self.assertAlmostEqual(first_total, second_total)

    def test_zero_driver_is_refused_rather_than_dividing_by_zero(self):
        # Every revenue unit must contribute nothing to the driver, not just
        # this test's two — the guard is about the pool total being zero.
        self.env["hms.unit"].search([("is_revenue_unit", "=", True)]).write({"area_m2": 0})
        period = fields.Date.context_today(self.env["hms.unit"]).strftime("%Y-%m")
        pool = self.env["hms.cost.pool"].create({"name": "Kosong", "driver": "area"})
        run = self.env["hms.cost.allocation.run"].create({
            "name": "Alokasi Kosong", "period": period, "pool_ids": [(4, pool.id)],
            "amount_by_pool": json.dumps({"Kosong": 1000}),
        })
        with self.assertRaises(UserError):
            run.action_run()

    def test_pnl_reports_revenue_and_margin_per_unit(self):
        self.env["hms.medical.fee.rule"].create({
            "name": "Uji — penuh untuk tarif ini",
            "tariff_id": self.tariff.id, "percent": 100.0, "sequence": 1,
        })
        self._closed_bill()
        period = fields.Date.context_today(self.env["hms.unit"]).strftime("%Y-%m")
        report = self.env["hms.unit.pnl"].compute(period, unit_ids=self.clinic.ids)
        row = report["units"][0]
        self.assertAlmostEqual(row["revenue_gross"], 200000)
        self.assertAlmostEqual(row["medical_fee"], 60000)
        self.assertAlmostEqual(row["cogs_consumable"], 20000)
        self.assertAlmostEqual(row["contribution_margin"], 120000)
        self.assertEqual(row["visits"], 1)

    def test_pnl_subtracts_allocated_overhead(self):
        self._closed_bill()
        run, period = self._run_allocation(amount=100000)
        report = self.env["hms.unit.pnl"].compute(period, unit_ids=self.clinic.ids)
        row = report["units"][0]
        self.assertLess(row["overhead_allocated"], 0)
        self.assertAlmostEqual(
            row["result"], row["contribution_margin"] + row["overhead_allocated"]
        )
