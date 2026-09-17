# -*- coding: utf-8 -*-
"""The completion criterion for this module, written as assertions.

The business process document asks for proof that an Account Executive cannot
reach a price "by any route, including export and API". A view that hides a field
does not give that. These tests go at the ORM, which is what export and JSON-RPC
go through too.
"""

from __future__ import annotations

from odoo import fields as odoo_fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import SpkCommon


@tagged("post_install", "-at_install")
class TestPriceFence(SpkCommon):

    # ---------- the strongest guard: nothing to leak ----------

    def test_spk_carries_no_monetary_field(self):
        """Absence, not concealment.

        This is the test that matters most, because it fails when someone adds a
        price to the AE-facing model in six months' time. A hidden field would
        pass a view-level review and leak through an export.
        """
        offenders = []
        for name, field in self.env["custom.spk"]._fields.items():
            if isinstance(field, odoo_fields.Monetary):
                offenders.append("%s (Monetary)" % name)
            elif isinstance(field, odoo_fields.Float) and getattr(field, "currency_field", None):
                offenders.append("%s (Float with currency)" % name)
        self.assertFalse(
            offenders,
            "custom.spk is read by the Account Executive and must hold no money. Found: %s"
            % ", ".join(offenders),
        )

    # ---------- the routes the BPD names ----------

    def test_ae_cannot_reach_sale_order_at_all(self):
        """No sales group, so there is no record to filter and no field to hide."""
        with self.assertRaises(AccessError):
            self.env["sale.order"].with_user(self.ae).search([], limit=1)

    def test_ae_cannot_reach_analytic_lines(self):
        """Every cost booked against a job lands here.

        The standard ACL already denies it, because the AE holds no accounting
        group. This asserts it anyway: the day someone adds the AE to an accounting
        group for an unrelated reason, this is what should fail.
        """
        with self.assertRaises(AccessError):
            self.env["account.analytic.line"].with_user(self.ae).search([], limit=1)

    def test_ae_cannot_see_product_cost(self):
        """The hole a view-level fence leaves open.

        `standard_price` ships with no restricting group, and from a bill of
        quantity, cost is most of the way to price. Checked through `fields_get`
        because that is what an export dialog and a client-side field list read.
        """
        product = self.env["product.product"].create({"name": "Hollow 40x40", "standard_price": 95000.0})
        self.assertNotIn(
            "standard_price",
            product.with_user(self.ae).fields_get(),
            "standard_price is visible to the Account Executive",
        )
        with self.assertRaises(AccessError):
            product.with_user(self.ae).read(["standard_price"])

    def test_cost_viewer_can_see_product_cost(self):
        """A fence that blocks the estimator too would just be turned off."""
        product = self.env["product.product"].create({"name": "Multiplek 12mm", "standard_price": 185000.0})
        self.assertIn("standard_price", product.with_user(self.pm).fields_get())
        self.assertAlmostEqual(
            product.with_user(self.pm).read(["standard_price"])[0]["standard_price"],
            185000.0,
            places=2,
        )

    def test_list_price_is_deliberately_not_fenced(self):
        """Documented choice, asserted so it is a choice and not a leak.

        In engineer-to-order work `list_price` is not the quoted price: the
        quotation carries that, and the AE cannot read sale.order. Gating it would
        cost website and portal flows a field they legitimately need.
        """
        product = self.env["product.product"].create({"name": "Jasa Booth 3x3", "list_price": 1.0})
        self.assertIn("list_price", product.with_user(self.ae).fields_get())

    def test_shift_allowance_is_fenced_but_multiplier_is_not(self):
        """A supervisor schedules shifts without learning what one costs."""
        shift = self.env.ref("custom_spk.shift_3")
        ae_fields = shift.with_user(self.ae).fields_get()
        self.assertNotIn("meal_allowance", ae_fields)
        self.assertIn("rate_multiplier", ae_fields, "a ratio is not money")
