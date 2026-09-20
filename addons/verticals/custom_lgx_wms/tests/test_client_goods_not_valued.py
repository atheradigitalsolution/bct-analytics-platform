# -*- coding: utf-8 -*-
"""LGX-E07 dan E02 — barang klien tidak masuk neraca, dan tidak tercampur.

Ini pembuktian keputusan 2 di Fase 0, dan alasannya disebut spesifikasi sebagai
risiko yang "ketahuan saat tutup buku pertama": pada titik itu koreksinya
menyentuh seluruh periode. Karena itu ia diuji, bukan diasumsikan.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestClientGoodsNotValued(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.client_category = cls.env.ref("custom_lgx_wms.product_category_client_goods")
        cls.owner_a = cls.env["res.partner"].create({"name": "PT Pemilik Barang A"})
        cls.owner_b = cls.env["res.partner"].create({"name": "PT Pemilik Barang B"})
        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company.id)], limit=1)
        cls.job_a = cls.env["lgx.job"].create({
            "job_type": "warehouse", "transport_mode": "land",
            "customer_id": cls.owner_a.id,
        })
        cls.client_a = cls.env["lgx.wms.client"].create({
            "name": "Pemilik A", "code": "OWNA",
            "partner_id": cls.owner_a.id, "owner_partner_id": cls.owner_a.id,
            "product_category_id": cls.client_category.id,
            "warehouse_id": cls.warehouse.id,
            "job_id": cls.job_a.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Kardus Mi Instan (milik klien)",
            "type": "consu",
            "is_storable": True,
            "categ_id": cls.client_category.id,
            "standard_price": 100000.0,
        })

    def _receive(self, client, product, quantity=10.0):
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"), ("warehouse_id", "=", self.warehouse.id),
        ], limit=1)
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "partner_id": client.partner_id.id,
            "lgx_wms_client_id": client.id,
            "owner_id": client.owner_partner_id.id,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": quantity,
                "description_picking": product.name,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            })],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = quantity
            move.picked = True
        picking.button_validate()
        return picking

    def test_client_category_is_not_real_time_valued(self):
        """Prasyarat yang membuat tes berikutnya berarti."""
        valuation = self.client_category.with_company(self.company).property_valuation
        self.assertEqual(
            valuation, "periodic",
            "Kategori barang klien harus bervaluasi periodik. owner_id saja TIDAK "
            "mengecualikan quant dari valuasi — itu keputusan 2 di Fase 0.",
        )

    def test_receiving_client_goods_creates_no_account_move(self):
        """LGX-E07 — penerimaan barang milik klien tidak menghasilkan account.move.

        Kalau tes ini merah, neraca perusahaan memuat aset yang bukan miliknya,
        dan itu ketahuan pertama kali saat tutup buku.
        """
        before = self.env["account.move"].search_count([])
        picking = self._receive(self.client_a, self.product, 10.0)
        self.assertEqual(picking.state, "done")
        after = self.env["account.move"].search_count([])
        self.assertEqual(
            before, after,
            "Penerimaan barang milik klien menghasilkan %s account.move baru. "
            "Barang klien tidak boleh masuk neraca perusahaan." % (after - before),
        )
        # Odoo 19 menghapus model `stock.valuation.layer`; pemeriksaan kedua
        # karena itu dilakukan langsung pada buku besar — dan itu justru
        # pemeriksaan yang lebih tepat, karena yang dipersoalkan neraca adalah
        # jurnalnya, bukan tabel perantaranya.
        stock_lines = self.env["account.move.line"].search([
            ("product_id", "=", self.product.id),
        ])
        self.assertFalse(
            stock_lines,
            "Barang milik klien menghasilkan %s baris jurnal. Tidak boleh ada satu pun."
            % len(stock_lines),
        )

    def test_quant_carries_the_owner_and_resolves_to_the_client(self):
        """LGX-E02 — stok terpisah per pemilik, dan pemiliknya terbaca di laporan."""
        self._receive(self.client_a, self.product, 10.0)
        quants = self.env["stock.quant"].search([
            ("product_id", "=", self.product.id), ("quantity", ">", 0),
            ("location_id.usage", "=", "internal"),
        ])
        self.assertTrue(quants)
        self.assertEqual(quants.mapped("owner_id"), self.owner_a)
        self.assertEqual(quants.mapped("lgx_wms_client_id"), self.client_a)

    def test_receiving_without_owner_is_rejected(self):
        """Stok tanpa pemilik di gudang multi-klien akan tercampur."""
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "incoming"), ("warehouse_id", "=", self.warehouse.id)], limit=1)
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "lgx_wms_client_id": self.client_a.id,
            "owner_id": False,
            "location_id": self.env.ref("stock.stock_location_suppliers").id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": [(0, 0, {
                "product_id": self.product.id, "product_uom_qty": 1,
                "description_picking": self.product.name,
                "location_id": self.env.ref("stock.stock_location_suppliers").id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            })],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = 1
            move.picked = True
        with self.assertRaises(UserError) as ctx:
            picking.button_validate()
        self.assertIn("pemilik", str(ctx.exception).lower())

    def test_a_valued_category_is_refused_for_client_goods(self):
        """Kontrol: kategori bervaluasi otomatis ditolak sebagai kategori barang klien."""
        valued = self.env["product.category"].create({"name": "Kategori Berharga Uji"})
        valued.with_company(self.company).property_valuation = "real_time"
        job_b = self.env["lgx.job"].create({
            "job_type": "warehouse", "transport_mode": "land",
            "customer_id": self.owner_b.id,
        })
        with self.assertRaises(ValidationError) as ctx:
            self.env["lgx.wms.client"].create({
                "name": "Pemilik B", "code": "OWNB",
                "partner_id": self.owner_b.id, "owner_partner_id": self.owner_b.id,
                "product_category_id": valued.id,
                "warehouse_id": self.warehouse.id,
                "job_id": job_b.id,
            })
        self.assertIn("neraca", str(ctx.exception).lower())
