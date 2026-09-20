# -*- coding: utf-8 -*-
"""Durasi rute tidak boleh negatif — jaraknya sudah dijaga, durasinya belum.

Bentuk yang sama dengan tarif HS code: penjaga dipasang untuk satu field lalu
terlupa untuk tetangganya di model yang sama.
"""
from psycopg2 import IntegrityError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestRouteBounds(TransactionCase):

    def _route(self, **kwargs):
        values = {
            "origin_location_id": self.env.ref("custom_lgx_base.loc_idjkt").id,
            "destination_location_id": self.env.ref("custom_lgx_base.loc_bandung").id,
            "distance_km": 180,
            "standard_duration_hours": 4.5,
        }
        values.update(kwargs)
        return self.env["lgx.route"].create(values)

    def test_negative_duration_is_refused(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            with self.env.cr.savepoint():
                self._route(standard_duration_hours=-2.0)
                self.env.flush_all()

    def test_zero_duration_is_accepted(self):
        """Kontrol positif: nol sah — rute yang durasinya belum diukur."""
        route = self._route(standard_duration_hours=0.0)
        self.env.flush_all()
        self.assertEqual(route.standard_duration_hours, 0.0)
