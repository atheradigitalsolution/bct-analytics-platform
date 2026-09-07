# -*- coding: utf-8 -*-
"""Field master pasal 5 dan penjaganya."""

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import NdiSampleCase


@tagged("post_install", "-at_install", "ndi")
class TestMasterFields(NdiSampleCase):

    def test_jenis_produk_distribution_matches_sample(self):
        counts = {}
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            self.assertEqual(template.ndi_jenis_produk, row["jenis"])
            counts[row["jenis"]] = counts.get(row["jenis"], 0) + 1
        self.assertEqual(
            counts,
            {"bahan_baku": 27, "kemasan": 8, "produk_jadi": 12, "barang_dagangan": 5},
        )

    def test_division_and_category_are_linked(self):
        template = self.products_by_sku["FG-BRS-01"]
        self.assertEqual(template.ndi_divisi_id.name, "Pakan Unggas")
        self.assertEqual(template.ndi_kategori_id.name, "Pakan Komplit Broiler")
        self.assertEqual(template.ndi_kategori_id.division_id, template.ndi_divisi_id)

    def test_category_from_another_division_is_refused(self):
        template = self.products_by_sku["FG-BRS-01"]
        other = self.env["ndi.product.category"].search(
            [("division_id", "!=", template.ndi_divisi_id.id), ("division_id", "!=", False)],
            limit=1,
        )
        self.assertTrue(other, "Butuh kategori dari divisi lain untuk menguji penjaganya.")
        with self.assertRaises(ValidationError):
            template.ndi_kategori_id = other

    def test_stock_bounds_order_is_enforced(self):
        template = self.products_by_sku["FG-BRS-01"]
        with self.assertRaises(ValidationError):
            template.write({"ndi_stok_min": 9_000_000.0, "ndi_stok_maks": 1.0})

    def test_stock_bounds_loaded_from_sample(self):
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            self.assertAlmostEqual(template.ndi_stok_min, float(row["stok_min"]), places=2)
            self.assertAlmostEqual(template.ndi_stok_maks, float(row["stok_maks"]), places=2)
            self.assertLessEqual(template.ndi_stok_min, template.ndi_stok_maks)

    def test_uom_weight_rejects_uom_outside_product(self):
        template = self.products_by_sku["FG-BRS-01"]
        stray = self.env.ref("custom_ndi_master.uom_dus_12btl")
        with self.assertRaises(ValidationError):
            self.env["ndi.product.uom.weight"].create(
                {
                    "product_tmpl_id": template.id,
                    "uom_id": stray.id,
                    "gross_weight": 1.0,
                }
            )

    @mute_logger("odoo.sql_db")
    def test_uom_weight_is_unique_per_product_and_uom(self):
        template = self.products_by_sku["FG-BRS-01"]
        sak = self.env.ref("custom_ndi_master.uom_sak_50kg")
        with self.assertRaises(Exception):
            with self.cr.savepoint():
                self.env["ndi.product.uom.weight"].create(
                    {
                        "product_tmpl_id": template.id,
                        "uom_id": sak.id,
                        "gross_weight": 99.0,
                    }
                )
                self.env.flush_all()

    def test_gross_weight_rows_match_sample_to_the_gram(self):
        """Berat gross disimpan 3 desimal; 50,148 kg tidak boleh jadi 50,15."""
        checked = 0
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            for index, uom in enumerate(template.uom_id | template.uom_ids, start=1):
                raw = row["berat_satuan%d_kg" % index]
                if not raw:
                    continue
                line = template.ndi_uom_weight_ids.filtered(lambda w, u=uom: w.uom_id == u)
                self.assertEqual(len(line), 1, "%s %s" % (row["sku"], uom.name))
                self.assertAlmostEqual(
                    line.gross_weight,
                    float(raw),
                    places=3,
                    msg="Berat gross %s pada %s meleset" % (row["sku"], uom.name),
                )
                checked += 1
        self.assertGreaterEqual(checked, 100)
