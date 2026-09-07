# -*- coding: utf-8 -*-
"""Uji fixture NDI.

Sengaja TIDAK menjalankan ``generate()``: satu jalan penuh membuat 336 MO dan 271
PO dan memakan menit, dan uji yang lambat adalah uji yang dimatikan orang. Yang
diuji di sini adalah hal-hal yang benar-benar pernah rusak dan yang bisa rusak
diam-diam: konsistensi berkas sumber terhadap rencana pembelian, pohon UoM yang
harus bisa diselesaikan untuk setiap SKU, dan dua pengaman idempotensi.
"""

import csv

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tools import file_path

from odoo.addons.custom_ndi_data_seed.models.ndi_data_seed import (
    BASE_UOM_XMLID, FIXED_MONTHLY_QTY, MODULE, PO_PLAN, SKU_SUPPLIER,
    TIER2_UOM_XMLID, TIER3_UOM_XMLID, NdiSeedRun, _f, _read_csv,
)


@tagged("post_install", "-at_install", "ndi")
class TestNdiDataSeed(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Seed = cls.env["ndi.data.seed"]
        cls.master = _read_csv("ndi_master_produk.csv")

    # -- berkas sumber --------------------------------------------------

    def test_master_csv_has_52_sku(self):
        self.assertEqual(len(self.master), 52)
        codes = [row["sku"].strip() for row in self.master]
        self.assertEqual(len(set(codes)), 52, "SKU harus unik")

    def test_every_bom_totals_100_percent(self):
        rows = {}
        for row in _read_csv("ndi_bom_formulasi.csv"):
            rows.setdefault(row["produk_sku"].strip(), []).append(row)
        self.assertEqual(len(rows), 12)
        for sku, lines in rows.items():
            total = sum(_f(line, "persen") for line in lines)
            self.assertAlmostEqual(total, 100.0, places=2, msg="formula %s" % sku)

    def test_bom_materials_exist_in_master(self):
        known = {row["sku"].strip() for row in self.master}
        for row in _read_csv("ndi_bom_formulasi.csv"):
            self.assertIn(row["bahan_sku"].strip(), known)

    def test_purchase_plan_covers_every_sku_it_names(self):
        """Setiap SKU di rencana pembelian harus punya kuantitas yang bisa dihitung.

        Sebuah SKU yang tidak muncul di satu pun BOM dan juga tidak punya
        ``FIXED_MONTHLY_QTY`` akan dibeli sebanyak nol lalu dinaikkan ke satu unit.
        Itu persis bentuk cacat yang pernah terjadi (seluruh baris PO berkuantitas
        1,00) dan gejalanya bukan galat melainkan produksi yang gagal direservasi
        sebelas langkah kemudian.
        """
        bom_materials = {row["bahan_sku"].strip() for row in _read_csv("ndi_bom_formulasi.csv")}
        packaging = {"PK-KRG-50N", "PK-KRG-30N", "PK-INN-50", "PK-INN-30",
                     "PK-LBL-01", "PK-BNG-01"}
        for _key, _supplier, lines in PO_PLAN:
            for sku, _share in lines:
                self.assertTrue(
                    sku in bom_materials or sku in packaging or sku in FIXED_MONTHLY_QTY,
                    "%s tidak punya sumber kuantitas apa pun" % sku,
                )

    def test_purchase_plan_has_22_orders_per_month(self):
        self.assertEqual(len(PO_PLAN), 22)

    def test_every_purchased_sku_has_a_supplier(self):
        for _key, _supplier, lines in PO_PLAN:
            for sku, _share in lines:
                self.assertIn(sku, SKU_SUPPLIER)

    def test_purchase_plan_suppliers_exist_in_csv(self):
        known = {row["kode"].strip() for row in _read_csv("ndi_supplier.csv")}
        for _key, supplier, _lines in PO_PLAN:
            self.assertIn(supplier, known)

    # -- pohon UoM ------------------------------------------------------

    def test_every_sku_resolves_its_uom_tree(self):
        """Termasuk tiga arti berbeda dari "TON".

        20 sak 50 KG = 1.000 kg, 20 sak 30 KG = 600 kg, 50 sak sekam = 1.000 kg.
        Satu record TON akan membuat berat surat jalan puyuh meleset 400 kg per
        ton, dan tidak ada satu pun angka di layar yang tampak salah.
        """
        run = NdiSeedRun(self.env, self.env.company, {"prefix": "unittest__"},
                         {"seed": 1}, self.env.cr.now().date(), commit=False)
        for row in self.master:
            base, tier2, tier3 = run._uom_tree(row)
            self.assertTrue(base, row["sku"])
            if row["satuan2"].strip():
                self.assertTrue(tier2, row["sku"])
                self.assertAlmostEqual(
                    tier2.relative_factor, _f(row, "konversi2"), places=4, msg=row["sku"])
            if row["satuan3"].strip():
                self.assertTrue(tier3, row["sku"])
                self.assertAlmostEqual(
                    tier3.relative_factor, _f(row, "konversi3"), places=4, msg=row["sku"])

    def test_uom_xmlids_all_resolve(self):
        for xmlid in list(BASE_UOM_XMLID.values()) + list(TIER2_UOM_XMLID.values()) \
                + list(TIER3_UOM_XMLID.values()):
            self.assertTrue(self.env.ref(xmlid, raise_if_not_found=False), xmlid)

    # -- pengaman idempotensi -------------------------------------------

    def test_dataset_name_is_matched_exactly(self):
        for bad in ("Prod", "", "prod_1", "1prod", None if False else "a" * 25):
            with self.assertRaises(UserError, msg=repr(bad)):
                self.Seed._dataset_context(bad)
        self.assertEqual(self.Seed._dataset_context("prod")["prefix"], "prod__")

    def test_shape_conflict_is_refused(self):
        """Bentuk berbeda untuk dataset yang sama harus menolak, bukan diam.

        Ini pengaman yang membuat idempotensi lewat external ID tidak berbahaya:
        tanpanya ``generate(months=3)`` di atas dataset 12 bulan mengembalikan 12
        bulan, diam-diam, dan pemanggilnya tidak punya cara tahu.
        """
        ds = self.Seed._dataset_context("unittest")
        self.env["ir.config_parameter"].sudo().set_param(
            "custom_ndi_data_seed.shape.unittest",
            '{"seed": 1, "months": 12, "company_id": %d}' % self.env.company.id,
        )
        with self.assertRaises(UserError):
            self.Seed._assert_shape(ds, {key: 0 for key in (
                "seed", "start", "months", "mo_per_month", "po_per_month",
                "so_per_month", "pos_orders", "transfers_per_month", "draft_mo",
                "waste_mo", "partial_receipts", "company_id")})

    def test_generate_refuses_a_purchase_plan_size_it_cannot_honour(self):
        with self.assertRaises(UserError):
            self.Seed.generate(po_per_month=5, dataset="unittest", commit=False)

    # -- klasifikasi PDP -------------------------------------------------

    def test_new_columns_are_classified(self):
        """Kolom ``ndi_*`` yang direplikasi harus punya klasifikasi PDP.

        ``up-analytics`` menolak kolom tanpa klasifikasi, dan itu perilaku benar.
        Uji ini menangkap field baru yang ditambahkan tanpa baris seed-nya, di
        sini, alih-alih berjam-jam kemudian di terminal orang lain.
        """
        Classification = self.env["pdp.field.classification"]
        # ``ttype NOT IN (one2many, many2many)``: registri PDP mengklasifikasi
        # KOLOM fisik. Sebuah one2many berstatus ``store`` di ir_model_fields tetapi
        # tidak punya kolom sama sekali -- ia adalah pandangan terbalik dari kolom
        # di tabel lain, dan tidak ada yang bisa direplikasi darinya.
        self.env.cr.execute("""
            SELECT f.model, f.name FROM ir_model_fields f
             WHERE f.name LIKE 'ndi\\_%' AND f.store IS TRUE
               AND f.ttype NOT IN ('one2many', 'many2many')
               AND f.model IN ('res.partner', 'product.template', 'sale.order.line',
                               'pos.order.line', 'product.pricelist', 'mrp.bom',
                               'mrp.bom.line', 'uom.uom')
        """)
        for model_name, field_name in self.env.cr.fetchall():
            self.assertTrue(
                Classification.search_count(
                    [("model_name", "=", model_name), ("field_name", "=", field_name)]),
                "%s.%s belum diklasifikasi di custom_pdp_core" % (model_name, field_name),
            )
