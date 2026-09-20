# -*- coding: utf-8 -*-
"""Shift control, closing reconciliation, estimates and receivables."""
import json

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def _fixed_part(estimate):
    """The one-off administration component, which does not scale with days."""
    basis = json.loads(estimate.basis)
    return sum(line["amount"] for line in basis["lines"] if line["qty"] == 1)


@tagged("post_install", "-at_install", "hms")
class CashierCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-KAS", "name": "Poli Kasir", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Dian Pratama", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101830011", "user_id": cls.env.user.id,
        })
        cls.cash_journal = cls.env["account.journal"].search([("type", "=", "cash")], limit=1)
        cls.bank_journal = cls.env["account.journal"].search([("type", "=", "bank")], limit=1)
        cls.counter = cls.env["hms.cashier.counter"].create({
            "code": "ZT-KAS-1", "name": "Kasir 1", "journal_cash_id": cls.cash_journal.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-TND-KAS", "name": "Tindakan Kasir",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": cls.clinic.id,
            "price_ids": [(0, 0, {"price_total": 100000})],
        })

    def _open_bill(self, amount_tariff=None):
        patient = self.env["hms.patient"].create({
            "name": "Pasien Kasir %s" % self.env["hms.patient"].search_count([]),
            "gender": "male", "birth_date": "1990-01-01",
            "nik": f"32017701010{self.env['hms.patient'].search_count([]) + 200:05d}",
        })
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "line_ids": [(0, 0, {"tariff_id": (amount_tariff or self.tariff).id})],
        })
        order.action_submit()
        order.line_ids.action_done()
        bill = self.env["hms.bill"].search([("encounter_id", "=", encounter.id)])
        bill.action_open()
        return bill


@tagged("post_install", "-at_install", "hms")
class TestShiftControl(CashierCase):
    def test_payment_without_an_open_shift_is_refused(self):
        """Once counters exist, every rupiah must belong to a shift."""
        bill = self._open_bill()
        with self.assertRaises(UserError):
            self.env["hms.payment"].create({
                "bill_id": bill.id, "method": "cash", "amount": 100000,
                "journal_id": self.cash_journal.id,
            })

    def test_payment_inside_a_shift_is_attached_to_it(self):
        session = self.env["hms.cashier.session"].create({
            "counter_id": self.counter.id, "opening_cash": 500000,
        })
        bill = self._open_bill()
        payment = self.env["hms.payment"].create({
            "bill_id": bill.id, "method": "cash", "amount": 100000,
            "journal_id": self.cash_journal.id,
        })
        self.assertEqual(payment.session_id, session)

    def test_one_open_shift_per_cashier_and_counter(self):
        self.env["hms.cashier.session"].create({
            "counter_id": self.counter.id, "opening_cash": 100000,
        })
        with self.assertRaises(Exception):
            self.env["hms.cashier.session"].create({
                "counter_id": self.counter.id, "opening_cash": 100000,
            })
            self.env.flush_all()

    def test_deposits_do_not_require_a_shift(self):
        """A deposit taken at registration never passes a cashier's drawer."""
        bill = self._open_bill()
        payment = self.env["hms.payment"].create({
            "bill_id": bill.id, "method": "deposit", "amount": 50000,
        })
        self.assertFalse(payment.session_id)


@tagged("post_install", "-at_install", "hms")
class TestClosing(CashierCase):
    def setUp(self):
        super().setUp()
        self.session = self.env["hms.cashier.session"].create({
            "counter_id": self.counter.id, "opening_cash": 200000,
        })

    def _pay(self, method, amount, tendered=None):
        bill = self._open_bill()
        return self.env["hms.payment"].create({
            "bill_id": bill.id, "method": method, "amount": amount,
            "tendered": tendered or amount,
            "journal_id": (self.cash_journal if method == "cash" else self.bank_journal).id,
        })

    def test_closing_builds_one_row_per_method_used(self):
        self._pay("cash", 100000)
        self._pay("edc_debit", 100000)
        self.session.action_start_closing()
        methods = set(self.session.line_ids.mapped("method"))
        self.assertEqual(methods, {"cash", "edc_debit"})

    def test_expected_cash_includes_the_opening_float(self):
        self._pay("cash", 100000)
        self.session.action_start_closing()
        cash_line = self.session.line_ids.filtered(lambda l: l.method == "cash")
        self.assertAlmostEqual(cash_line.expected_amount, 300000)

    def test_change_given_is_deducted_from_expected_cash(self):
        self._pay("cash", 100000, tendered=150000)
        self.session.action_start_closing()
        cash_line = self.session.line_ids.filtered(lambda l: l.method == "cash")
        self.assertAlmostEqual(cash_line.expected_amount, 250000)

    def test_unexplained_difference_blocks_closing(self):
        self._pay("cash", 100000)
        self.session.action_start_closing()
        self.session.line_ids.filtered(lambda l: l.method == "cash").counted_amount = 290000
        with self.assertRaises(UserError):
            self.session.action_close()

    def test_explained_difference_closes(self):
        self._pay("cash", 100000)
        self.session.action_start_closing()
        line = self.session.line_ids.filtered(lambda l: l.method == "cash")
        line.write({"counted_amount": 290000, "note": "Kembalian kurang Rp10.000"})
        self.session.action_close()
        self.assertEqual(self.session.state, "closed")
        self.assertAlmostEqual(self.session.difference, -10000)

    def test_matching_count_closes_cleanly(self):
        self._pay("cash", 100000)
        self.session.action_start_closing()
        for line in self.session.line_ids:
            line.counted_amount = line.expected_amount
        self.session.action_close()
        self.assertAlmostEqual(self.session.difference, 0.0)

    def test_closing_cannot_start_twice(self):
        self.session.action_start_closing()
        with self.assertRaises(UserError):
            self.session.action_start_closing()

    def test_summary_breaks_down_by_method_and_payer(self):
        self._pay("cash", 100000)
        self.session.action_start_closing()
        summary = self.session.closing_summary()
        self.assertEqual(summary["transaction_count"], 1)
        self.assertTrue(summary["by_method"])
        self.assertTrue(summary["by_payer"])


@tagged("post_install", "-at_install", "hms")
class TestEstimateAndReceivable(CashierCase):
    def test_estimate_scales_with_the_length_of_stay(self):
        """Doubling the stay doubles the per-day part of the estimate.

        Asserted as a relationship rather than an absolute figure: which
        accommodation tariff applies depends on what the hospital has
        configured, and pinning a number here would test the fixture instead
        of the arithmetic.
        """
        care_class = self.env.ref("custom_hms_base.care_class_2")
        patient = self.env["hms.patient"].create({
            "name": "Estimasi Test", "gender": "female", "birth_date": "1980-01-01",
            "nik": "3201014501800099",
        })
        two_days = self.env["hms.bill.estimate"].estimate(patient, care_class, expected_los=2)
        four_days = self.env["hms.bill.estimate"].estimate(patient, care_class, expected_los=4)
        self.assertGreater(two_days.estimate_amount, 0)
        daily = four_days.estimate_amount - two_days.estimate_amount
        self.assertAlmostEqual(daily, two_days.estimate_amount - _fixed_part(two_days), delta=1)


    def test_estimate_states_what_it_excludes(self):
        care_class = self.env.ref("custom_hms_base.care_class_3")
        patient = self.env["hms.patient"].create({
            "name": "Estimasi Test 2", "gender": "male", "birth_date": "1980-01-01",
            "nik": "3201010101800098",
        })
        estimate = self.env["hms.bill.estimate"].estimate(patient, care_class)
        self.assertIn("Obat", estimate.basis)
        self.assertIn("tidak termasuk", estimate.basis)

    def test_receivable_requires_supervisor_approval(self):
        bill = self._open_bill()
        with self.assertRaises(UserError):
            self.env["hms.patient.receivable"].create_from_bill(bill, 50000)

    def test_supervisor_can_record_a_receivable(self):
        bill = self._open_bill()
        self.env.user.group_ids = [
            (4, self.env.ref("custom_hms_base.group_hms_billing_supervisor").id)
        ]
        receivable = self.env["hms.patient.receivable"].create_from_bill(
            bill, 50000, note="Pasien pulang, sisa dicicil"
        )
        self.assertEqual(receivable.amount, 50000)
        self.assertEqual(receivable.balance, 50000)
        self.assertAlmostEqual(bill.amount_due, 50000)

    def test_receivable_cannot_exceed_the_outstanding_amount(self):
        bill = self._open_bill()
        self.env.user.group_ids = [
            (4, self.env.ref("custom_hms_base.group_hms_billing_supervisor").id)
        ]
        with self.assertRaises(UserError):
            self.env["hms.patient.receivable"].create_from_bill(bill, 999999)
