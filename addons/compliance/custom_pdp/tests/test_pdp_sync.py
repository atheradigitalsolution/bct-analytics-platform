# Part of custom_pdp. Licence: LGPL-3.
"""Tests for the dictionary roll-up and the registry->tag projection."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_pdp.models.pdp_classification import (
    CODE_TO_CLASS,
    DEFAULT_CODE_FOR_CLASS,
)
from odoo.addons.custom_pdp.models.pdp_field_classification import PDP_CLASS_KEYS


@tagged("post_install", "-at_install", "pdp")
class TestPdpSync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Registry = cls.env["pdp.field.classification"]
        cls.Dictionary = cls.env["pdp.classification"]

    def _tag_of(self, model, name):
        self.env.cr.execute(
            "SELECT x_pdp_classification_id FROM ir_model_fields "
            "WHERE model = %s AND name = %s",
            (model, name),
        )
        row = self.env.cr.fetchone()
        return row and row[0] or None

    # -- roll-up map ----------------------------------------------------

    def test_every_seeded_code_has_a_rollup(self):
        codes = set(
            self.Dictionary.with_context(active_test=False).search([]).mapped("code")
        )
        unmapped = {c for c in codes if c not in CODE_TO_CLASS}
        self.assertFalse(
            unmapped,
            "dictionary codes without a frozen-class roll-up: %s" % sorted(unmapped),
        )

    def test_rollups_stay_inside_the_frozen_classes(self):
        self.assertFalse(set(CODE_TO_CLASS.values()) - set(PDP_CLASS_KEYS))
        self.assertEqual(set(DEFAULT_CODE_FOR_CLASS), set(PDP_CLASS_KEYS))

    def test_pdp_class_backfilled_on_seed_records(self):
        for rec in self.Dictionary.with_context(active_test=False).search([]):
            if rec.code in CODE_TO_CLASS:
                self.assertEqual(
                    rec.pdp_class,
                    CODE_TO_CLASS[rec.code],
                    "code %r must roll up to %r" % (rec.code, CODE_TO_CLASS[rec.code]),
                )

    # -- projection -----------------------------------------------------

    def test_sync_fills_null_tags_from_registry(self):
        # res.partner.email is classified `personal` in the registry seed.
        self.env.cr.execute(
            "UPDATE ir_model_fields SET x_pdp_classification_id = NULL "
            "WHERE model = 'res.partner' AND name = 'email'"
        )
        self.Dictionary._sync_field_tags()
        tag_id = self._tag_of("res.partner", "email")
        self.assertTrue(tag_id, "sync must fill the NULL tag from the registry")
        tag = self.Dictionary.browse(tag_id)
        self.assertEqual(tag.pdp_class, "personal")
        self.assertEqual(tag.code, DEFAULT_CODE_FOR_CLASS["personal"])

    def test_sync_keeps_finer_grained_tag(self):
        # vat: registry says `sensitive`; the seed tags it `financial`, which
        # rolls up to `sensitive` too. Sync must not coarsen it.
        financial = self.Dictionary.search([("code", "=", "financial")], limit=1)
        self.assertTrue(financial)
        self.env.cr.execute(
            "UPDATE ir_model_fields SET x_pdp_classification_id = %s "
            "WHERE model = 'res.partner' AND name = 'vat'",
            (financial.id,),
        )
        self.Dictionary._sync_field_tags()
        self.assertEqual(self._tag_of("res.partner", "vat"), financial.id)

    def test_sync_never_overwrites_a_conflicting_tag(self):
        # A tag whose roll-up contradicts the registry is logged, not rewritten.
        public = self.Dictionary.search([("code", "=", "public")], limit=1)
        self.env.cr.execute(
            "UPDATE ir_model_fields SET x_pdp_classification_id = %s "
            "WHERE model = 'res.partner' AND name = 'email'",
            (public.id,),
        )
        with self.assertLogs(
            "odoo.addons.custom_pdp.models.pdp_classification", level="WARNING"
        ):
            self.Dictionary._sync_field_tags()
        self.assertEqual(self._tag_of("res.partner", "email"), public.id)

    # -- wizard write-through -------------------------------------------

    def test_wizard_writes_through_to_registry(self):
        model = self.env["ir.model"].search([("model", "=", "res.company")], limit=1)
        field = self.env["ir.model.fields"].search(
            [("model", "=", "res.company"), ("name", "=", "email")], limit=1
        )
        self.assertTrue(model and field)
        pii = self.Dictionary.search([("code", "=", "pii")], limit=1)
        wizard = self.env["pdp.tag.fields.wizard"].create(
            {
                "model_id": model.id,
                "field_ids": [(6, 0, [field.id])],
                "classification_id": pii.id,
            }
        )
        wizard.action_apply()
        row = self.Registry.with_context(active_test=False).search(
            [("model_name", "=", "res.company"), ("field_name", "=", "email")],
            limit=1,
        )
        self.assertTrue(row, "the wizard must upsert the canonical registry row")
        self.assertEqual(row.pdp_class, "personal")
