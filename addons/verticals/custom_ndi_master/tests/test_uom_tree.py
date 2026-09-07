# -*- coding: utf-8 -*-
"""Pohon UoM feed mill di Odoo 19 (keputusan D2).

Bukan port dari Odoo 17: ``uom.category`` dan ``factor_inv`` tidak ada lagi, dan
konversi hanya sah bila dua satuan berbagi akar pohon.
"""

from odoo.tests import tagged

from .common import NdiSampleCase


@tagged("post_install", "-at_install", "ndi")
class TestUomTree(NdiSampleCase):

    def test_kg_sak_ton_absolute_factors(self):
        kg = self.env.ref("uom.product_uom_kgm")
        sak = self.env.ref("custom_ndi_master.uom_sak_50kg")
        ton = self.env.ref("custom_ndi_master.uom_ton_20sak_50kg")

        self.assertEqual(sak.relative_uom_id, kg)
        self.assertEqual(sak.relative_factor, 50.0)
        self.assertEqual(ton.relative_uom_id, sak)
        self.assertEqual(ton.relative_factor, 20.0)

        # `factor` rekursif sampai akar pohon (gram), jadi rasionya yang bermakna.
        self.assertAlmostEqual(sak.factor / kg.factor, 50.0, places=6)
        self.assertAlmostEqual(ton.factor / sak.factor, 20.0, places=6)
        self.assertAlmostEqual(ton.factor / kg.factor, 1000.0, places=6)

    def test_conversion_kg_sak_ton_round_trip(self):
        kg = self.env.ref("uom.product_uom_kgm")
        sak = self.env.ref("custom_ndi_master.uom_sak_50kg")
        ton = self.env.ref("custom_ndi_master.uom_ton_20sak_50kg")

        self.assertAlmostEqual(kg._compute_quantity(1000.0, sak, round=False), 20.0, places=6)
        self.assertAlmostEqual(kg._compute_quantity(1000.0, ton, round=False), 1.0, places=6)
        self.assertAlmostEqual(sak._compute_quantity(20.0, ton, round=False), 1.0, places=6)
        self.assertAlmostEqual(ton._compute_quantity(3.0, kg, round=False), 3000.0, places=6)
        self.assertAlmostEqual(ton._compute_quantity(3.0, sak, round=False), 60.0, places=6)

        # Bolak-balik tanpa kebocoran.
        self.assertAlmostEqual(
            sak._compute_quantity(kg._compute_quantity(750.0, sak, round=False), kg, round=False),
            750.0,
            places=6,
        )

    def test_sak_30kg_ton_is_600_kg_not_1000(self):
        """"TON" pada data NDI berarti 20 sak, bukan tonne metrik.

        Untuk pakan puyuh dan kambing yang dikarungi 30 kg, satu "TON" adalah
        600 kg. Kalau satu record TON dipakai bersama, surat jalan salah 400 kg.
        """
        kg = self.env.ref("uom.product_uom_kgm")
        ton_30 = self.env.ref("custom_ndi_master.uom_ton_20sak_30kg")
        ton_50 = self.env.ref("custom_ndi_master.uom_ton_20sak_50kg")

        self.assertAlmostEqual(ton_30._compute_quantity(1.0, kg, round=False), 600.0, places=6)
        self.assertAlmostEqual(ton_50._compute_quantity(1.0, kg, round=False), 1000.0, places=6)
        self.assertNotEqual(ton_30, ton_50)

    def test_counting_roots_are_isolated_from_each_other(self):
        """BTL tidak bisa dikonversi ke SCH: keduanya akar terpisah."""
        btl = self.env.ref("custom_ndi_master.uom_btl")
        sch = self.env.ref("custom_ndi_master.uom_sch")
        pcs = self.env.ref("custom_ndi_master.uom_pcs")
        dus_btl = self.env.ref("custom_ndi_master.uom_dus_12btl")

        self.assertFalse(btl._has_common_reference(sch))
        self.assertFalse(btl._has_common_reference(pcs))
        self.assertTrue(btl._has_common_reference(dus_btl))
        self.assertAlmostEqual(dus_btl._compute_quantity(1.0, btl, round=False), 12.0, places=6)

    def test_ndi_tier_reflects_tree_depth(self):
        self.assertEqual(self.env.ref("custom_ndi_master.uom_pcs").ndi_tier, 1)
        self.assertEqual(self.env.ref("custom_ndi_master.uom_bal_1000pcs").ndi_tier, 2)
        # kg beranak ke gram, jadi kg tingkat 2 dan SAK 50 KG tingkat 3.
        self.assertEqual(self.env.ref("custom_ndi_master.uom_sak_50kg").ndi_tier, 3)
        self.assertEqual(self.env.ref("custom_ndi_master.uom_ton_20sak_50kg").ndi_tier, 4)

    def test_sample_products_carry_their_packaging_uoms(self):
        """Setiap produk sampel bisa ditransaksikan pada tiap tingkat satuannya."""
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            allowed = template.uom_id | template.uom_ids
            expected_levels = 1 + bool(row["satuan2"]) + bool(row["satuan3"])
            self.assertEqual(
                len(allowed),
                expected_levels,
                "%s harus punya %d tingkat satuan, dapat %s"
                % (row["sku"], expected_levels, allowed.mapped("name")),
            )

    def test_gross_weight_per_uom_beats_base_unit_weight(self):
        """Pasal 18: berat gross satu sak pakan bukan 50 kg, tapi 50,148 kg."""
        template = self.products_by_sku["FG-BRS-01"]
        sak = self.env.ref("custom_ndi_master.uom_sak_50kg")
        ton = self.env.ref("custom_ndi_master.uom_ton_20sak_50kg")

        row = next(r for r in self.sample_rows if r["sku"] == "FG-BRS-01")
        self.assertEqual(row["berat_satuan2_kg"], "50.148")
        self.assertAlmostEqual(
            template.ndi_gross_weight_for_uom(sak), float(row["berat_satuan2_kg"]), places=3
        )
        self.assertAlmostEqual(
            template.ndi_gross_weight_for_uom(ton), float(row["berat_satuan3_kg"]), places=3
        )

        # Netto dari factor UoM saja akan memberi 50 kg — inilah yang tidak cukup.
        netto = sak._compute_quantity(1.0, template.uom_id, round=False) * template.weight
        self.assertAlmostEqual(netto, 50.0, places=3)
        self.assertGreater(template.ndi_gross_weight_for_uom(sak), netto)

    def test_gross_weight_falls_back_when_no_row_exists(self):
        template = self.products_by_sku["FG-BRS-01"]
        drum = self.env.ref("custom_ndi_master.uom_drum_200kg")
        self.assertFalse(template.ndi_uom_weight_ids.filtered(lambda w: w.uom_id == drum))
        self.assertAlmostEqual(template.ndi_gross_weight_for_uom(drum), 200.0, places=3)
