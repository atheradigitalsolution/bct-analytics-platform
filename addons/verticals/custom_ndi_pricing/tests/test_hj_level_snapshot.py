# -*- coding: utf-8 -*-
"""``ndi_hj_level`` benar-benar tersimpan di baris transaksi.

Tanpa kolom ini, pasal 4 dan pasal 24 tidak punya sumbu pengelompokan sama
sekali — ``sale.order.line.pricelist_item_id`` tidak stored di Odoo 19.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.custom_ndi_master.tests.common import NdiSampleCase

TOLERANCE = 0.01


@tagged("post_install", "-at_install", "ndi")
class TestHjLevelSnapshot(NdiSampleCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.levels = cls.env["product.pricelist"]._ndi_pricelist_by_level()
        cls.env["ndi.price.matrix"]._ndi_sync_from_products(
            cls.env["product.template"].browse([t.id for t in cls.products_by_sku.values()])
        ).action_apply()
        cls.template = cls.products_by_sku["FG-BRS-01"]
        cls.product = cls.template.product_variant_id
        cls.row = next(r for r in cls.sample_rows if r["sku"] == "FG-BRS-01")

    def _make_partner(self, level):
        return self.env["res.partner"].create(
            {"name": "Peternak Uji HJ%d" % level, "ndi_default_hj_level": level}
        )

    def test_field_is_a_real_stored_column(self):
        self.assertTrue(self.env["sale.order.line"]._fields["ndi_hj_level"].store)
        self.assertTrue(self.env["pos.order.line"]._fields["ndi_hj_level"].store)
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sale_order_line' AND column_name = 'ndi_hj_level'"
        )
        self.assertEqual(self.env.cr.rowcount, 1, "Kolom ndi_hj_level tidak ada di sale_order_line.")
        # Pembanding: yang inilah yang TIDAK ada, dan karena itu field kita perlu.
        self.env.cr.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'sale_order_line' AND column_name = 'pricelist_item_id'"
        )
        self.assertEqual(
            self.env.cr.rowcount, 0, "pricelist_item_id ternyata stored; asumsi desain berubah."
        )

    def test_sale_order_line_stamps_the_level_from_the_pricelist(self):
        for level in (1, 3, 5, 9):
            order = self.env["sale.order"].create(
                {
                    "partner_id": self._make_partner(level).id,
                    "pricelist_id": self.levels[level].id,
                    "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 2.0})],
                }
            )
            line = order.order_line
            self.assertEqual(
                line.ndi_hj_level,
                str(level),
                "Baris pada pricelist Harga %d tidak menyimpan tingkatnya." % level,
            )
            self.assertAlmostEqual(
                line.price_unit, float(self.row["hj%d" % level]), delta=TOLERANCE
            )

    def test_level_is_persisted_not_recomputed_on_read(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(5).id,
                "pricelist_id": self.levels[5].id,
                "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1.0})],
            }
        )
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT ndi_hj_level FROM sale_order_line WHERE id = %s", (order.order_line.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "5")

    def test_level_freezes_once_the_order_is_confirmed(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(5).id,
                "pricelist_id": self.levels[5].id,
                "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1.0})],
            }
        )
        order.action_confirm()
        line = order.order_line
        self.assertEqual(line.ndi_hj_level, "5")

        # Odoo sendiri sudah menolak penggantian pricelist setelah konfirmasi.
        with self.assertRaises(UserError):
            order.pricelist_id = self.levels[1]

        # Yang benar-benar diuji: kalau ORM diminta menghitung ulang field stored
        # ini pada order yang sudah dikonfirmasi, nilainya tidak boleh berubah.
        self.env.add_to_compute(line._fields["ndi_hj_level"], line)
        line.invalidate_recordset(["ndi_hj_level"])
        self.assertEqual(
            line.ndi_hj_level,
            "5",
            "Perhitungan ulang pada order terkonfirmasi menimpa snapshot tingkat harga.",
        )

    def test_level_follows_pricelist_while_the_order_is_still_draft(self):
        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(5).id,
                "pricelist_id": self.levels[5].id,
                "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1.0})],
            }
        )
        self.assertEqual(order.order_line.ndi_hj_level, "5")
        order.pricelist_id = self.levels[2]
        order.order_line.invalidate_recordset()
        self.assertEqual(
            order.order_line.ndi_hj_level,
            "2",
            "Selama draft, tingkat harus mengikuti harga — kalau tidak, laporan "
            "bertentangan dengan nilai order.",
        )

    def test_hpp_and_components_are_snapshotted(self):
        self.product.standard_price = 7000.0
        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(3).id,
                "pricelist_id": self.levels[3].id,
                "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1.0})],
            }
        )
        line = order.order_line
        self.assertAlmostEqual(line.ndi_hpp_snapshot, 7000.0, delta=TOLERANCE)
        self.assertAlmostEqual(
            line.ndi_hj_components["hpp_dasar"], self.template.ndi_hpp_dasar, delta=TOLERANCE
        )
        order.action_confirm()
        self.product.standard_price = 9999.0
        self.env.flush_all()
        self.assertAlmostEqual(
            line.ndi_hpp_snapshot,
            7000.0,
            delta=TOLERANCE,
            msg="HPP historis ikut bergerak saat biaya produk diubah.",
        )

    def test_hpp_is_snapshotted_in_the_line_unit_not_the_product_unit(self):
        """Regresi: HPP per kg pernah tersimpan apa adanya pada baris per sak.

        `standard_price` dinyatakan dalam satuan referensi produk; `qty` dan
        `price_unit` dinyatakan dalam satuan baris. Pakan NDI berbasis kg dan
        dijual per sak, jadi keduanya berbeda pada hampir setiap baris nyata.
        Tanpa konversi, `qty * ndi_hpp_snapshot` mengalikan jumlah SAK dengan
        biaya per KG: biaya keluar 50 kali terlalu kecil, dan marginnya cuma
        terlihat bagus — tidak mustahil, yang justru membuatnya lolos.

        Terukur pada tenant `ndi` sebelum perbaikan: margin kotor kanal sale
        98,1% melawan kanal POS 17,6%, pada gudang data yang sama.
        """
        sak50 = self.env.ref("custom_ndi_master.uom_sak_50kg")
        self.assertEqual(
            self.product.uom_id,
            self.env.ref("uom.product_uom_kgm"),
            "Fixture ini mengandalkan produk berbasis kg; asumsinya berubah.",
        )
        self.product.standard_price = 7000.0

        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(3).id,
                "pricelist_id": self.levels[3].id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_id": sak50.id,
                        "product_uom_qty": 4.0,
                    })
                ],
            }
        )
        line = order.order_line
        self.assertEqual(line.product_uom_id, sak50)
        self.assertAlmostEqual(
            line.ndi_hpp_snapshot,
            350000.0,
            delta=TOLERANCE,
            msg="HPP per sak harus 7.000/kg * 50 kg, bukan 7.000.",
        )
        # Yang sebenarnya rusak bukan satu angka, melainkan perbandingannya:
        # biaya baris dan subtotal baris harus berada pada satuan yang sama.
        self.assertAlmostEqual(
            line.ndi_hpp_snapshot * line.product_uom_qty,
            1400000.0,
            delta=TOLERANCE,
            msg="qty * HPP tidak sebanding dengan price_subtotal baris ini.",
        )

    def test_changing_the_line_unit_moves_the_snapshot_with_it(self):
        """Satuan baris ada di `@api.depends`, jadi menggantinya bukan diam-diam."""
        sak50 = self.env.ref("custom_ndi_master.uom_sak_50kg")
        sak30 = self.env.ref("custom_ndi_master.uom_sak_30kg")
        self.product.standard_price = 7000.0
        order = self.env["sale.order"].create(
            {
                "partner_id": self._make_partner(3).id,
                "pricelist_id": self.levels[3].id,
                "order_line": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "product_uom_id": sak50.id,
                        "product_uom_qty": 1.0,
                    })
                ],
            }
        )
        line = order.order_line
        self.assertAlmostEqual(line.ndi_hpp_snapshot, 350000.0, delta=TOLERANCE)
        line.product_uom_id = sak30
        self.env.flush_all()
        self.assertAlmostEqual(
            line.ndi_hpp_snapshot,
            210000.0,
            delta=TOLERANCE,
            msg="Mengganti satuan baris mengubah biaya per satuan; snapshot ikut atau salah.",
        )

    def test_pos_line_is_unaffected_because_it_has_no_unit_of_its_own(self):
        """POS memakai satuan referensi produk, jadi konversinya operasi kosong.

        Ditegaskan, bukan diasumsikan: kalau `_ndi_line_uom` bawaan suatu saat
        salah mundur, POS-lah yang diam-diam ikut tergeser.
        """
        session = self._open_pos_session()
        self.product.standard_price = 7000.0
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "company_id": self.env.company.id,
                "partner_id": self._make_partner(3).id,
                "pricelist_id": self.levels[3].id,
                "lines": [
                    (0, 0, {
                        "product_id": self.product.id,
                        "qty": 2.0,
                        "price_unit": 8000.0,
                        "price_subtotal": 16000.0,
                        "price_subtotal_incl": 16000.0,
                    })
                ],
                "amount_tax": 0.0,
                "amount_total": 16000.0,
                "amount_paid": 16000.0,
                "amount_return": 0.0,
            }
        )
        self.assertAlmostEqual(
            order.lines.ndi_hpp_snapshot,
            7000.0,
            delta=TOLERANCE,
            msg="Baris POS tidak punya satuan sendiri; HPP-nya harus apa adanya.",
        )

    def test_partner_default_level_drives_the_pricelist(self):
        partner = self._make_partner(4)
        self.assertEqual(partner.property_product_pricelist, self.levels[4])
        order = self.env["sale.order"].create({"partner_id": partner.id})
        self.assertEqual(order.pricelist_id, self.levels[4])
        order.write({"order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": 1.0})]})
        self.assertEqual(order.order_line.ndi_hj_level, "4")

    def test_partner_default_level_follows_a_direct_pricelist_change(self):
        partner = self._make_partner(4)
        partner.write({"specific_property_product_pricelist": self.levels[7].id})
        self.assertEqual(partner.ndi_default_hj_level, 7)

    def test_pos_order_line_carries_the_level(self):
        """POS: pricelist ada di order, bukan di baris — snapshot harus dibuat sendiri."""
        session = self._open_pos_session()
        partner = self._make_partner(3)
        order = self.env["pos.order"].create(
            {
                "session_id": session.id,
                "company_id": self.env.company.id,
                "partner_id": partner.id,
                "pricelist_id": self.levels[3].id,
                "lines": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product.id,
                            "qty": 4.0,
                            "price_unit": float(self.row["hj3"]),
                            "price_subtotal": 4.0 * float(self.row["hj3"]),
                            "price_subtotal_incl": 4.0 * float(self.row["hj3"]),
                        },
                    )
                ],
                "amount_tax": 0.0,
                "amount_total": 4.0 * float(self.row["hj3"]),
                "amount_paid": 0.0,
                "amount_return": 0.0,
            }
        )
        self.assertEqual(order.lines.ndi_hj_level, "3")
        self.env.flush_all()
        self.env.cr.execute(
            "SELECT ndi_hj_level FROM pos_order_line WHERE id = %s", (order.lines.id,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], "3")

    def _open_pos_session(self):
        config = self.env["pos.config"].search([("company_id", "=", self.env.company.id)], limit=1)
        if not config:
            config = self.env["pos.config"].create({"name": "NDI Uji"})
        config.with_user(self.env.user).open_ui()
        return config.current_session_id
