# -*- coding: utf-8 -*-
"""Billing shapes, milestones that must add up, and the down-payment gate."""

from __future__ import annotations

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import BillingCommon


@tagged("post_install", "-at_install")
class TestBillingPlan(BillingCommon):

    def test_three_shapes_are_available_per_job(self):
        """The same contractor bills all three ways in the same month."""
        for mode in ("single", "per_delivery"):
            plan = self._plan(mode=mode)
            self.assertEqual(plan.mode, mode)
        milestone_plan = self._plan(mode="milestone")
        self._standard_terms(milestone_plan)
        self.assertEqual(milestone_plan.mode, "milestone")

    def test_one_plan_per_job(self):
        from psycopg2 import IntegrityError
        spk = self._spk()
        self._plan(spk)
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._plan(spk)

    # ---------- milestones must add up ----------

    def test_milestones_totalling_less_than_one_hundred_are_refused(self):
        """A plan that does not add up leaves money uninvoiced."""
        plan = self._plan(mode="milestone")
        self.Milestone.create({"plan_id": plan.id, "name": "DP", "percentage": 50.0})
        with self.assertRaises(ValidationError):
            plan.action_activate()

    def test_milestones_totalling_more_than_one_hundred_are_refused(self):
        plan = self._plan(mode="milestone")
        self.Milestone.create({"plan_id": plan.id, "name": "DP", "percentage": 60.0})
        self.Milestone.create({"plan_id": plan.id, "name": "Sisa", "percentage": 60.0})
        with self.assertRaises(ValidationError):
            plan.action_activate()

    def test_standard_terms_add_up_and_price_out(self):
        plan = self._standard_terms(self._plan(mode="milestone", amount=44_000_000.0))
        self.assertAlmostEqual(plan.milestone_total_pct, 100.0, places=2)
        by_name = {m.name: m.amount for m in plan.milestone_ids}
        self.assertAlmostEqual(by_name["DP"], 22_000_000.0, places=2)
        self.assertAlmostEqual(by_name["Setelah BAST"], 17_600_000.0, places=2)
        self.assertAlmostEqual(by_name["Retensi"], 4_400_000.0, places=2)

    def test_a_milestone_outside_zero_to_one_hundred_is_refused(self):
        plan = self._plan(mode="milestone")
        for bad in (0.0, -10.0, 120.0):
            with self.assertRaises(ValidationError):
                self.Milestone.create({
                    "plan_id": plan.id, "name": "x", "percentage": bad})

    def test_a_draft_milestone_plan_may_be_incomplete(self):
        """The plan has to exist before milestones can point at it."""
        plan = self._plan(mode="milestone")
        self.assertEqual(plan.state, "draft")
        self.Milestone.create({"plan_id": plan.id, "name": "DP", "percentage": 50.0})
        self.assertAlmostEqual(plan.milestone_total_pct, 50.0, places=2)

    def test_a_milestone_plan_with_no_milestones_is_refused(self):
        plan = self._plan(mode="milestone")
        with self.assertRaises(ValidationError):
            plan.action_activate()

    # ---------- the down payment gate ----------

    def test_production_is_held_until_the_down_payment_arrives(self):
        """Buying material before any money lands means financing the client's event."""
        plan = self._standard_terms(self._plan(mode="milestone"))
        allowed, reason = plan.can_release_to_workshop()
        self.assertFalse(allowed)
        self.assertIn(plan.spk_id.name, reason)

    def test_the_gate_can_be_waived_per_job(self):
        """Sometimes the relationship earns it, and that is the owner's call."""
        plan = self._standard_terms(self._plan(mode="milestone"))
        plan.block_production_until_dp = False
        allowed, reason = plan.can_release_to_workshop()
        self.assertTrue(allowed)
        self.assertFalse(reason)

    def test_a_plan_without_a_down_payment_does_not_hold_production(self):
        plan = self._plan(mode="single")
        allowed, _reason = plan.can_release_to_workshop()
        self.assertTrue(allowed)

    def test_a_paid_down_payment_releases_production(self):
        plan = self._standard_terms(self._plan(mode="milestone"))
        dp = plan.milestone_ids.filtered(lambda m: m.is_down_payment)
        invoice = self.Move.create({
            "move_type": "out_invoice", "partner_id": self.partner.id,
            "invoice_line_ids": [(0, 0, {"name": "DP", "quantity": 1, "price_unit": 100.0})],
        })
        dp.invoice_id = invoice
        self.assertFalse(dp.is_paid, "a draft invoice is not a payment")
        allowed, _r = plan.can_release_to_workshop()
        self.assertFalse(allowed)
