# -*- coding: utf-8 -*-
"""The offcut threshold: who pays for the part of the sheet nobody used."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import MaterialCommon


@tagged("post_install", "-at_install")
class TestOffcut(MaterialCommon):

    def _return(self, spk, product, qty=1.0, share=100.0):
        ret = self.Ret.create({"spk_id": spk.id, "returned_by": self.worker.id})
        line = self.RetL.create({
            "return_id": ret.id, "product_id": product.id,
            "qty_returned": qty, "remnant_share": share,
        })
        return ret, line

    # ---------- the threshold ----------

    def test_a_large_remnant_is_reusable_and_credits_the_job(self):
        """40% of a sheet is above the 30% threshold, so it comes back at 60% value."""
        spk = self._spk()
        _ret, line = self._return(spk, self.sheet, qty=1.0, share=40.0)
        self.assertTrue(line.is_reusable)
        self.assertAlmostEqual(line.credit_amount, 185_000.0 * 0.60, places=2)
        self.assertAlmostEqual(line.waste_amount, 185_000.0 * 0.40, places=2)

    def test_a_small_remnant_is_waste_and_the_job_keeps_it(self):
        """20% is below the threshold: too small to store, so it is not the next job's."""
        spk = self._spk()
        _ret, line = self._return(spk, self.sheet, qty=1.0, share=20.0)
        self.assertFalse(line.is_reusable)
        self.assertAlmostEqual(line.credit_amount, 0.0, places=2)
        self.assertAlmostEqual(line.waste_amount, 185_000.0, places=2)

    def test_the_threshold_boundary_is_inclusive(self):
        spk = self._spk()
        _ret, line = self._return(spk, self.sheet, qty=1.0, share=30.0)
        self.assertTrue(line.is_reusable, "exactly at the threshold is worth keeping")

    def test_credit_plus_waste_always_equals_what_came_back(self):
        """No value is created or lost by classifying a remnant."""
        spk = self._spk()
        for share in (10.0, 30.0, 50.0, 100.0):
            _ret, line = self._return(spk, self.sheet, qty=2.0, share=share)
            self.assertAlmostEqual(
                line.credit_amount + line.waste_amount, 2.0 * 185_000.0, places=2,
                msg="classification splits value, it does not change it",
            )

    # ---------- class decides whether there is a remnant at all ----------

    def test_made_to_order_material_has_no_second_life(self):
        """A banner printed to one size cannot be credited to anyone.

        Crediting it would move real cost off the job that caused it, which is the
        distortion this whole policy exists to remove — just in the other direction.
        """
        spk = self._spk()
        _ret, line = self._return(spk, self.banner, qty=1.0, share=90.0)
        self.assertFalse(line.is_reusable)
        self.assertAlmostEqual(line.credit_amount, 0.0, places=2)
        self.assertAlmostEqual(line.waste_amount, 500_000.0, places=2)

    def test_offcut_product_is_only_allowed_on_recut_stock(self):
        with self.assertRaises(ValidationError):
            self.banner.product_tmpl_id.x_spk_offcut_product_id = self.offcut_product.id

    # ---------- the discount has to be real ----------

    def test_valuing_a_remnant_at_full_price_is_refused(self):
        """Otherwise the offcut rack becomes a way to move cost off jobs."""
        with self.assertRaises(ValidationError):
            self.sheet.product_tmpl_id.x_spk_offcut_valuation_pct = 100.0

    def test_a_threshold_of_zero_or_one_hundred_classifies_nothing(self):
        for bad in (0.0, 100.0):
            with self.assertRaises(ValidationError):
                self.sheet.product_tmpl_id.x_spk_offcut_threshold_pct = bad

    # ---------- booking ----------

    def test_booking_credits_the_job_with_an_analytic_line(self):
        spk = self._spk()
        ret, line = self._return(spk, self.sheet, qty=1.0, share=40.0)
        expected = line.credit_amount
        ret.action_done()

        self.assertEqual(ret.state, "done")
        lines = self.env["account.analytic.line"].search([
            ("account_id", "=", spk.analytic_account_id.id)])
        self.assertTrue(lines)
        self.assertAlmostEqual(sum(lines.mapped("amount")), expected, places=2,
                               msg="a credit is positive against a cost held negative")

    def test_waste_only_return_books_nothing(self):
        """Nothing changes hands: the job already carries the cost."""
        spk = self._spk()
        ret, _line = self._return(spk, self.sheet, qty=1.0, share=10.0)
        ret.action_done()
        lines = self.env["account.analytic.line"].search([
            ("account_id", "=", spk.analytic_account_id.id)])
        self.assertFalse(lines)

    def test_booking_twice_is_refused(self):
        spk = self._spk()
        ret, _line = self._return(spk, self.sheet, qty=1.0, share=40.0)
        ret.action_done()
        with self.assertRaises(UserError):
            ret.action_done()

    def test_remnant_share_bounds(self):
        spk = self._spk()
        ret = self.Ret.create({"spk_id": spk.id})
        for bad in (0.0, -5.0, 150.0):
            with self.assertRaises(ValidationError):
                self.RetL.create({
                    "return_id": ret.id, "product_id": self.sheet.id,
                    "qty_returned": 1.0, "remnant_share": bad,
                })
