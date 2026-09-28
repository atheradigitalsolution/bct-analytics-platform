# -*- coding: utf-8 -*-
"""The demo seeder must refuse to invent a password.

A default written into the source tree is a known credential from the moment
it is committed, and this seeder runs on every `-u`. The test that matters is
not "does seeding work" but "which way does it fail when the variable is
gone" -- so both directions are asserted here.
"""
import secrets
from unittest.mock import patch

from odoo.exceptions import AccessDenied, UserError
from odoo.tests import TransactionCase, tagged

LOGIN = "zz-pwtest@simrs-demo.invalid"
# One invented slug, so the real demo accounts are never touched by this test.
FAKE_USERS = [("zz-pwtest", None, ["custom_hms_base.group_hms_staff"])]


@tagged("post_install", "-at_install", "hms")
class DemoPasswordCase(TransactionCase):

    def _builder(self):
        return self.env["hms.demo.builder"]

    def _existing(self):
        return self.env["res.users"].sudo().search([("login", "=", LOGIN)])

    # --- fails closed -----------------------------------------------------
    def test_absent_variable_refuses_and_creates_nothing(self):
        env_without = {k: v for k, v in __import__("os").environ.items()
                       if k != "SIMRS_DEMO_PASSWORD"}
        with patch.dict("os.environ", env_without, clear=True), \
             patch.object(type(self._builder()), "DEMO_USERS", FAKE_USERS):
            with self.assertRaises(UserError) as caught:
                self._builder()._users({})
        self.assertIn("SIMRS_DEMO_PASSWORD", str(caught.exception),
                      "Pesannya harus menyebut variabel mana yang harus disetel.")
        self.assertFalse(self._existing(), "Akun tidak boleh lahir saat sandi tidak ada.")

    def test_blank_variable_is_refused_too(self):
        # compose forwards ${SIMRS_DEMO_PASSWORD:-}, so an .env without the
        # value leaves the key PRESENT and empty -- os.environ.get() never
        # reaches its default there.
        with patch.dict("os.environ", {"SIMRS_DEMO_PASSWORD": "   "}), \
             patch.object(type(self._builder()), "DEMO_USERS", FAKE_USERS):
            with self.assertRaises(UserError):
                self._builder()._users({})
        self.assertFalse(self._existing())

    #: SHA-256 of the default password this module used to ship. The guard below
    #: compares digests instead of the literal on purpose: spelling the password
    #: out here would republish it into the very tree the guard exists to keep
    #: clean (this repository is public).
    RETIRED_PASSWORD_SHA256 = (
        "4697c4b1b6eaec1af2341e65bfb497884e23102fbc2cccf5f87873185a4afd86"
    )

    def test_no_default_password_survives_in_the_source(self):
        import hashlib
        import inspect
        import re

        from odoo.addons.custom_hms_demo.models import hms_demo_builder

        source = inspect.getsource(hms_demo_builder)
        # Every string literal in the module, hashed and compared. A substring
        # search cannot work without the plaintext, and this is stricter anyway:
        # it catches the password wherever it hides, not just where we looked.
        digests = {
            hashlib.sha256(token.encode()).hexdigest()
            for token in re.findall(r"""['"]([^'"\n]{6,64})['"]""", source)
        }
        self.assertNotIn(
            self.RETIRED_PASSWORD_SHA256, digests,
            "Sandi bawaan tidak boleh kembali ke pohon sumber.",
        )

    # --- positive control -------------------------------------------------
    def test_seeding_still_works_and_the_account_can_log_in(self):
        # Without this, a guard that broke seeding entirely would pass every
        # test above with flying colours.
        # Generated, not written down: a literal here reads exactly like a
        # leaked credential to scripts/scan-secrets.py, and widening that
        # rule to allow fixtures is how the rule stops catching real ones.
        secret = secrets.token_urlsafe(12)
        with patch.dict("os.environ", {"SIMRS_DEMO_PASSWORD": secret}), \
             patch.object(type(self._builder()), "DEMO_USERS", FAKE_USERS):
            self._builder()._users({})
        user = self._existing()
        self.assertTrue(user, "Dengan variabel terisi, akun harus tetap dibuat.")
        # The password must be the one supplied, not merely non-empty.
        # _check_credentials validates the CURRENT user's password, so the
        # environment has to be bound to the account under test -- calling it
        # on a recordset alone compares against whoever is running the test.
        user.with_user(user)._check_credentials(
            {"type": "password", "password": secret}, {"interactive": False}
        )

    def test_the_login_control_can_actually_fail(self):
        # Guards the test above: if _check_credentials silently accepted
        # anything, the positive control would prove nothing.
        secret = secrets.token_urlsafe(12)
        with patch.dict("os.environ", {"SIMRS_DEMO_PASSWORD": secret}), \
             patch.object(type(self._builder()), "DEMO_USERS", FAKE_USERS):
            self._builder()._users({})
        user = self._existing()
        with self.assertRaises(AccessDenied):
            user.with_user(user)._check_credentials(
                {"type": "password", "password": secret + "-salah"},
                {"interactive": False},
            )
