# -*- coding: utf-8 -*-
"""The service the platform calls, and the two ways it refuses."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestObjectStorage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Storage = cls.env["custom.object.storage"]
        cls.Config = cls.env["custom.adapter.config"]
        cls.env["ir.config_parameter"].sudo().set_param(
            "r2.test.secret", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")

    def _config(self, **over):
        vals = {
            "name": "R2 Test",
            "adapter_type": "s3_compatible",
            # R2 addresses the bucket in the path, which is why the host is the account
            # endpoint and not <bucket>.<host>.
            "base_url": "https://abc123.r2.cloudflarestorage.com",
            "auth_method": "none",
            "credential_ref": "r2.test.secret",
            "x_s3_bucket": "athera-booth",
            "x_s3_region": "auto",
            # Assembled, not written out: see test_s3_presign for why.
            "x_s3_access_key_id": "AKIA" + "IOSFODNN7EXAMPLE",
            "status": "active",
        }
        vals.update(over)
        return self.Config.create(vals)

    # ---------- signing through the service ----------

    def test_presign_put_returns_a_url_key_and_an_explicit_expiry(self):
        """The expiry is returned, not implied: an offline queue has to check it."""
        cfg = self._config()
        self.env.company.x_object_storage_config_id = cfg
        out = self.Storage.presign_put("spk/SPK-2026-0001/progress/a.jpg")
        self.assertIn("X-Amz-Signature=", out["url"])
        self.assertEqual(out["method"], "PUT")
        self.assertEqual(out["key"], "spk/SPK-2026-0001/progress/a.jpg")
        self.assertTrue(out["expires_at"], "a queue cannot ask whether a URL is dead")
        self.assertEqual(out["expires_in"], 900)

    def test_the_bucket_goes_in_the_path_for_r2(self):
        cfg = self._config()
        self.env.company.x_object_storage_config_id = cfg
        out = self.Storage.presign_get("survey/front.jpg")
        self.assertIn("/athera-booth/survey/front.jpg?", out["url"])

    def test_a_subdomain_endpoint_does_not_repeat_the_bucket(self):
        """Some providers put the bucket in the host; doubling it signs a 404."""
        cfg = self._config(base_url="https://athera-booth.s3.example.com")
        self.env.company.x_object_storage_config_id = cfg
        out = self.Storage.presign_get("survey/front.jpg")
        self.assertIn("/survey/front.jpg?", out["url"])
        self.assertNotIn("/athera-booth/survey/front.jpg", out["url"])

    def test_read_and_write_urls_differ(self):
        cfg = self._config()
        self.env.company.x_object_storage_config_id = cfg
        put = self.Storage.presign_put("x.jpg")["url"]
        get = self.Storage.presign_get("x.jpg")["url"]
        self.assertNotEqual(put, get, "a read URL must not be able to write")

    # ---------- keys ----------

    def test_build_key_produces_something_readable_in_the_bucket(self):
        """The only structure a key has is the structure put in it deliberately."""
        key = self.Storage.build_key("spk", "SPK/2026/0001", "survey", "front photo.jpg")
        self.assertEqual(key, "spk/SPK-2026-0001/survey/front_photo.jpg")

    def test_build_key_skips_empty_parts(self):
        self.assertEqual(self.Storage.build_key("spk", "", None, "a.jpg"), "spk/a.jpg")

    # ---------- how it refuses ----------

    def test_no_configuration_is_an_error_with_a_reason(self):
        self.env.company.x_object_storage_config_id = False
        self.Config.search([("adapter_type", "=", "s3_compatible")]).write(
            {"status": "disabled"})
        with self.assertRaises(UserError):
            self.Storage.presign_get("x.jpg")

    def test_incomplete_configuration_is_refused_at_save(self):
        with self.assertRaises(ValidationError):
            self._config(x_s3_bucket=False)

    def test_an_expiry_beyond_seven_days_is_refused(self):
        """S3 refuses it, and a week is a standing grant rather than a link."""
        with self.assertRaises(ValidationError):
            self._config(x_s3_default_expiry_s=8 * 24 * 3600)

    def test_a_zero_expiry_is_refused(self):
        with self.assertRaises(ValidationError):
            self._config(x_s3_default_expiry_s=0)

    # ---------- health check ----------

    def test_health_check_signs_without_touching_the_network(self):
        """A check that needs the internet fails for unrelated reasons and gets ignored."""
        cfg = self._config()
        self.env.company.x_object_storage_config_id = cfg
        adapter = self.Storage._adapter()
        response = adapter.health_check()
        self.assertTrue(response.ok, response.error)
        self.assertEqual(response.data.get("bucket"), "athera-booth")

    def test_health_check_fails_loudly_with_no_secret(self):
        cfg = self._config(credential_ref="r2.missing.secret")
        self.env.company.x_object_storage_config_id = cfg
        response = self.Storage._adapter().health_check()
        self.assertFalse(response.ok)
        self.assertIn("no secret", response.error)
