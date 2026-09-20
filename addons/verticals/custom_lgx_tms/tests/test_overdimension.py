# -*- coding: utf-8 -*-
"""Butir A12 — over-dimension adalah pelanggaran yang BERBEDA dari over-load.

UU 22/2009 memisahkan keduanya, dan jaraknya jauh:

* Pasal 307 — muatan/daya angkut menyimpang: kurungan paling lama 2 bulan atau
  denda paling banyak Rp500.000.
* Pasal 277 — kendaraan dimodifikasi sehingga berubah tipe tanpa uji tipe:
  penjara paling lama 1 tahun atau denda paling banyak Rp24.000.000.

Empat puluh delapan kali lipat. Sampai uji ini ditulis, modul hanya memeriksa
yang Rp500.000 sementara namanya "ODOL" — dan nama itu yang membuat separuh
lebih mahal tampak sudah tertangani.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestOverDimension(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        model = cls.env["fleet.vehicle.model"].search([], limit=1)
        if not model:
            brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Uji Dimensi"})
            model = cls.env["fleet.vehicle.model"].create({
                "name": "Tronton Uji Dimensi", "brand_id": brand.id,
            })
        cls.model = model

    def _vehicle(self, **kwargs):
        values = {
            "model_id": self.model.id,
            "license_plate": "B 7777 DIM",
            "lgx_is_freight": True,
            "lgx_jbb_kg": 26000, "lgx_jbi_kg": 24000, "lgx_kerb_weight_kg": 9000,
            "lgx_body_length_mm": 9000,
            "lgx_body_width_mm": 2400,
            "lgx_body_height_mm": 2100,
            "lgx_type_length_mm": 9000,
            "lgx_type_width_mm": 2400,
            "lgx_type_height_mm": 2100,
        }
        values.update(kwargs)
        return self.env["fleet.vehicle"].create(values)

    def test_body_matching_its_type_is_ok(self):
        vehicle = self._vehicle()
        level, _message = vehicle.lgx_check_dimensions()
        self.assertEqual(level, "ok")
        self.assertEqual(vehicle.lgx_dimension_status, "ok")

    def test_vehicle_without_type_dimensions_is_unknown_not_ok(self):
        """Alasan yang sama seperti JBI: belum-diperiksa bukan aman.

        Ini justru keadaan armada nyata sebelum SRUT disalin — dan kalau ia
        dilaporkan "ok", tidak akan pernah ada yang menyalinnya.
        """
        vehicle = self._vehicle(lgx_type_length_mm=0, lgx_type_width_mm=0,
                                lgx_type_height_mm=0)
        level, message = vehicle.lgx_check_dimensions()
        self.assertEqual(level, "unknown")
        self.assertNotEqual(level, "ok")
        self.assertIn("SRUT", message)

    def test_longer_body_than_type_is_flagged_and_names_the_article(self):
        """Pesannya harus menyebut Pasal 277, bukan sekadar 'melebihi'.

        Operator yang membaca "melebihi dimensi" akan menakarnya seperti
        kelebihan muatan biasa. Angka Rp24.000.000 yang mengubah keputusannya.
        """
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")
        vehicle = self._vehicle(lgx_body_length_mm=10_500)
        level, message = vehicle.lgx_check_dimensions()
        self.assertEqual(level, "warning")
        self.assertIn("panjang", message)
        self.assertIn("1500", message.replace(".", ""))
        self.assertIn("277", message)

    def test_over_dimension_is_blocked_from_the_enforcement_date(self):
        self.params.set_param("lgx.odol_enforcement_date", "2026-01-01")
        vehicle = self._vehicle(lgx_body_height_mm=2_600)
        level, _message = vehicle.lgx_check_dimensions()
        self.assertEqual(level, "blocked")
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")

    def test_trip_takes_the_worse_of_load_and_dimension(self):
        """Muatan sah di atas kendaraan yang baknya menyimpang tetap ditahan.

        Inilah yang hilang sebelum A12: status ODOL hanya membaca berat, jadi
        trip seperti ini berangkat dengan layar hijau.
        """
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")
        vehicle = self._vehicle(lgx_body_width_mm=2_900)  # lebar melebihi tipe
        trip = self.env["lgx.trip"].create({
            "trip_type": "ftl",
            "vehicle_id": vehicle.id,
            "cargo_weight_kg": 10_000,  # jauh di bawah JBI
            "planned_start": "2026-09-20 06:00:00",
            "planned_end": "2026-09-20 18:00:00",
        })
        self.assertEqual(
            trip.odol_status, "warning",
            "Berat yang sah tidak boleh menutupi dimensi yang menyimpang.",
        )
        self.assertIn("277", trip.odol_message)
        with self.assertRaises(UserError):
            trip.action_assign()

    def test_clean_vehicle_and_load_is_still_ok(self):
        """Kontrol positif: penggabungan dua pemeriksaan tidak boleh rakus."""
        self.params.set_param("lgx.odol_enforcement_date", "2027-01-01")
        vehicle = self._vehicle()
        trip = self.env["lgx.trip"].create({
            "trip_type": "ftl",
            "vehicle_id": vehicle.id,
            "cargo_weight_kg": 10_000,
            "planned_start": "2026-09-20 06:00:00",
            "planned_end": "2026-09-20 18:00:00",
        })
        self.assertEqual(trip.odol_status, "ok")
