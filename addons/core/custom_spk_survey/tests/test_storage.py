# -*- coding: utf-8 -*-
"""The object-storage mixin, exercised through the document that inherits it.

These tests live here rather than in custom_object_storage because that module has no
business depending on SPK to prove its own mixin works.
"""

from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestStorageMixin(TransactionCase):
    """Exercised through custom.spk.survey, which inherits the mixin."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "r2.mixin.secret", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
        cls.cfg = cls.env["custom.adapter.config"].create({
            "name": "R2 Mixin Test", "adapter_type": "s3_compatible",
            "base_url": "https://abc123.r2.cloudflarestorage.com",
            "auth_method": "none", "credential_ref": "r2.mixin.secret",
            "x_s3_bucket": "athera-booth", "x_s3_region": "auto",
            "x_s3_access_key_id": "AKIAIOSFODNN7EXAMPLE", "status": "active",
        })
        cls.env.company.x_object_storage_config_id = cls.cfg

    def _survey(self):
        partner = self.env["res.partner"].create({"name": "Klien"})
        spk = self.env["custom.spk"].create(
            {"partner_id": partner.id, "event_name": "GIIAS"})
        spk.action_confirm()
        return self.env["custom.spk.survey"].create({
            "spk_id": spk.id, "venue_name": "JCC Senayan",
            "ceiling_height_m": 4.0, "access_width_m": 2.2,
        })

    def test_a_record_with_no_key_offers_no_url(self):
        s = self._survey()
        self.assertFalse(s.has_storage_file)
        self.assertFalse(s.storage_url)

    def test_requesting_an_upload_records_where_it_will_land(self):
        s = self._survey()
        out = s.action_request_upload("front.jpg")
        self.assertTrue(out["url"].startswith("https://"))
        self.assertEqual(s.storage_key, out["key"])
        self.assertIn(s.spk_id.name.replace("/", "-"), s.storage_key)
        self.assertTrue(s.storage_key.endswith("front.jpg"))

    def test_the_url_is_signed_on_read_and_not_stored(self):
        s = self._survey()
        s.action_request_upload("front.jpg")
        self.assertIn("X-Amz-Signature=", s.storage_url)
        # storage_url is computed and non-stored, so there is no column holding a URL
        # that outlives the record's access rules.
        self.assertFalse(self.env["custom.spk.survey"]._fields["storage_url"].store)

    def test_clearing_forgets_the_reference_without_deleting_the_object(self):
        s = self._survey()
        s.action_request_upload("front.jpg")
        s.action_clear_storage()
        self.assertFalse(s.storage_key)

    def test_clearing_nothing_is_an_error(self):
        with self.assertRaises(UserError):
            self._survey().action_clear_storage()

    def test_a_missing_configuration_does_not_make_records_unreadable(self):
        s = self._survey()
        s.action_request_upload("front.jpg")
        self.env.company.x_object_storage_config_id = False
        self.cfg.status = "disabled"
        s.invalidate_recordset()
        self.assertFalse(s.storage_url, "no URL, but the record still reads")
        self.assertTrue(s.storage_key, "and the key is not lost")
