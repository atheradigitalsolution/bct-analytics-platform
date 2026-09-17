# -*- coding: utf-8 -*-
"""The record itself: numbering, the dependants it issues, risk, and who sees it."""

from __future__ import annotations

from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SpkCommon


@tagged("post_install", "-at_install")
class TestSpk(SpkCommon):

    def _spk(self, days_out=30, progress=0.0, user=None, **kw):
        vals = {
            "partner_id": self.partner.id,
            "event_name": "GIIAS",
            "event_date_start": fields.Date.context_today(self.Spk) + timedelta(days=days_out),
            "progress": progress,
            **kw,
        }
        if user is not None:
            vals["user_id"] = user.id
        return self.Spk.create(vals)

    # ---------- numbering ----------

    def test_number_comes_from_the_sequence(self):
        spk = self._spk()
        self.assertRegex(spk.name, r"^SPK/\d{4}/\d{4}$")

    def test_numbers_do_not_repeat(self):
        first, second = self._spk(), self._spk()
        self.assertNotEqual(first.name, second.name)

    # ---------- what approval issues ----------

    def test_confirm_issues_project_and_analytic_account(self):
        """Both exist from approval, not from whoever needs one first.

        If the analytic account arrives late, the costs booked before it have
        nowhere to land, and job costing is wrong in a way nobody notices.
        """
        spk = self._spk()
        self.assertFalse(spk.project_id)
        self.assertFalse(spk.analytic_account_id)

        spk.action_confirm()

        self.assertEqual(spk.state, "confirmed")
        self.assertTrue(spk.project_id, "a confirmed SPK has a project")
        self.assertTrue(spk.analytic_account_id, "a confirmed SPK has somewhere for cost to land")
        self.assertEqual(spk.analytic_account_id.name, spk.name,
                         "the analytic account is findable by SPK number")

    def test_confirm_is_idempotent_about_its_dependants(self):
        spk = self._spk()
        spk.action_confirm()
        project, analytic = spk.project_id, spk.analytic_account_id
        spk.state = "design"
        with self.assertRaises(UserError):
            spk.action_confirm()
        self.assertEqual(spk.project_id, project)
        self.assertEqual(spk.analytic_account_id, analytic)

    # ---------- risk ----------

    def test_risk_is_late_when_deadline_is_close_and_work_is_not(self):
        spk = self._spk(days_out=5, progress=40.0)
        self.assertEqual(spk.risk_level, "late")
        self.assertEqual(spk.days_to_event, 5)

    def test_risk_is_ok_when_work_has_kept_up(self):
        self.assertEqual(self._spk(days_out=5, progress=95.0).risk_level, "ok")

    def test_risk_watch_is_the_earlier_warning(self):
        self.assertEqual(self._spk(days_out=10, progress=20.0).risk_level, "watch")

    def test_a_handed_over_job_is_not_at_risk(self):
        """The event may be tomorrow; the booth is already standing."""
        spk = self._spk(days_out=1, progress=10.0, state="handover")
        self.assertEqual(spk.risk_level, "ok")

    def test_risk_without_an_event_date_does_not_guess(self):
        spk = self.Spk.create({"partner_id": self.partner.id})
        self.assertEqual(spk.risk_level, "ok")
        self.assertEqual(spk.days_to_event, 0)

    # ---------- who sees which record ----------

    def test_ae_sees_only_their_own_spk(self):
        mine = self._spk(user=self.ae)
        theirs = self._spk(user=self.ae_other)
        visible = self.Spk.with_user(self.ae).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible, "an AE must not see another AE's client")

    def test_pm_sees_every_spk(self):
        a = self._spk(user=self.ae)
        b = self._spk(user=self.ae_other)
        visible = self.Spk.with_user(self.pm).search([])
        self.assertIn(a, visible)
        self.assertIn(b, visible)

    # ---------- shift master ----------

    def test_night_shift_crossing_midnight_is_derived(self):
        self.assertTrue(self.env.ref("custom_spk.shift_3").crosses_midnight)
        self.assertFalse(self.env.ref("custom_spk.shift_1").crosses_midnight)

    def test_seeded_shift_premiums(self):
        self.assertAlmostEqual(self.env.ref("custom_spk.shift_1").rate_multiplier, 1.0, places=4)
        self.assertAlmostEqual(self.env.ref("custom_spk.shift_2").rate_multiplier, 1.1, places=4)
        self.assertAlmostEqual(self.env.ref("custom_spk.shift_3").rate_multiplier, 1.3, places=4)

    def test_a_shift_that_pays_nothing_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.Shift.create({
                "name": "Gratis", "code": "S0",
                "time_start": 7.0, "time_stop": 15.0, "rate_multiplier": 0.0,
            })

    def test_shift_hours_must_fall_within_a_day(self):
        with self.assertRaises(ValidationError):
            self.Shift.create({
                "name": "Salah", "code": "SX",
                "time_start": 7.0, "time_stop": 26.0, "rate_multiplier": 1.0,
            })
