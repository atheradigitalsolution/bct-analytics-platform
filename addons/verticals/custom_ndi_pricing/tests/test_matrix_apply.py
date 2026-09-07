# -*- coding: utf-8 -*-
"""Penerapan matriks ke pricelist: benar, dan boleh diulang.

Idempotensi diuji dengan hitungan baris ``product.pricelist.item``, bukan dengan
"tidak ada error". Menjalankan dua kali dan tidak meledak adalah hal yang juga
dilakukan implementasi yang menggandakan aturan.
"""

from odoo.tests import tagged

from odoo.addons.custom_ndi_master.tests.common import NdiSampleCase

TOLERANCE = 0.01


@tagged("post_install", "-at_install", "ndi")
class TestPriceMatrixApply(NdiSampleCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.matrices = cls.env["ndi.price.matrix"]._ndi_sync_from_products(
            cls.env["product.template"].browse([t.id for t in cls.products_by_sku.values()])
        )
        cls.levels = cls.env["product.pricelist"]._ndi_pricelist_by_level()

    def _items(self):
        return self.env["product.pricelist.item"].search(
            [
                ("pricelist_id", "in", [p.id for p in self.levels.values()]),
                ("product_tmpl_id", "in", self.matrices.product_tmpl_id.ids),
            ]
        )

    def test_nine_pricelists_exist_one_per_level(self):
        self.assertEqual(sorted(self.levels), list(range(1, 10)))
        for level, pricelist in self.levels.items():
            self.assertEqual(pricelist.ndi_hj_level, level)

    def test_apply_writes_nine_fixed_items_per_product(self):
        self.matrices.action_apply()
        items = self._items()
        self.assertEqual(len(items), 9 * len(self.matrices))
        self.assertEqual(set(items.mapped("compute_price")), {"fixed"})
        self.assertEqual(set(items.mapped("applied_on")), {"1_product"})
        # Rantai base_pricelist_id sengaja tidak dipakai: tidak boleh ada satu pun
        # aturan yang bergantung pada tingkat lain saat runtime.
        self.assertEqual(set(items.mapped("base")), {"list_price"})
        self.assertFalse(any(items.mapped("base_pricelist_id")))
        self.assertEqual(set(self.matrices.mapped("state")), {"applied"})

    def test_applied_prices_equal_the_sample_csv(self):
        self.matrices.action_apply()
        mismatches = []
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            for level in range(1, 10):
                item = self.env["product.pricelist.item"].search(
                    [
                        ("pricelist_id", "=", self.levels[level].id),
                        ("product_tmpl_id", "=", template.id),
                    ]
                )
                self.assertEqual(len(item), 1, "%s HJ%d" % (row["sku"], level))
                expected = float(row["hj%d" % level])
                if abs(item.fixed_price - expected) > TOLERANCE:
                    mismatches.append(
                        "%s HJ%d: pricelist=%.2f CSV=%.2f"
                        % (row["sku"], level, item.fixed_price, expected)
                    )
        self.assertFalse(mismatches, "Harga di pricelist menyimpang dari CSV:\n  " + "\n  ".join(mismatches))

    def test_apply_twice_does_not_duplicate_items(self):
        self.matrices.action_apply()
        first_ids = set(self._items().ids)
        self.assertEqual(len(first_ids), 9 * len(self.matrices))

        self.matrices.action_apply()
        second_ids = set(self._items().ids)

        self.assertEqual(len(second_ids), len(first_ids), "Jalan kedua menggandakan aturan harga.")
        self.assertEqual(second_ids, first_ids, "Jalan kedua membuat record baru, bukan memperbarui.")

        self.matrices.action_apply()
        self.assertEqual(set(self._items().ids), first_ids, "Jalan ketiga menggandakan aturan harga.")

    def test_apply_refreshes_price_after_component_change(self):
        template = self.products_by_sku["FG-BRS-01"]
        matrix = self.matrices.filtered(lambda m: m.product_tmpl_id == template)
        matrix.action_apply()
        item = self.env["product.pricelist.item"].search(
            [("pricelist_id", "=", self.levels[1].id), ("product_tmpl_id", "=", template.id)]
        )
        before = item.fixed_price

        template.ndi_margin_het_rp = template.ndi_margin_het_rp + 250.0
        matrix.action_apply()

        item = self.env["product.pricelist.item"].search(
            [("pricelist_id", "=", self.levels[1].id), ("product_tmpl_id", "=", template.id)]
        )
        self.assertEqual(len(item), 1, "Penyegaran harga tidak boleh membuat aturan kedua.")
        self.assertAlmostEqual(item.fixed_price, before + 250.0, delta=TOLERANCE)

    def test_sync_is_idempotent_too(self):
        templates = self.env["product.template"].browse(
            [t.id for t in self.products_by_sku.values()]
        )
        before = self.env["ndi.price.matrix"].search_count([])
        self.env["ndi.price.matrix"]._ndi_sync_from_products(templates)
        self.assertEqual(self.env["ndi.price.matrix"].search_count([]), before)

    def test_apply_records_a_log_entry(self):
        template = self.products_by_sku["FG-KSL-01"]
        matrix = self.matrices.filtered(lambda m: m.product_tmpl_id == template)
        before = self.env["ndi.price.matrix.log"].search_count([("matrix_id", "=", matrix.id)])
        matrix.action_apply()
        logs = self.env["ndi.price.matrix.log"].search([("matrix_id", "=", matrix.id)])
        self.assertEqual(len(logs), before + 1)
        snapshot = logs[0].values
        self.assertAlmostEqual(snapshot["hj1"], template.ndi_hj1, delta=TOLERANCE)
        self.assertAlmostEqual(snapshot["hpp_dasar"], template.ndi_hpp_dasar, delta=TOLERANCE)
        self.assertEqual(snapshot["sku"], "FG-KSL-01")

    def test_price_engine_returns_the_matrix_price(self):
        """Bukti bahwa Odoo — bukan modul ini — yang menerapkan harga saat transaksi."""
        self.matrices.action_apply()
        template = self.products_by_sku["FG-BRS-01"]
        product = template.product_variant_id
        row = next(r for r in self.sample_rows if r["sku"] == "FG-BRS-01")
        for level in (1, 3, 5, 9):
            price = self.levels[level]._get_product_price(product, 1.0)
            self.assertAlmostEqual(
                price,
                float(row["hj%d" % level]),
                delta=TOLERANCE,
                msg="Mesin harga Odoo pada Harga %d tidak mengembalikan nilai matriks." % level,
            )
