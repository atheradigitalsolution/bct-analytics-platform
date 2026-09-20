# -*- coding: utf-8 -*-
"""Kelima tarif pungutan impor dijaga, bukan tiga.

Penjaga sebelumnya menutup bm_rate, ppn_rate, dan pph22_rate lalu melewatkan
ppnbm_rate serta pph22_rate_no_api — pada model yang sama. Bentuk yang sama
dengan yang dilaporkan sesi SIMRS pada pengali tarif mereka: penjaga dipasang
sekali, terlupa di tempat lain, dan tidak ada yang terlihat ganjil karena
seluruh angka turunannya ikut bergerak serempak.
"""
from psycopg2 import IntegrityError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestHsCodeRates(TransactionCase):

    def _create(self, **kwargs):
        values = {"code": "8471.30.90", "name": "Uji tarif"}
        values.update(kwargs)
        return self.env["lgx.hs.code"].create(values)

    def _refuses(self, **kwargs):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._create(**kwargs)
                self.env.flush_all()

    def test_negative_ppnbm_is_refused(self):
        """Field ini yang terlewat penjaga lama."""
        self._refuses(ppnbm_rate=-10.0)

    def test_negative_pph22_without_api_is_refused(self):
        """Dan field ini."""
        self._refuses(pph22_rate_no_api=-1.0)

    def test_negative_bm_is_still_refused(self):
        """Kontrol positif atas penjaga lama: memperluas tidak boleh melonggarkan."""
        self._refuses(bm_rate=-5.0)

    def test_high_but_legal_rates_are_accepted(self):
        """Kontrol positif: tidak ada batas atas, dan itu disengaja.

        Tarif PPnBM dapat mencapai ratusan persen untuk barang mewah. Menebak
        batas maksimum lalu menolak data yang sah lebih buruk daripada tidak
        membatasi — yang salah ketik tertangkap perbandingan terhadap BTKI,
        bukan oleh constraint yang dikarang.
        """
        hs = self._create(ppnbm_rate=125.0, bm_rate=150.0)
        self.env.flush_all()
        self.assertEqual(hs.ppnbm_rate, 125.0)
