# -*- coding: utf-8 -*-
"""The arithmetic, and the one error it exists to prevent."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestEstimation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Est = cls.env["custom.spk.estimation"]
        cls.Line = cls.env["custom.spk.estimation.line"]
        cls.Tmpl = cls.env["custom.spk.estimation.template"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

    def _est(self, overhead=0.0, risk=0.0, margin=0.0):
        return self.Est.create({
            "overhead_rate": overhead, "risk_rate": risk, "target_margin": margin,
        })

    def _line(self, est, category="material", qty=1.0, cost=0.0, waste=0.0):
        return self.Line.create({
            "estimation_id": est.id, "category": category, "name": "x",
            "quantity": qty, "unit_cost": cost, "waste_pct": waste,
        })

    # ---------- the error this module exists to prevent ----------

    def test_margin_is_not_markup(self):
        """price = cost / (1 - margin). The markup form is always short.

        Cost 100 at a 30% target: dividing gives 142.86, whose margin is
        42.86/142.86 = 30%. Multiplying would give 130, whose margin is 23% — and a
        business quoting that way believes it runs on 30% and does not.
        """
        est = self._est(margin=30.0)
        self._line(est, cost=100.0)
        self.assertAlmostEqual(est.base_price, 100.0, places=2)
        self.assertAlmostEqual(est.quoted_price, 100.0 / 0.7, places=2)
        self.assertAlmostEqual(est.quoted_price, 142.857, places=2)
        self.assertNotAlmostEqual(est.quoted_price, 130.0, places=2,
                                  msg="this is the markup answer and it is wrong")
        realised = est.margin_amount / est.quoted_price * 100.0
        self.assertAlmostEqual(realised, 30.0, places=4,
                               msg="the margin actually realised must equal the target")

    def test_a_margin_of_one_hundred_percent_is_refused(self):
        with self.assertRaises(ValidationError):
            self._est(margin=100.0)

    # ---------- the cost build ----------

    def test_categories_roll_up_separately(self):
        est = self._est()
        self._line(est, "material", cost=12_000_000.0)
        self._line(est, "labor", cost=8_000_000.0)
        self._line(est, "subcon", cost=5_000_000.0)
        self._line(est, "delivery", cost=2_500_000.0)
        self._line(est, "venue", cost=1_000_000.0)
        self.assertAlmostEqual(est.material_cost, 12_000_000.0, places=2)
        self.assertAlmostEqual(est.labor_cost, 8_000_000.0, places=2)
        self.assertAlmostEqual(est.direct_cost, 28_500_000.0, places=2)

    def test_overhead_and_contingency_compound_in_order(self):
        """Contingency is taken on cost INCLUDING overhead, not beside it."""
        est = self._est(overhead=12.0, risk=5.0)
        self._line(est, cost=10_000_000.0)
        self.assertAlmostEqual(est.overhead_amount, 1_200_000.0, places=2)
        self.assertAlmostEqual(est.total_cost, 11_200_000.0, places=2)
        self.assertAlmostEqual(est.contingency_amount, 560_000.0, places=2)
        self.assertAlmostEqual(est.base_price, 11_760_000.0, places=2)

    # ---------- waste is estimated so it can be measured ----------

    def test_waste_allowance_is_added_and_kept_visible(self):
        est = self._est()
        self._line(est, "material", qty=15.0, cost=185_000.0, waste=10.0)
        base = 15.0 * 185_000.0
        self.assertAlmostEqual(est.waste_allowance, base * 0.10, places=2)
        self.assertAlmostEqual(est.material_cost, base * 1.10, places=2)

    def test_labour_lines_carry_no_waste(self):
        est = self._est()
        self._line(est, "labor", qty=12.0, cost=180_000.0)
        self.assertAlmostEqual(est.waste_allowance, 0.0, places=2)

    def test_total_waste_is_refused(self):
        est = self._est()
        with self.assertRaises(ValidationError):
            self._line(est, "material", waste=100.0)

    def test_a_line_with_no_quantity_is_refused(self):
        est = self._est()
        with self.assertRaises(ValidationError):
            self._line(est, qty=0.0)

    # ---------- workflow ----------

    def test_an_empty_estimation_cannot_be_approved(self):
        with self.assertRaises(UserError):
            self._est().action_approve()

    def test_revision_supersedes_rather_than_overwrites(self):
        """A negotiation has to keep what was quoted before it."""
        est = self._est(margin=30.0)
        self._line(est, cost=100.0)
        est.action_approve()
        new = est.action_revise()
        self.assertEqual(est.state, "superseded")
        self.assertEqual(new.state, "draft")
        self.assertEqual(new.revision, 2)
        self.assertNotEqual(new.name, est.name)
        self.assertAlmostEqual(new.base_price, est.base_price, places=2)

    # ---------- templates ----------

    def test_template_copies_lines_and_does_not_link_them(self):
        """Editing the template later must not change what was already quoted."""
        tmpl = self.Tmpl.create({"name": "Booth 3x3", "overhead_rate": 15.0, "risk_rate": 8.0})
        self.env["custom.spk.estimation.template.line"].create({
            "template_id": tmpl.id, "category": "material", "name": "Multiplek",
            "quantity": 15.0, "unit_cost": 185_000.0, "waste_pct": 10.0,
        })
        est = self._est()
        tmpl.action_apply_to(est)

        self.assertEqual(len(est.line_ids), 1)
        self.assertAlmostEqual(est.overhead_rate, 15.0, places=2)
        self.assertAlmostEqual(est.risk_rate, 8.0, places=2)

        tmpl.line_ids.unit_cost = 999_999.0
        self.assertAlmostEqual(est.line_ids.unit_cost, 185_000.0, places=2,
                               msg="the estimate is a copy, not a view of the template")

    def test_template_refuses_an_estimation_already_quoted(self):
        tmpl = self.Tmpl.create({"name": "Booth 3x3"})
        est = self._est()
        self._line(est, cost=1.0)
        est.action_approve()
        with self.assertRaises(UserError):
            tmpl.action_apply_to(est)
