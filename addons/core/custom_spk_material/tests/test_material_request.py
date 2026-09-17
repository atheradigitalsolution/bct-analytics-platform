# -*- coding: utf-8 -*-
"""Approval, and the escalation that keeps material overrun visible."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import MaterialCommon


@tagged("post_install", "-at_install")
class TestMaterialRequest(MaterialCommon):

    def test_a_request_within_estimate_does_not_escalate(self):
        spk = self._spk()
        self._estimate(spk, self.sheet, 15.0)
        req = self._request(spk, self.sheet, 10.0)
        self.assertFalse(req.over_estimate)

    def test_a_request_past_the_estimate_is_flagged(self):
        spk = self._spk()
        self._estimate(spk, self.sheet, 15.0)
        req = self._request(spk, self.sheet, 20.0)
        self.assertTrue(req.over_estimate)

    def test_cumulative_take_is_what_counts_not_this_request_alone(self):
        """Overrun arrives one sheet at a time; each request on its own looks fine."""
        spk = self._spk()
        self._estimate(spk, self.sheet, 15.0)

        first = self._request(spk, self.sheet, 10.0)
        first.action_submit()
        first.action_approve()
        first.action_issue()

        second = self._request(spk, self.sheet, 8.0)
        self.assertAlmostEqual(second.line_ids.qty_taken_before, 10.0, places=3)
        self.assertTrue(second.over_estimate, "10 + 8 is past an estimate of 15")

    def test_over_estimate_needs_a_reason_before_approval(self):
        spk = self._spk()
        self._estimate(spk, self.sheet, 5.0)
        req = self._request(spk, self.sheet, 20.0)
        req.action_submit()
        with self.assertRaises(UserError):
            req.action_approve()

    def test_over_estimate_with_a_reason_approves_for_a_pm(self):
        spk = self._spk()
        self._estimate(spk, self.sheet, 5.0)
        req = self._request(spk, self.sheet, 20.0)
        req.escalation_reason = "Panel dipotong ulang karena revisi design D3."
        req.action_submit()
        self.env.user.group_ids |= self.env.ref("custom_spk.group_spk_pm")
        req.action_approve()
        self.assertEqual(req.state, "approved")

    def test_approval_fills_approved_quantity_from_requested(self):
        spk = self._spk()
        req = self._request(spk, self.sheet, 7.0)
        req.action_submit()
        req.action_approve()
        self.assertAlmostEqual(req.line_ids.qty_approved, 7.0, places=3)

    def test_cannot_approve_more_than_was_asked(self):
        spk = self._spk()
        req = self._request(spk, self.sheet, 5.0)
        with self.assertRaises(ValidationError):
            req.line_ids.qty_approved = 9.0

    def test_an_empty_request_cannot_be_submitted(self):
        spk = self._spk()
        req = self.MR.create({"spk_id": spk.id, "requested_by": self.worker.id})
        with self.assertRaises(UserError):
            req.action_submit()

    def test_issuing_before_approval_is_refused(self):
        spk = self._spk()
        req = self._request(spk, self.sheet, 3.0)
        with self.assertRaises(UserError):
            req.action_issue()

    def test_issue_moves_goods_and_carries_the_analytic_account(self):
        """One mechanism books material cost, so there is no second number to reconcile."""
        spk = self._spk()
        req = self._request(spk, self.sheet, 4.0)
        req.action_submit()
        req.action_approve()
        req.action_issue()

        self.assertEqual(req.state, "issued")
        self.assertTrue(req.picking_id)
        move = req.picking_id.move_ids
        self.assertEqual(len(move), 1)
        self.assertAlmostEqual(move.product_uom_qty, 4.0, places=3)
        self.assertIn(str(spk.analytic_account_id.id), move.analytic_distribution or {})

    def test_request_cost_uses_product_cost(self):
        spk = self._spk()
        req = self._request(spk, self.sheet, 3.0)
        self.assertAlmostEqual(req.total_cost, 3.0 * 185_000.0, places=2)
