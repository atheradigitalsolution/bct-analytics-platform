# -*- coding: utf-8 -*-
"""Batas Harga 1-3 untuk kasir benar-benar menyaring, bukan sekadar terpasang.

Uji ini membuat pengguna nyata dan membaca lewat ``with_user``, bukan memeriksa
bahwa record ``ir.rule`` ada. Rule yang salah domain juga "ada".
"""

from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.custom_ndi_master.tests.common import NdiSampleCase


@tagged("post_install", "-at_install", "ndi")
class TestPriceTierRule(NdiSampleCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.levels = cls.env["product.pricelist"]._ndi_pricelist_by_level()
        cls.cashier = cls._make_user("kasir.ndi", "custom_ndi_pricing.ndi_group_price_1_3")
        cls.owner = cls._make_user("owner.ndi", "custom_ndi_pricing.ndi_group_price_1_9")

    @classmethod
    def _make_user(cls, login, group_xmlid):
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, cls.env.ref(group_xmlid).id),
                ],
            }
        )

    def _visible_levels(self, user):
        pricelists = self.env["product.pricelist"].with_user(user).search(
            [("ndi_hj_level", "!=", False)]
        )
        return sorted(pricelists.mapped("ndi_hj_level"))

    def test_cashier_sees_only_levels_1_to_3(self):
        self.assertEqual(self._visible_levels(self.cashier), [1, 2, 3])

    def test_owner_sees_all_nine_levels(self):
        self.assertEqual(self._visible_levels(self.owner), list(range(1, 10)))

    def test_cashier_cannot_read_a_hidden_pricelist_even_by_id(self):
        """Batasnya di lapisan record, jadi menebak id pun tidak menolong."""
        hidden = self.levels[7]
        with self.assertRaises(AccessError):
            hidden.with_user(self.cashier).read(["name"])

    def test_cashier_can_still_read_an_allowed_pricelist_by_id(self):
        allowed = self.levels[2]
        self.assertTrue(allowed.with_user(self.cashier).read(["name"]))

    def test_non_ndi_pricelists_stay_visible_to_the_cashier(self):
        """Menyembunyikan pricelist di luar matriks akan mematikan terminal POS lama."""
        plain = self.env["product.pricelist"].create({"name": "Pricelist Non-NDI"})
        self.assertFalse(plain.ndi_hj_level)
        self.assertTrue(plain.with_user(self.cashier).read(["name"]))

    def test_rule_applies_to_the_pos_loading_path(self):
        """POS memuat pricelist lewat ``_filtered_access('read')``.

        Diuji melalui API yang sama yang dipakai POS, bukan lewat ``search``
        biasa — inilah yang membedakan batas nyata dari batas kosmetik.
        """
        all_ndi = self.env["product.pricelist"].search([("ndi_hj_level", "!=", False)])
        readable = all_ndi.with_user(self.cashier)._filtered_access("read")
        self.assertEqual(sorted(readable.mapped("ndi_hj_level")), [1, 2, 3])

        readable_owner = all_ndi.with_user(self.owner)._filtered_access("read")
        self.assertEqual(sorted(readable_owner.mapped("ndi_hj_level")), list(range(1, 10)))

    def test_pricelist_level_is_unique(self):
        from odoo.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self.env["product.pricelist"].create({"name": "Harga 3 Duplikat", "ndi_hj_level": 3})
