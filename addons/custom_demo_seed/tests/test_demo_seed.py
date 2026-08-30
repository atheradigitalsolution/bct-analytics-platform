# Part of custom_demo_seed. Licence: LGPL-3.
"""Tests for the demo fixture.

Deliberately small volume: the point is to prove the three properties (idempotent, reproducible,
spanning >= 2 Operating Units and >= the requested months), not to generate the full 12 months
inside a test transaction.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "demo_seed")
class TestDemoSeed(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Generator = cls.env["demo.seed.generator"]
        cls.params = dict(
            seed=424242,
            partners=4,
            products=6,
            operating_units=2,
            months=3,
            sale_orders_per_month=2,
            pos_orders_per_month=1,
            ppob_per_month=3,
        )

    def test_generation_is_idempotent(self):
        """Acceptance criterion 7: running it twice does not duplicate rows."""
        first = self.Generator.generate(**self.params)
        second = self.Generator.generate(**self.params)
        for key in first:
            if key == "elapsed_seconds":
                continue
            with self.subTest(counter=key):
                self.assertEqual(
                    first[key], second[key],
                    "a second run changed the %s count (%s -> %s)"
                    % (key, first[key], second[key]),
                )

    def test_every_record_carries_an_external_id(self):
        """Idempotency rests on ir.model.data, so assert the external IDs really exist."""
        self.Generator.generate(**self.params)
        data = self.env["ir.model.data"].search([("module", "=", "custom_demo_seed")])
        self.assertTrue(data)
        models = set(data.mapped("model"))
        for expected in ("res.partner", "operating.unit", "ppob.biller",
                         "sale.order", "ppob.transaction"):
            self.assertIn(expected, models)

    def test_data_spans_at_least_two_operating_units(self):
        self.Generator.generate(**self.params)
        units = self.env["operating.unit"].search([("code", "like", "OU-DEMO-%")])
        self.assertGreaterEqual(len(units), 2)
        orders = self.env["sale.order"].search([("operating_unit_id", "in", units.ids)])
        self.assertGreaterEqual(
            len(set(orders.mapped("operating_unit_id"))), 2,
            "demo sale orders must span more than one Operating Unit",
        )

    def test_data_spans_the_requested_months(self):
        self.Generator.generate(**self.params)
        orders = self.env["sale.order"].search(
            [("operating_unit_id.code", "like", "OU-DEMO-%")], order="date_order"
        )
        self.assertTrue(orders)
        months = {(order.date_order.year, order.date_order.month) for order in orders}
        self.assertGreaterEqual(
            len(months), self.params["months"],
            "expected at least %s distinct months, got %s" % (self.params["months"], len(months)),
        )

    def test_reproducible_for_a_given_seed(self):
        """The same seed must produce the same partner set."""
        self.Generator.generate(**self.params)
        names = self.env["res.partner"].search(
            [("ref", "like", "DEMO-C-%")], order="ref"
        ).mapped("name")
        self.assertEqual(names[0], "Budi Santoso (Demo 001)")
        self.assertEqual(len(names), self.params["partners"])

    def test_demo_identifiers_are_obviously_synthetic(self):
        """No generated value may look like a real person's real identifier."""
        self.Generator.generate(**self.params)
        partners = self.env["res.partner"].search([("ref", "like", "DEMO-C-%")])
        self.assertTrue(partners)
        for partner in partners:
            with self.subTest(partner=partner.ref):
                self.assertIn("(Demo", partner.name)
                self.assertTrue(partner.email.endswith("@contoh.invalid"), partner.email)
                self.assertTrue(partner.phone.startswith("+62-800-555-"), partner.phone)
                # A checksum-valid NPWP would be indistinguishable from a real one.
                self.assertFalse(partner.vat)
        for txn in self.env["ppob.transaction"].search([("biller_id.code", "like", "DEMO-%")]):
            self.assertTrue(txn.customer_ref.startswith("DEMO-"), txn.customer_ref)

    def test_operating_unit_propagates_to_invoices_and_pickings(self):
        """The warehouse joins on operating_unit_id; a NULL here loses the row silently."""
        self.Generator.generate(**self.params)
        orders = self.env["sale.order"].search(
            [("operating_unit_id.code", "like", "OU-DEMO-%")]
        )
        self.assertTrue(orders)
        invoices = orders.invoice_ids
        self.assertTrue(invoices, "the fixture must produce invoices")
        self.assertFalse(
            invoices.filtered(lambda move: not move.operating_unit_id),
            "an invoice generated from a stamped sale order carries no Operating Unit",
        )
        pickings = orders.picking_ids
        self.assertTrue(pickings, "the fixture must produce deliveries")
        self.assertFalse(
            pickings.filtered(lambda picking: not picking.operating_unit_id),
            "a delivery generated from a stamped sale order carries no Operating Unit",
        )

    def test_ppob_states_are_realistic(self):
        self.Generator.generate(**self.params)
        txns = self.env["ppob.transaction"].search([("biller_id.code", "like", "DEMO-%")])
        self.assertTrue(txns)
        states = set(txns.mapped("state"))
        self.assertTrue(states <= {"success", "failed", "reversed"})

    def test_non_admin_is_refused(self):
        user = self.env["res.users"].create({
            "name": "Demo Seed Outsider",
            "login": "demo_seed_outsider",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(UserError):
            self.Generator.with_user(user).generate(**self.params)

    def test_at_least_two_operating_units_required(self):
        params = dict(self.params, operating_units=1)
        with self.assertRaises(UserError):
            self.Generator.generate(**params)
