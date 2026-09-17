# -*- coding: utf-8 -*-
"""Estimate versus actual, and the sign convention that makes it readable."""

from __future__ import annotations

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCostSummary(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Summary = cls.env["custom.spk.cost.summary"]
        cls.Est = cls.env["custom.spk.estimation"]
        cls.EstLine = cls.env["custom.spk.estimation.line"]
        cls.Analytic = cls.env["account.analytic.line"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})
        cls.product = cls.env["product.product"].create(
            {"name": "Multiplek", "standard_price": 185_000.0})

    def _spk(self, event="GIIAS"):
        spk = self.env["custom.spk"].create(
            {"partner_id": self.partner.id, "event_name": event})
        spk.action_confirm()
        return spk

    def _estimate(self, spk, material=0.0, labor=0.0, waste=0.0, margin=30.0):
        est = self.Est.create({"spk_id": spk.id, "target_margin": margin,
                               "overhead_rate": 0.0, "risk_rate": 0.0})
        if material:
            self.EstLine.create({
                "estimation_id": est.id, "category": "material", "name": "m",
                "quantity": 1.0, "unit_cost": material, "waste_pct": waste,
            })
        if labor:
            self.EstLine.create({
                "estimation_id": est.id, "category": "labor", "name": "l",
                "quantity": 1.0, "unit_cost": labor,
            })
        est.action_approve()
        return est

    def _cost(self, spk, amount, category="material", product=None):
        """Book a cost. Analytic holds cost negative, which is what the report flips."""
        return self.Analytic.create({
            "name": "biaya",
            "account_id": spk.analytic_account_id.id,
            "amount": -abs(amount),
            "x_spk_cost_category": category,
            **({"product_id": product.id} if product else {}),
        })

    def _summary(self, spk):
        summary = self.Summary.create({"spk_id": spk.id})
        summary.action_refresh()
        return summary

    # ---------- the sign convention ----------

    def test_cost_held_negative_is_reported_positive(self):
        """Analytic keeps cost negative; a report that showed that would be unreadable."""
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0)
        self._cost(spk, 9_000_000.0, "material")
        s = self._summary(spk)
        self.assertAlmostEqual(s.act_material, 9_000_000.0, places=2)
        self.assertAlmostEqual(s.act_total, 9_000_000.0, places=2)

    def test_a_credit_reduces_the_bucket_it_reverses(self):
        """A returned remnant must land where the issue landed, or material variance lies."""
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0)
        self._cost(spk, 9_000_000.0, "material")
        self.Analytic.create({
            "name": "sisa kembali", "account_id": spk.analytic_account_id.id,
            "amount": 1_000_000.0, "x_spk_cost_category": "material",
        })
        s = self._summary(spk)
        self.assertAlmostEqual(s.act_material, 8_000_000.0, places=2)

    # ---------- variance ----------

    def test_under_estimate_is_a_positive_variance(self):
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0)
        self._cost(spk, 8_000_000.0, "material")
        s = self._summary(spk)
        self.assertAlmostEqual(s.var_total, 2_000_000.0, places=2)
        self.assertGreater(s.var_total_pct, 0.0)

    def test_over_estimate_is_a_negative_variance(self):
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0)
        self._cost(spk, 13_450_000.0, "material")
        s = self._summary(spk)
        self.assertAlmostEqual(s.var_material, -3_450_000.0, places=2)
        self.assertLess(s.var_total, 0.0)

    def test_categories_do_not_bleed_into_each_other(self):
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0, labor=8_000_000.0)
        self._cost(spk, 11_000_000.0, "material")
        self._cost(spk, 7_000_000.0, "labor")
        s = self._summary(spk)
        self.assertAlmostEqual(s.act_material, 11_000_000.0, places=2)
        self.assertAlmostEqual(s.act_labor, 7_000_000.0, places=2)
        self.assertAlmostEqual(s.var_material, -1_000_000.0, places=2)
        self.assertAlmostEqual(s.var_labor, 1_000_000.0, places=2)

    # ---------- classification ----------

    def test_a_line_with_a_product_is_material_without_being_told(self):
        """Stock valuation is how material cost reaches a job, and it carries a product."""
        spk = self._spk()
        line = self.Analytic.create({
            "name": "stock", "account_id": spk.analytic_account_id.id,
            "amount": -500_000.0, "product_id": self.product.id,
        })
        self.assertEqual(line.x_spk_cost_category, "material")

    def test_an_unclassifiable_line_is_shown_not_dropped(self):
        """A figure that silently vanishes is worse than one that needs a name."""
        spk = self._spk()
        self._estimate(spk, material=1_000_000.0)
        self.Analytic.create({
            "name": "entah", "account_id": spk.analytic_account_id.id,
            "amount": -250_000.0,
        })
        s = self._summary(spk)
        self.assertAlmostEqual(s.act_other, 250_000.0, places=2)
        self.assertAlmostEqual(s.act_total, 250_000.0, places=2,
                               msg="other still counts toward the total")

    def test_an_explicit_category_is_not_overwritten(self):
        spk = self._spk()
        line = self.Analytic.create({
            "name": "subcon print", "account_id": spk.analytic_account_id.id,
            "amount": -5_000_000.0, "product_id": self.product.id,
            "x_spk_cost_category": "subcon",
        })
        self.assertEqual(line.x_spk_cost_category, "subcon",
                         "a stated decision beats the product heuristic")

    # ---------- margin ----------

    def test_margin_slip_is_flagged_against_what_was_quoted(self):
        spk = self._spk()
        est = self._estimate(spk, material=10_000_000.0, margin=30.0)
        self._cost(spk, 12_000_000.0, "material")
        s = self._summary(spk)
        self.assertAlmostEqual(s.quoted_price, est.quoted_price, places=2)
        self.assertLess(s.margin_actual_pct, s.margin_estimated_pct)
        self.assertTrue(s.margin_slipped)

    def test_margin_held_is_not_flagged(self):
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0, margin=30.0)
        self._cost(spk, 9_000_000.0, "material")
        s = self._summary(spk)
        self.assertFalse(s.margin_slipped)

    # ---------- the estimate it measures against ----------

    def test_the_latest_approved_revision_is_the_baseline(self):
        """A revision supersedes; measuring against the old one would flatter the job."""
        spk = self._spk()
        first = self._estimate(spk, material=10_000_000.0)
        second = first.action_revise()
        second.line_ids.unit_cost = 14_000_000.0
        second.action_approve()
        s = self._summary(spk)
        self.assertEqual(s.estimation_id, second)
        self.assertAlmostEqual(s.est_material, 14_000_000.0, places=2)

    def test_waste_allowance_is_carried_for_comparison(self):
        spk = self._spk()
        self._estimate(spk, material=10_000_000.0, waste=10.0)
        s = self._summary(spk)
        self.assertAlmostEqual(s.est_waste, 1_000_000.0, places=2)

    def test_a_job_without_an_estimate_reports_actual_only(self):
        spk = self._spk()
        self._cost(spk, 3_000_000.0, "material")
        s = self._summary(spk)
        self.assertFalse(s.estimation_id)
        self.assertAlmostEqual(s.est_total, 0.0, places=2)
        self.assertAlmostEqual(s.act_total, 3_000_000.0, places=2)
        self.assertAlmostEqual(s.var_total_pct, 0.0, places=2,
                               msg="no baseline means no percentage, not a division by zero")

    def test_one_summary_per_job(self):
        from psycopg2 import IntegrityError
        spk = self._spk()
        self.Summary.create({"spk_id": spk.id})
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Summary.create({"spk_id": spk.id})

    def test_refresh_all_creates_what_is_missing(self):
        spk_a, spk_b = self._spk("A"), self._spk("B")
        self._cost(spk_a, 1_000_000.0)
        self._cost(spk_b, 2_000_000.0)
        self.Summary.refresh_all()
        found = self.Summary.search([("spk_id", "in", (spk_a | spk_b).ids)])
        self.assertEqual(len(found), 2)
