# Part of custom_demo_seed. Licence: LGPL-3.
"""Tests for the demo fixture.

**Hermetic by construction.** Every test seeds into its own ``dataset``, which namespaces the
external IDs and every human-visible reference. Nothing here can see, or be affected by, the
``default`` dataset that a real run leaves in the database.

That is not a stylistic choice - it is the fix for the bug that let a broken build reach the Lead
as green. The original tests seeded into the shared default namespace, so once a full-scale run had
populated the database they silently received 40 partners when they asked for 4. They passed in
isolation (``--test-tags /custom_demo_seed``) and failed in the combined run, which is the worst
possible failure mode: green when run the way the author checks, red when run the way the brief
specifies.

Deliberately small volume: the point is to prove the properties, not to generate 12 months inside
a test transaction.
"""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

#: Private namespace. Must not be "default".
DATASET = "unittest"

#: Reference infix that DATASET produces, e.g. DEMO-UNITTEST-C-0001.
TAG = DATASET.upper() + "-"


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
            dataset=DATASET,
        )

    def _demo_partners(self, tag=TAG):
        return self.env["res.partner"].search(
            [("ref", "like", "DEMO-%sC-%%" % tag)], order="ref"
        )

    def _demo_orders(self, tag=TAG):
        return self.env["sale.order"].search(
            [("operating_unit_id.code", "like", "OU-DEMO-%s%%" % tag)]
        )

    # -- the property the Lead's review caught missing -------------------

    def test_requesting_a_different_shape_raises_instead_of_lying(self):
        """The regression test for the reported defect.

        Before the fix, asking for 4 partners on a dataset seeded with 8 silently returned 8.
        """
        self.Generator.generate(**dict(self.params, partners=8))
        self.assertEqual(len(self._demo_partners()), 8)

        with self.assertRaises(UserError) as caught:
            self.Generator.generate(**dict(self.params, partners=4))

        message = str(caught.exception)
        self.assertIn("partners", message)
        self.assertIn("8", message)
        self.assertIn("4", message)
        # And nothing was changed by the refused call.
        self.assertEqual(len(self._demo_partners()), 8)

    def test_every_shape_key_is_guarded(self):
        """Not just `partners` - any parameter difference must be refused."""
        self.Generator.generate(**self.params)
        for key, value in (
            ("seed", 999),
            ("products", 5),
            ("operating_units", 3),
            ("months", 2),
            ("sale_orders_per_month", 1),
            ("pos_orders_per_month", 2),
            ("ppob_per_month", 4),
            ("with_pos", False),
        ):
            with self.subTest(parameter=key):
                with self.assertRaises(UserError):
                    self.Generator.generate(**dict(self.params, **{key: value}))

    def test_a_different_dataset_is_independent(self):
        """The supported way to seed a second shape: a new dataset name."""
        self.Generator.generate(**self.params)
        self.assertEqual(len(self._demo_partners()), 4)

        other = self.Generator.generate(**dict(self.params, partners=7, dataset="othertest"))
        self.assertEqual(other["partners"], 7)
        self.assertEqual(other["dataset"], "othertest")
        # The first dataset is untouched, and the two share no records.
        self.assertEqual(len(self._demo_partners()), 4)
        self.assertEqual(len(self._demo_partners(tag="OTHERTEST-")), 7)

    def test_recorded_shape_is_readable(self):
        self.assertFalse(self.Generator.get_shape(DATASET))
        self.Generator.generate(**self.params)
        shape = self.Generator.get_shape(DATASET)
        self.assertEqual(shape["partners"], 4)
        self.assertEqual(shape["months"], 3)
        self.assertEqual(shape["seed"], 424242)

    def test_invalid_dataset_name_is_refused(self):
        for bad in ("Default", "with_underscore", "", "9leading", "x" * 21):
            with self.subTest(dataset=bad):
                with self.assertRaises(UserError):
                    self.Generator.generate(**dict(self.params, dataset=bad))

    # -- the original properties ----------------------------------------

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

    def test_counts_are_exactly_what_was_requested(self):
        """The counters must reflect the request, not whatever happened to exist."""
        summary = self.Generator.generate(**self.params)
        self.assertEqual(summary["dataset"], DATASET)
        self.assertEqual(summary["partners"], self.params["partners"])
        self.assertEqual(summary["products"], self.params["products"])
        self.assertEqual(summary["operating_units"], self.params["operating_units"])
        self.assertEqual(
            summary["sale_orders"],
            self.params["months"] * self.params["sale_orders_per_month"],
        )
        self.assertEqual(
            summary["ppob_transactions"],
            self.params["months"] * self.params["ppob_per_month"],
        )

    def test_summary_counts_inventory_and_delivery_moves_separately(self):
        """The first version reported only delivery moves and understated stock_move."""
        summary = self.Generator.generate(**self.params)
        self.assertEqual(
            summary["stock_moves"],
            summary["stock_moves_delivery"] + summary["stock_moves_inventory"],
        )
        storable = self.env["product.template"].search([
            ("default_code", "like", "DEMO-%sP-%%" % TAG), ("is_storable", "=", True),
        ])
        self.assertEqual(summary["stock_moves_inventory"], len(storable))

    def test_every_record_carries_an_external_id(self):
        self.Generator.generate(**self.params)
        data = self.env["ir.model.data"].search([
            ("module", "=", "custom_demo_seed"),
            ("name", "=like", "%s__%%" % DATASET),
        ])
        self.assertTrue(data)
        models = set(data.mapped("model"))
        for expected in ("res.partner", "operating.unit", "ppob.biller",
                         "sale.order", "ppob.transaction", "stock.move"):
            self.assertIn(expected, models)

    def test_data_spans_at_least_two_operating_units(self):
        self.Generator.generate(**self.params)
        units = self.env["operating.unit"].search([("code", "like", "OU-DEMO-%s%%" % TAG)])
        self.assertGreaterEqual(len(units), 2)
        orders = self._demo_orders()
        self.assertGreaterEqual(
            len(set(orders.mapped("operating_unit_id"))), 2,
            "demo sale orders must span more than one Operating Unit",
        )

    def test_data_spans_the_requested_months(self):
        self.Generator.generate(**self.params)
        orders = self._demo_orders()
        self.assertTrue(orders)
        months = {(order.date_order.year, order.date_order.month) for order in orders}
        self.assertGreaterEqual(
            len(months), self.params["months"],
            "expected at least %s distinct months, got %s" % (self.params["months"], len(months)),
        )

    def test_reproducible_for_a_given_seed(self):
        self.Generator.generate(**self.params)
        names = self._demo_partners().mapped("name")
        self.assertEqual(len(names), self.params["partners"])
        self.assertEqual(names[0], "Budi Santoso (Demo 001)")

    def test_demo_identifiers_are_obviously_synthetic(self):
        """No generated value may look like a real person's real identifier."""
        self.Generator.generate(**self.params)
        partners = self._demo_partners()
        self.assertTrue(partners)
        for partner in partners:
            with self.subTest(partner=partner.ref):
                self.assertIn("(Demo", partner.name)
                self.assertTrue(partner.email.endswith("@contoh.invalid"), partner.email)
                self.assertTrue(partner.phone.startswith("+62-800-555-"), partner.phone)
                # A checksum-valid NPWP would be indistinguishable from a real one.
                self.assertFalse(partner.vat)
        for txn in self.env["ppob.transaction"].search(
            [("biller_id.code", "like", "DEMO-%s%%" % TAG)]
        ):
            self.assertTrue(txn.customer_ref.startswith("DEMO-"), txn.customer_ref)

    def test_operating_unit_propagates_to_invoices_and_pickings(self):
        """The warehouse joins on operating_unit_id; a NULL here loses the row silently."""
        self.Generator.generate(**self.params)
        orders = self._demo_orders()
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
        txns = self.env["ppob.transaction"].search(
            [("biller_id.code", "like", "DEMO-%s%%" % TAG)]
        )
        self.assertTrue(txns)
        self.assertTrue(set(txns.mapped("state")) <= {"success", "failed", "reversed"})

    def test_non_admin_is_refused(self):
        user = self.env["res.users"].create({
            "name": "Demo Seed Outsider",
            "login": "demo_seed_outsider",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(UserError):
            self.Generator.with_user(user).generate(**self.params)

    def test_at_least_two_operating_units_required(self):
        with self.assertRaises(UserError):
            self.Generator.generate(**dict(self.params, operating_units=1))
