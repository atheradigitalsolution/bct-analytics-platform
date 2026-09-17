# -*- coding: utf-8 -*-
"""The two layers, and the gate between them."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import WorkforceCommon


@tagged("post_install", "-at_install")
class TestWorkLog(WorkforceCommon):

    # ---------- classification is not duplicated ----------

    def test_daily_flag_comes_from_the_payroll_field(self):
        """One source of truth, so costing and PPh 21 cannot disagree."""
        self.assertTrue(self.daily.x_spk_is_daily)
        self.assertFalse(self.permanent_direct.x_spk_is_daily)
        self.daily.x_custom_employment_type = "pegawai_tetap"
        self.assertFalse(self.daily.x_spk_is_daily, "the derived flag follows payroll")

    def test_a_daily_worker_without_a_rate_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hr.employee"].create({
                "name": "Helper", "x_custom_employment_type": "pegawai_tidak_tetap",
                "x_spk_labor_category": "direct", "x_spk_shift_rate": 0.0,
            })

    # ---------- cost belongs to the daily worker only ----------

    def test_daily_shift_costs_rate_times_multiplier(self):
        att = self._attendance(self.daily, shift=self.shift3)  # 1.3
        self.assertAlmostEqual(att.shift_cost, 180000.0 * 1.3, places=2)

    def test_permanent_shift_carries_no_money(self):
        att = self._attendance(self.permanent_direct)
        self.assertAlmostEqual(att.shift_cost, 0.0, places=2)

    def test_absent_shift_costs_nothing_even_for_a_daily_worker(self):
        att = self._attendance(self.daily, status="sakit")
        self.assertAlmostEqual(att.shift_cost, 0.0, places=2)

    def test_work_log_cost_follows_the_portion(self):
        spk_a, spk_b = self._spk("A"), self._spk("B")
        att = self._attendance(self.daily)
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk_a.id, "shift_portion": 0.75})
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk_b.id, "shift_portion": 0.25})
        by_spk = {l.spk_id: l.labor_cost for l in att.work_log_ids}
        self.assertAlmostEqual(by_spk[spk_a], 180000.0 * 0.75, places=2)
        self.assertAlmostEqual(by_spk[spk_b], 180000.0 * 0.25, places=2)
        self.assertAlmostEqual(sum(by_spk.values()), att.shift_cost, places=2)

    def test_permanent_direct_log_is_allocation_basis_not_cost(self):
        spk = self._spk()
        att = self._attendance(self.permanent_direct)
        log = self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id})
        self.assertAlmostEqual(log.labor_cost, 0.0, places=2)
        self.assertTrue(log.is_allocation_basis, "this shift drives the monthly allocation")

    def test_permanent_indirect_is_never_allocated(self):
        """A supervisor's cost is overhead however many workshops they walked."""
        spk = self._spk()
        att = self._attendance(self.permanent_indirect)
        log = self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id})
        self.assertFalse(log.is_allocation_basis)

    # ---------- the analytic target ----------

    def test_spk_log_resolves_to_the_spk_analytic_account(self):
        spk = self._spk()
        att = self._attendance(self.daily)
        log = self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id})
        self.assertEqual(log.analytic_account_id, spk.analytic_account_id)

    def test_idle_shift_does_not_land_on_a_job(self):
        """Present, paid, nothing to build. Charging a job for that is the distortion."""
        att = self._attendance(self.daily)
        log = self.WorkLog.create({"attendance_id": att.id, "target": "idle"})
        self.assertEqual(log.analytic_account_id, self.idle_account)
        self.assertAlmostEqual(log.labor_cost, 180000.0, places=2)

    def test_spk_target_without_an_spk_is_refused(self):
        att = self._attendance(self.daily)
        with self.assertRaises(ValidationError):
            self.WorkLog.create({"attendance_id": att.id, "target": "spk"})

    def test_unconfirmed_spk_has_nowhere_for_cost_to_land(self):
        spk = self.env["custom.spk"].create({"partner_id": self.partner.id})
        att = self._attendance(self.daily)
        with self.assertRaises(ValidationError):
            self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id})

    def test_portion_bounds(self):
        spk = self._spk()
        att = self._attendance(self.daily)
        for bad in (0.0, -0.5, 1.5):
            with self.assertRaises(ValidationError):
                self.WorkLog.create({
                    "attendance_id": att.id, "spk_id": spk.id, "shift_portion": bad,
                })

    # ---------- the approval gate ----------

    def test_daily_shift_cannot_be_approved_unmapped(self):
        """The money left this week. It has to land somewhere."""
        att = self._attendance(self.daily)
        with self.assertRaises(UserError):
            att.action_approve()

    def test_permanent_shift_may_be_approved_unmapped(self):
        """Their pay does not depend on it, so the gate would only teach people to lie."""
        att = self._attendance(self.permanent_direct)
        att.action_approve()
        self.assertEqual(att.state, "approved")

    def test_portions_must_make_a_whole_shift(self):
        spk = self._spk()
        att = self._attendance(self.daily)
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id, "shift_portion": 0.5})
        with self.assertRaises(UserError):
            att.action_approve()

    def test_a_mapped_whole_shift_approves(self):
        spk = self._spk()
        att = self._attendance(self.daily)
        self.WorkLog.create({"attendance_id": att.id, "spk_id": spk.id, "shift_portion": 1.0})
        att.action_approve()
        self.assertEqual(att.state, "approved")

    def test_absent_shift_needs_no_mapping(self):
        att = self._attendance(self.daily, status="alpha")
        att.action_approve()
        self.assertEqual(att.state, "approved")

    def test_one_attendance_per_person_per_shift_per_day(self):
        from psycopg2 import IntegrityError
        self._attendance(self.daily)
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._attendance(self.daily)

    # ---------- the reminder ----------

    def test_cron_flags_paid_shifts_that_went_nowhere(self):
        self._attendance(self.daily)
        self._attendance(self.permanent_direct)
        flagged = self.Attendance._cron_warn_unmapped()
        self.assertEqual(flagged, 1, "only the daily worker's shift is money already spent")
