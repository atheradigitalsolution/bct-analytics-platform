# Part of custom_pdp_masking. Licence: LGPL-3.
"""Tests for the masking policy, the reference digest, and in-Odoo enforcement."""

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_pdp_masking.models.pdp_hash import (
    PDP_DIGEST_LENGTH,
    pdp_hmac_sha256,
)
from odoo.addons.custom_pdp_masking.models.pdp_masked_mixin import (
    UI_MASK_BLANK,
    UI_MASK_PREFIX,
)

#: Known-answer vectors. These pin the cross-language construction. If one of these changes, every
#: digest already in the warehouse is invalid and the change is a migration, not a bug fix.
KAT = [
    (
        "budi.santoso@contoh.invalid",
        "bct-demo-salt",
        "57890775652c2e05536c54638d280c1f2cde752d0fc52bf42ac3a76d53ddbd5e",
    ),
    (
        "budi.santoso@contoh.invalid",
        "other-tenant-salt",
        "c24c6fc738f518543fe3b5cfb2e8e0bafd0464371333e91188552317f9b4f738",
    ),
    (
        "Budi Santoso",
        "bct-demo-salt",
        "a5c30f115ac845dd0cfafabe0326c71de7f1e7d3a869d252c4caa894ab4b978b",
    ),
    (
        "Ir. Sri Wahyuni, S.T.",
        "bct-demo-salt",
        "9a5f1b855c3e59c66e701fb93f6411627790d573b9d48cda9c7b74cf1a1e6b3b",
    ),
]

TENANT_A_SALT = "tenant-a-salt"
TENANT_B_SALT = "tenant-b-salt"


@tagged("post_install", "-at_install", "pdp")
class TestPdpHash(TransactionCase):
    """The digest itself: deterministic, salt-separated, and byte-pinned."""

    def test_known_answer_vectors(self):
        """Byte-identical output is the whole point. A change here breaks the CDC loader."""
        for value, salt, expected in KAT:
            with self.subTest(value=value, salt=salt):
                self.assertEqual(pdp_hmac_sha256(value, salt), expected)

    def test_output_shape(self):
        digest = pdp_hmac_sha256("anything", TENANT_A_SALT)
        self.assertEqual(len(digest), PDP_DIGEST_LENGTH)
        self.assertEqual(digest, digest.lower())
        self.assertTrue(all(char in "0123456789abcdef" for char in digest))

    def test_deterministic_within_a_tenant(self):
        """Same input + same salt -> identical digest across two calls."""
        first = pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT)
        second = pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT)
        self.assertEqual(first, second)

    def test_different_across_tenants(self):
        """Different tenant salt -> different digest for the same cleartext."""
        self.assertNotEqual(
            pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT),
            pdp_hmac_sha256("Budi Santoso", TENANT_B_SALT),
        )

    def test_null_and_empty_are_preserved_as_null(self):
        self.assertIsNone(pdp_hmac_sha256(None, TENANT_A_SALT))
        self.assertIsNone(pdp_hmac_sha256("", TENANT_A_SALT))

    def test_salt_is_the_hmac_key_not_a_prefix(self):
        """Guards against a loader reimplementing this as sha256(salt + value)."""
        import hashlib

        naive = hashlib.sha256((TENANT_A_SALT + "Budi Santoso").encode("utf-8")).hexdigest()
        self.assertNotEqual(pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT), naive)

    def test_no_normalisation_is_applied(self):
        """No trim, no case fold. Whitespace and case are part of the input."""
        self.assertNotEqual(
            pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT),
            pdp_hmac_sha256(" Budi Santoso ", TENANT_A_SALT),
        )
        self.assertNotEqual(
            pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT),
            pdp_hmac_sha256("budi santoso", TENANT_A_SALT),
        )

    def test_empty_salt_is_refused(self):
        with self.assertRaises(ValueError):
            pdp_hmac_sha256("Budi Santoso", "")

    def test_non_text_input_is_refused(self):
        with self.assertRaises(TypeError):
            pdp_hmac_sha256(12345, TENANT_A_SALT)


@tagged("post_install", "-at_install", "pdp")
class TestPdpMaskingRule(TransactionCase):
    """The policy table, and the plan it hands the CDC loader."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env["pdp.masking.rule"]

    def test_contract_01_transform_table(self):
        expected = {
            "public": "none",
            "internal": "none",
            "personal": "hmac_sha256",
            "sensitive": "hmac_sha256_or_null",
            "secret": "drop",
        }
        actual = {rule.pdp_class: rule.transform for rule in self.Rule.search([])}
        self.assertEqual(actual, expected)

    def test_one_rule_per_class(self):
        rules = self.Rule.search([])
        self.assertEqual(len(rules), 5)
        self.assertEqual(len(set(rules.mapped("pdp_class"))), 5)

    def test_hash_value_uses_the_configured_salt(self):
        self.env["ir.config_parameter"].sudo().set_param("pdp.mask_salt", TENANT_A_SALT)
        self.assertEqual(
            self.Rule.hash_value("Budi Santoso"),
            pdp_hmac_sha256("Budi Santoso", TENANT_A_SALT),
        )

    def test_missing_salt_raises(self):
        """An unset salt fails loudly rather than degrading to an unkeyed hash."""
        self.env["ir.config_parameter"].sudo().set_param("pdp.mask_salt", False)
        rule = self.Rule.with_context(pdp_test_no_env_salt=True)
        with self.patch_env_salt(None):
            with self.assertRaises(UserError):
                rule._get_salt()

    def patch_env_salt(self, value):
        import os
        from contextlib import contextmanager

        keys = [
            "WAREHOUSE_MASK_SALT_DEFAULT",
            "WAREHOUSE_MASK_SALT_" + self.Rule._tenant_key(),
        ]

        @contextmanager
        def _patch():
            saved = {key: os.environ.pop(key, None) for key in keys}
            try:
                if value is not None:
                    for key in keys:
                        os.environ[key] = value
                yield
            finally:
                for key, old in saved.items():
                    if old is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old

        return _patch()

    def test_digest_spec_is_published(self):
        spec = self.Rule.get_digest_spec()
        self.assertEqual(spec["primitive"], "hmac")
        self.assertEqual(spec["digest"], "sha256")
        self.assertEqual(spec["key_encoding"], "utf-8")
        self.assertEqual(spec["message_encoding"], "utf-8")
        self.assertEqual(spec["output"], "lowercase hex, 64 characters")
        self.assertTrue(spec["null_in_null_out"])

    def test_masking_plan_resolves_per_column(self):
        plan = self.Rule.get_masking_plan(["res.partner", "res.users"])
        self.assertEqual(plan["res.partner"]["email"]["transform"], "hmac_sha256")
        self.assertEqual(plan["res.partner"]["vat"]["transform"], "hmac_sha256")
        # sensitive + drop_to_null -> NULL, not a digest
        self.assertEqual(plan["res.partner"]["comment"]["transform"], "null")
        self.assertEqual(plan["res.partner"]["id"]["transform"], "none")
        # secret columns are absent from the plan entirely
        self.assertNotIn("password", plan["res.users"])
        self.assertIn("login", plan["res.users"])


@tagged("post_install", "-at_install", "pdp")
class TestPdpUiMasking(TransactionCase):
    """In-Odoo enforcement: a non-viewer never sees personal data through read()."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "Budi Santoso",
            "email": "budi.santoso@contoh.invalid",
            "phone": "+62-800-0000-0001",
            "street": "Jl. Contoh No. 1",
            "comment": "<p>Catatan bebas untuk pengujian.</p>",
            "ref": "DEMO-P-0001",
        })
        cls.plain_user = cls.env["res.users"].create({
            "name": "PDP Plain User",
            "login": "pdp_plain_user",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })
        cls.viewer_user = cls.env["res.users"].create({
            "name": "PDP Viewer User",
            "login": "pdp_viewer_user",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("custom_pdp_core.group_pdp_data_viewer").id,
            ])],
        })

    def test_plain_user_sees_masked_values(self):
        row = self.partner.with_user(self.plain_user).read(
            ["name", "email", "phone", "street", "comment", "ref"]
        )[0]
        for field_name in ("name", "email", "phone", "street"):
            with self.subTest(field=field_name):
                self.assertTrue(row[field_name].startswith(UI_MASK_PREFIX))
                self.assertNotIn("Budi", row[field_name])
        self.assertEqual(row["comment"], UI_MASK_BLANK)
        # `ref` is on the model's exclusion list so the search box stays usable.
        self.assertEqual(row["ref"], "DEMO-P-0001")

    def test_masked_values_are_stable_and_distinct(self):
        other = self.env["res.partner"].create({"name": "Siti Aminah"})
        first = self.partner.with_user(self.plain_user).read(["name"])[0]["name"]
        second = self.partner.with_user(self.plain_user).read(["name"])[0]["name"]
        third = other.with_user(self.plain_user).read(["name"])[0]["name"]
        self.assertEqual(first, second, "the UI token must be stable for a given value")
        self.assertNotEqual(first, third, "two partners must stay distinguishable")

    def test_display_name_is_masked_too(self):
        row = self.partner.with_user(self.plain_user).read(["display_name"])[0]
        self.assertTrue(row["display_name"].startswith(UI_MASK_PREFIX))

    def test_ui_token_is_not_the_warehouse_digest(self):
        """The UI token must never be usable as a warehouse join key."""
        self.env["ir.config_parameter"].sudo().set_param("pdp.mask_salt", TENANT_A_SALT)
        masked = self.partner.with_user(self.plain_user).read(["email"])[0]["email"]
        warehouse = self.env["pdp.masking.rule"].hash_value(
            "budi.santoso@contoh.invalid"
        )
        self.assertNotIn(masked.replace(UI_MASK_PREFIX, ""), warehouse)

    def test_data_viewer_sees_cleartext(self):
        row = self.partner.with_user(self.viewer_user).read(["name", "email", "comment"])[0]
        self.assertEqual(row["name"], "Budi Santoso")
        self.assertEqual(row["email"], "budi.santoso@contoh.invalid")
        self.assertIn("Catatan bebas", row["comment"])

    def test_orm_access_is_not_masked(self):
        """Masking is a presentation control. Business logic keeps seeing cleartext."""
        partner = self.partner.with_user(self.plain_user)
        self.assertEqual(partner.email, "budi.santoso@contoh.invalid")

    def test_search_still_works_for_a_non_viewer(self):
        found = self.env["res.partner"].with_user(self.plain_user).search(
            [("email", "=", "budi.santoso@contoh.invalid")]
        )
        self.assertIn(self.partner, found)
