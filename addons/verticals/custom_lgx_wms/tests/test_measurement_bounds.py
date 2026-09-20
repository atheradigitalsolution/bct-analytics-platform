# -*- coding: utf-8 -*-
"""Persentase hasil ukur tidak mungkin di luar 0-100.

Keempat angka SLA adalah rasio dari hitungan: berapa yang tepat waktu dibagi
berapa seluruhnya. Angka di luar rentang itu bukan kinerja luar biasa melainkan
salah ketik — dan pengukuran SLA yang salah menggeser tagihan penalti ke klien.
"""
from psycopg2 import IntegrityError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestMeasurementBounds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env["res.partner"].create({"name": "PT Klien SLA"})
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.client = cls.env["lgx.wms.client"].create({
            "name": "Klien SLA", "code": "SLAUJI",
            "partner_id": partner.id, "owner_partner_id": partner.id,
            "product_category_id": cls.env.ref(
                "custom_lgx_wms.product_category_client_goods").id,
            "warehouse_id": warehouse.id,
        })

    def _measure(self, **kwargs):
        values = {
            "client_id": self.client.id,
            "date": "2026-09-01",
            "receiving_ontime_pct": 98.0,
            "dispatch_ontime_pct": 97.0,
            "inventory_accuracy_pct": 99.5,
            "order_accuracy_pct": 99.0,
        }
        values.update(kwargs)
        return self.env["lgx.wms.sla.measurement"].create(values)

    def _refuses(self, **kwargs):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._measure(**kwargs)
                self.env.flush_all()

    def test_above_hundred_is_refused(self):
        self._refuses(receiving_ontime_pct=150.0)

    def test_negative_is_refused(self):
        self._refuses(order_accuracy_pct=-1.0)

    def test_boundaries_are_accepted(self):
        """Kontrol positif: 0 dan 100 keduanya sah.

        Penjaga yang menolak batasnya sendiri akan menolak bulan yang sempurna
        dan bulan yang gagal total — dua keadaan yang justru paling perlu
        tercatat.
        """
        m = self._measure(receiving_ontime_pct=100.0, dispatch_ontime_pct=0.0)
        self.env.flush_all()
        self.assertEqual(m.receiving_ontime_pct, 100.0)
        self.assertEqual(m.dispatch_ontime_pct, 0.0)


@tagged("post_install", "-at_install")
class TestCountThreshold(TransactionCase):
    """Ambang selisih stock opname juga persentase, dan juga terlupa dijaga."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        partner = cls.env["res.partner"].create({"name": "PT Klien Opname"})
        warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1)
        cls.client = cls.env["lgx.wms.client"].create({
            "name": "Klien Opname", "code": "OPNUJI",
            "partner_id": partner.id, "owner_partner_id": partner.id,
            "product_category_id": cls.env.ref(
                "custom_lgx_wms.product_category_client_goods").id,
            "warehouse_id": warehouse.id,
        })

    def _program(self, **kwargs):
        values = {
            "name": "Program Uji",
            "client_id": self.client.id,
            "discrepancy_threshold_pct": 2.0,
        }
        values.update(kwargs)
        return self.env["lgx.wms.count.program"].create(values)

    def test_threshold_above_hundred_is_refused(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._program(discrepancy_threshold_pct=250.0)
                self.env.flush_all()

    def test_threshold_zero_is_accepted(self):
        """Kontrol positif: ambang nol berarti selisih sekecil apa pun ditandai."""
        program = self._program(discrepancy_threshold_pct=0.0)
        self.env.flush_all()
        self.assertEqual(program.discrepancy_threshold_pct, 0.0)
