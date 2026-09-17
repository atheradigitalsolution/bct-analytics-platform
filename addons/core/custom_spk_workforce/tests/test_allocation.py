# -*- coding: utf-8 -*-
"""The monthly run, and the two refusals that keep it honest."""

from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import WorkforceCommon


@tagged("post_install", "-at_install")
class TestLaborAllocation(WorkforceCommon):

    def _approved_shift(self, employee, spk, date, portion=1.0, shift=None):
        att = self._attendance(employee, shift=shift, date=date)
        self.WorkLog.create({
            "attendance_id": att.id, "spk_id": spk.id, "shift_portion": portion,
        })
        att.action_approve()
        return att

    def _payslip(self, employee, gross, month="6", year=2026):
        slip = self.env["hr.payslip"].create({
            "employee_id": employee.id,
            "period_year": year,
            "period_month": month,
            "gross_salary": gross,
        })
        slip.action_compute()
        slip.action_approve()
        return slip

    def _allocation(self, month="6", year=2026):
        return self.Allocation.create({"period_year": year, "period_month": month})

    # ---------- the arithmetic ----------

    def test_allocation_divides_payroll_by_shifts_actually_worked(self):
        """The whole point of the shift-count basis.

        Two jobs, six permanent shifts between them in a 4:2 split, and one month of
        salary. The job that got two thirds of the effort carries two thirds of the
        cost -- which a flat spread over direct cost would not produce.
        """
        spk_a, spk_b = self._spk("A"), self._spk("B")
        for day in (1, 2, 3, 4):
            self._approved_shift(self.permanent_direct, spk_a, "2026-06-%02d" % day)
        for day in (5, 8):
            self._approved_shift(self.permanent_direct, spk_b, "2026-06-%02d" % day)
        self._payslip(self.permanent_direct, 12_000_000.0)

        alloc = self._allocation()
        alloc.action_compute()

        self.assertEqual(alloc.state, "computed")
        self.assertAlmostEqual(alloc.total_shifts, 6.0, places=3)
        self.assertAlmostEqual(alloc.payroll_total, 12_000_000.0, places=2)
        self.assertAlmostEqual(alloc.rate_per_shift, 2_000_000.0, places=2)

        by_spk = {l.spk_id: l.amount for l in alloc.line_ids}
        self.assertAlmostEqual(by_spk[spk_a], 8_000_000.0, places=2)
        self.assertAlmostEqual(by_spk[spk_b], 4_000_000.0, places=2)
        self.assertAlmostEqual(sum(by_spk.values()), 12_000_000.0, places=2,
                               msg="the whole salary reaches COGS, not part of it")

    def test_indirect_shifts_do_not_dilute_the_rate(self):
        """A mandor's shifts are overhead, so they must not enter the divisor.

        If they did, the rate per shift would fall and every job would be charged
        less than the direct labour it actually consumed.
        """
        spk = self._spk()
        self._approved_shift(self.permanent_direct, spk, "2026-06-01")
        self._approved_shift(self.permanent_direct, spk, "2026-06-02")
        self._approved_shift(self.permanent_indirect, spk, "2026-06-03")
        self._payslip(self.permanent_direct, 10_000_000.0)

        alloc = self._allocation()
        alloc.action_compute()
        self.assertAlmostEqual(alloc.total_shifts, 2.0, places=3)
        self.assertAlmostEqual(alloc.rate_per_shift, 5_000_000.0, places=2)

    def test_daily_shifts_are_not_allocated_twice(self):
        """Their cost already reached the job the day it was logged."""
        spk = self._spk()
        self._approved_shift(self.daily, spk, "2026-06-01")
        self._approved_shift(self.permanent_direct, spk, "2026-06-02")
        self._payslip(self.permanent_direct, 5_000_000.0)

        alloc = self._allocation()
        alloc.action_compute()
        self.assertAlmostEqual(alloc.total_shifts, 1.0, places=3,
                               msg="only the permanent shift is an allocation basis")

    def test_partial_shifts_split_the_allocation(self):
        spk_a, spk_b = self._spk("A"), self._spk("B")
        att = self._attendance(self.permanent_direct, date="2026-06-01")
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk_a.id, "shift_portion": 0.75})
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk_b.id, "shift_portion": 0.25})
        att.action_approve()
        self._payslip(self.permanent_direct, 4_000_000.0)

        alloc = self._allocation()
        alloc.action_compute()
        by_spk = {l.spk_id: l.amount for l in alloc.line_ids}
        self.assertAlmostEqual(by_spk[spk_a], 3_000_000.0, places=2)
        self.assertAlmostEqual(by_spk[spk_b], 1_000_000.0, places=2)

    # ---------- the refusals ----------

    def test_no_shifts_refuses_rather_than_dividing_by_zero(self):
        self._payslip(self.permanent_direct, 8_000_000.0)
        with self.assertRaises(UserError):
            self._allocation().action_compute()

    def test_shifts_without_payroll_refuses_rather_than_allocating_zero(self):
        """Allocating zero would silently declare that month's jobs free of labour."""
        spk = self._spk()
        self._approved_shift(self.permanent_direct, spk, "2026-06-01")
        with self.assertRaises(UserError):
            self._allocation().action_compute()

    def test_unapproved_attendance_is_not_a_basis(self):
        """Half-entered attendance must not set the rate for the whole month."""
        spk = self._spk()
        att = self._attendance(self.permanent_direct, date="2026-06-01")
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id})
        # deliberately not approved
        self._payslip(self.permanent_direct, 6_000_000.0)
        with self.assertRaises(UserError):
            self._allocation().action_compute()

    # ---------- posting ----------

    def test_posting_writes_one_analytic_line_per_spk(self):
        spk_a, spk_b = self._spk("A"), self._spk("B")
        self._approved_shift(self.permanent_direct, spk_a, "2026-06-01")
        self._approved_shift(self.permanent_direct, spk_b, "2026-06-02")
        self._payslip(self.permanent_direct, 4_000_000.0)

        alloc = self._allocation()
        alloc.action_compute()
        alloc.action_post()

        self.assertEqual(alloc.state, "posted")
        Line = self.env["account.analytic.line"]
        for spk, expected in ((spk_a, 2_000_000.0), (spk_b, 2_000_000.0)):
            lines = Line.search([("account_id", "=", spk.analytic_account_id.id)])
            self.assertTrue(lines, "%s received no allocation line" % spk.name)
            self.assertAlmostEqual(sum(lines.mapped("amount")), -expected, places=2,
                                   msg="cost is booked negative on the analytic account")

    def test_posting_before_computing_is_refused(self):
        with self.assertRaises(UserError):
            self._allocation().action_post()

    def test_one_allocation_per_period(self):
        from psycopg2 import IntegrityError
        self._allocation()
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._allocation()
