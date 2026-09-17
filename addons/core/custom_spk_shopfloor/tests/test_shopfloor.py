# -*- coding: utf-8 -*-
"""The round, and the gate it must not offer a way around."""

from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestShopfloorRound(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Round = cls.env["custom.spk.shopfloor.round"]
        cls.Attendance = cls.env["custom.spk.attendance"]
        cls.WorkLog = cls.env["custom.spk.work.log"]
        cls.shift = cls.env.ref("custom_spk.shift_1")
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})
        cls.daily = cls.env["hr.employee"].create({
            "name": "Tukang Harian",
            "x_custom_employment_type": "pegawai_tidak_tetap",
            "x_spk_labor_category": "direct",
            "x_spk_shift_rate": 180_000.0,
        })
        cls.permanent = cls.env["hr.employee"].create({
            "name": "Tukang Tetap",
            "x_custom_employment_type": "pegawai_tetap",
            "x_spk_labor_category": "direct",
        })

    def _spk(self):
        spk = self.env["custom.spk"].create(
            {"partner_id": self.partner.id, "event_name": "GIIAS"})
        spk.action_confirm()
        return spk

    def _round(self, date="2026-06-01"):
        return self.Round.get_or_open(date, self.shift.id)

    def _attend(self, rnd, employee):
        return self.Attendance.create({
            "employee_id": employee.id, "date": rnd.date,
            "shift_id": rnd.shift_id.id, "shopfloor_round_id": rnd.id,
        })

    # ---------- the round is idempotent ----------

    def test_reopening_returns_the_same_round(self):
        """A device retrying after a dropped connection must not split the walk in two."""
        first = self._round()
        second = self._round()
        self.assertEqual(first, second)

    def test_a_different_shift_gets_its_own_round(self):
        night = self.env.ref("custom_spk.shift_3")
        day_round = self._round()
        night_round = self.Round.get_or_open(day_round.date, night.id)
        self.assertNotEqual(day_round, night_round)

    def test_one_round_per_supervisor_per_shift_per_day(self):
        from psycopg2 import IntegrityError
        rnd = self._round()
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Round.create({
                    "date": rnd.date, "shift_id": rnd.shift_id.id,
                    "supervisor_id": rnd.supervisor_id.id,
                })

    # ---------- the number the supervisor has to clear ----------

    def test_unmapped_counts_only_paid_shifts(self):
        """A permanent worker's unmapped shift is not money already out the door."""
        rnd = self._round()
        self._attend(rnd, self.daily)
        self._attend(rnd, self.permanent)
        self.assertEqual(rnd.attendance_count, 2)
        self.assertEqual(rnd.unmapped_count, 1)

    def test_mapping_a_shift_clears_it(self):
        rnd = self._round()
        att = self._attend(rnd, self.daily)
        self.WorkLog.create({
            "attendance_id": att.id, "spk_id": self._spk().id, "shift_portion": 1.0})
        self.assertEqual(rnd.unmapped_count, 0)

    def test_a_partial_split_is_still_unmapped(self):
        """Half a shift accounted for is half a shift of wage with nowhere to land."""
        rnd = self._round()
        att = self._attend(rnd, self.daily)
        self.WorkLog.create({
            "attendance_id": att.id, "spk_id": self._spk().id, "shift_portion": 0.5})
        self.assertEqual(rnd.unmapped_count, 1)

    # ---------- the round must not become a way around the gate ----------

    def test_approving_a_round_with_unmapped_paid_shifts_is_refused(self):
        """A faster button that skips the control would defeat the control."""
        rnd = self._round()
        self._attend(rnd, self.daily)
        rnd.action_submit_round()
        with self.assertRaises(UserError):
            rnd.action_approve_round()

    def test_a_fully_mapped_round_approves_every_attendance(self):
        rnd = self._round()
        att = self._attend(rnd, self.daily)
        self.WorkLog.create({
            "attendance_id": att.id, "spk_id": self._spk().id, "shift_portion": 1.0})
        rnd.action_submit_round()
        rnd.action_approve_round()
        self.assertEqual(rnd.state, "approved")
        self.assertEqual(att.state, "approved")

    def test_an_empty_round_cannot_be_submitted(self):
        rnd = self._round()
        with self.assertRaises(UserError):
            rnd.action_submit_round()

    def test_back_office_attendance_needs_no_round(self):
        """Typed straight into the back office, and that is fine."""
        att = self.Attendance.create({
            "employee_id": self.permanent.id, "date": "2026-06-02",
            "shift_id": self.shift.id,
        })
        self.assertFalse(att.shopfloor_round_id)
        att.action_approve()
        self.assertEqual(att.state, "approved")
