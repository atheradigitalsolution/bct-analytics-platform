# Part of custom_pdp_core. Licence: LGPL-3.
"""Tests for the PDP classification registry (frozen contract 01)."""

import psycopg2

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from odoo.addons.custom_pdp_core.models.pdp_field_classification import PDP_CLASS_KEYS

#: Every model the warehouse reads, per the Platform-Addons brief, Scope 1.
REQUIRED_MODELS = [
    "res.partner",
    "res.users",
    "res.company",
    "product.template",
    "product.product",
    "sale.order",
    "sale.order.line",
    "account.move",
    "account.move.line",
    "stock.move",
    "pos.order",
    "pos.order.line",
    "ppob.transaction",
]

#: Spot checks. These are the classifications the rest of the platform is entitled to assume.
SPOT_CHECKS = [
    ("res.partner", "name", "personal"),
    ("res.partner", "email", "personal"),
    ("res.partner", "phone", "personal"),
    ("res.partner", "street", "personal"),
    ("res.partner", "city", "personal"),
    ("res.partner", "vat", "sensitive"),
    ("res.partner", "comment", "sensitive"),
    ("res.users", "password", "secret"),
    ("res.users", "totp_secret", "secret"),
    ("res.company", "name", "public"),
    ("product.template", "name", "public"),
    ("sale.order", "amount_total", "internal"),
    ("stock.move", "product_qty", "internal"),
    ("ppob.transaction", "customer_ref", "sensitive"),
]


@tagged("post_install", "-at_install", "pdp")
class TestPdpFieldClassification(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Classification = cls.env["pdp.field.classification"]

    # -- taxonomy -------------------------------------------------------

    def test_taxonomy_is_exactly_five_frozen_classes(self):
        """Contract 01 freezes five classes. A sixth is a contract breach."""
        self.assertEqual(
            PDP_CLASS_KEYS,
            ("public", "internal", "personal", "sensitive", "secret"),
        )
        selection = dict(
            self.Classification._fields["pdp_class"]._description_selection(self.env)
        )
        self.assertEqual(set(selection), set(PDP_CLASS_KEYS))

    def test_seeded_classes_are_within_the_taxonomy(self):
        used = set(self.Classification.search([]).mapped("pdp_class"))
        self.assertTrue(used, "the registry must not be empty after install")
        self.assertFalse(used - set(PDP_CLASS_KEYS))

    # -- constraints ----------------------------------------------------

    @mute_logger("odoo.sql_db")
    def test_model_field_pair_is_unique(self):
        self.Classification.create({
            "model_name": "x.unit.test",
            "field_name": "some_column",
            "pdp_class": "internal",
        })
        with self.assertRaises(psycopg2.errors.UniqueViolation):
            with self.env.cr.savepoint():
                self.Classification.create({
                    "model_name": "x.unit.test",
                    "field_name": "some_column",
                    "pdp_class": "personal",
                })

    @mute_logger("odoo.sql_db")
    def test_drop_to_null_requires_sensitive(self):
        """drop_to_null is the 'sensitive' NULL-drop of contract 01, nothing else."""
        with self.assertRaises(psycopg2.errors.CheckViolation):
            with self.env.cr.savepoint():
                self.Classification.create({
                    "model_name": "x.unit.test",
                    "field_name": "another_column",
                    "pdp_class": "personal",
                    "drop_to_null": True,
                })

    def test_blank_names_rejected(self):
        with self.assertRaises(ValidationError):
            self.Classification.create({
                "model_name": "   ",
                "field_name": "col",
                "pdp_class": "internal",
            })

    # -- seeded map -----------------------------------------------------

    def test_map_covers_every_required_model(self):
        payload = self.Classification.get_classification_map()
        self.assertEqual(payload["contract"], "01-classification")
        self.assertEqual(payload["classes"], list(PDP_CLASS_KEYS))
        missing = [m for m in REQUIRED_MODELS if not payload["models"].get(m)]
        self.assertFalse(
            missing, "models absent from the seeded classification map: %s" % missing
        )

    def test_spot_checks(self):
        for model_name, field_name, expected in SPOT_CHECKS:
            with self.subTest(model=model_name, field=field_name):
                row = self.Classification.get_classification(model_name, field_name)
                self.assertTrue(
                    row, "%s.%s carries no classification" % (model_name, field_name)
                )
                self.assertEqual(row["pdp_class"], expected)

    def test_unclassified_field_returns_nothing(self):
        """The loader must be able to hard-fail. An unknown column returns False, not a class."""
        self.assertFalse(
            self.Classification.get_classification("res.partner", "no_such_column_xyz")
        )
        self.assertEqual(
            self.Classification.get_unclassified_fields(
                "res.partner", ["email", "no_such_column_xyz"]
            ),
            ["no_such_column_xyz"],
        )

    def test_map_restricted_to_requested_models(self):
        payload = self.Classification.get_classification_map(["res.partner"])
        self.assertEqual(list(payload["models"]), ["res.partner"])

    def test_secret_columns_are_not_extractable(self):
        """A `secret` column is never named in the loader's SELECT list."""
        extractable = self.Classification.get_extractable_fields("res.users")
        self.assertIn("login", extractable)
        self.assertNotIn("password", extractable)
        self.assertNotIn("totp_secret", extractable)

    # -- coverage -------------------------------------------------------

    def test_no_installed_column_is_unclassified(self):
        """Every physical column of every warehouse-read model must carry a class.

        Models that are not installed in this database are skipped: the registry deliberately
        depends on `base` only and classifies models by name.
        """
        gaps = self.Classification.check_coverage(REQUIRED_MODELS)
        self.assertFalse(
            gaps,
            "unclassified columns found - the CDC loader would refuse to start:\n%s"
            % "\n".join("  %s: %s" % (m, ", ".join(c)) for m, c in sorted(gaps.items())),
        )

    # -- access ---------------------------------------------------------

    def test_plain_user_may_read_but_not_write(self):
        user = self.env["res.users"].create({
            "name": "PDP Test Reader",
            "login": "pdp_test_reader",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        registry = self.Classification.with_user(user)
        self.assertTrue(registry.search_count([]) > 0)
        with self.assertRaises(Exception):
            registry.create({
                "model_name": "x.denied",
                "field_name": "col",
                "pdp_class": "internal",
            })
