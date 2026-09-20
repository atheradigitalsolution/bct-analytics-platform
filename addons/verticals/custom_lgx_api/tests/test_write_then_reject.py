# -*- coding: utf-8 -*-
"""Penolakan tidak boleh meninggalkan keadaan yang separuh tersimpan.

Endpoint `/json/2` menjawab dengan NILAI, bukan exception — `{"error": ...}`
adalah request yang SUKSES sejauh Odoo tahu, jadi cursor tetap di-commit di
akhir. Tanpa savepoint, setiap tulis yang sudah terjadi sebelum penolakan
bertahan, dan perangkat di lapangan menerima "ditolak" atas keadaan yang
sebenarnya sudah berubah.

Cacat ini lolos dari blok `except` biasa justru karena tidak ada yang dilempar
keluar: kita sendiri yang menangkapnya lalu mengubahnya menjadi nilai balik.
"""
import base64
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

FOTO = base64.b64encode(b"foto-pod-uji").decode()


@tagged("post_install", "-at_install")
class TestWriteThenReject(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service = cls.env["lgx.api.service"]
        cls.customer = cls.env["res.partner"].create({"name": "PT Uji API"})
        driver_partner = cls.env["res.partner"].create({"name": "Sari Pengemudi"})
        cls.driver = cls.env["lgx.driver"].create({
            "name": "Sari Pengemudi",
            "partner_id": driver_partner.id,
            "sim_number": "9911-2233-4455",
            "sim_class": "b2_umum",
            "sim_expiry_date": "2030-12-31",
        })
        model = cls.env["fleet.vehicle.model"].search([], limit=1)
        if not model:
            brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Uji API"})
            model = cls.env["fleet.vehicle.model"].create({
                "name": "Tronton Uji API", "brand_id": brand.id,
            })
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id,
            "license_plate": "B 1111 API",
            "lgx_is_freight": True,
            "lgx_jbb_kg": 26000,
            "lgx_jbi_kg": 24000,
            "lgx_kerb_weight_kg": 9000,
            "lgx_kir_expiry_date": "2030-01-01",
            "lgx_stnk_expiry_date": "2030-01-01",
        })
        cls.route = cls.env["lgx.route"].create({
            "origin_location_id": cls.env.ref("custom_lgx_base.loc_idjkt").id,
            "destination_location_id": cls.env.ref("custom_lgx_base.loc_bandung").id,
            "distance_km": 180,
            "tariff_ids": [(0, 0, {
                "pricing_basis": "per_trip", "price": 3_500_000,
                "standard_advance": 800_000, "valid_from": "2026-01-01",
            })],
        })

    def _trip(self, **kwargs):
        values = {
            "trip_type": "ftl",
            "vehicle_id": self.vehicle.id,
            "driver_id": self.driver.id,
            "route_id": self.route.id,
            "cargo_weight_kg": 10_000,
            "planned_start": "2026-09-20 06:00:00",
            "planned_end": "2026-09-20 18:00:00",
        }
        values.update(kwargs)
        return self.env["lgx.trip"].create(values)

    def _stop(self, trip):
        return self.env["lgx.trip.stop"].create({
            "trip_id": trip.id,
            "stop_type": "dropoff",
            "partner_id": self.customer.id,
            "qty_planned": 100,
        })

    # --- submit_pod --------------------------------------------------------
    def test_pod_rejected_midway_leaves_no_trace_on_the_stop(self):
        """Lampiran kedua gagal → stop harus kembali persis seperti sebelumnya.

        Inilah kasus yang paling mahal di lapangan. Tanpa savepoint, `stop.write`
        di awal sudah tersimpan: stop tercatat ber-POD, dengan nama penerima,
        atas jawaban yang berbunyi "ditolak". Pengemudi mengulang kirim, dan
        tidak ada satu pun log yang menunjukkan kedua fakta itu bertentangan.
        """
        stop = self._stop(self._trip())
        Attachment = type(self.env["ir.attachment"])
        original = Attachment.create
        state = {"n": 0}

        def flaky(model_self, vals):
            state["n"] += 1
            if state["n"] == 2:
                raise ValidationError("Lampiran kedua sengaja ditolak.")
            return original(model_self, vals)

        with patch.object(Attachment, "create", flaky):
            result = self.service.submit_pod(
                stop_id=stop.id, received_by="Pak Joko", photos=[FOTO, FOTO])

        self.assertIn("error", result, "Panggilan ini memang harus ditolak.")
        self.assertEqual(result["error"]["code"], "rejected")

        stop.invalidate_recordset()
        self.assertFalse(
            stop.received_by_name,
            "Nama penerima tersimpan padahal jawabannya 'ditolak' — separuh "
            "keadaan bertahan, dan itu cacat yang dicari uji ini.",
        )
        self.assertFalse(stop.has_pod, "Stop tidak boleh tercatat ber-POD.")
        self.assertFalse(stop.pod_photo_ids, "Foto pertama pun harus ikut dibatalkan.")

    def test_pod_that_succeeds_is_still_saved(self):
        """Savepoint tidak boleh membatalkan yang berhasil.

        Perbaikan yang membuat semua penolakan bersih tetapi diam-diam juga
        membatalkan keberhasilan akan lolos uji di atas dan merusak produksi.
        """
        stop = self._stop(self._trip())
        result = self.service.submit_pod(
            stop_id=stop.id, received_by="Pak Joko", photos=[FOTO])
        self.assertNotIn("error", result)
        stop.invalidate_recordset()
        self.assertEqual(stop.received_by_name, "Pak Joko")
        self.assertTrue(stop.has_pod)
        self.assertEqual(len(stop.pod_photo_ids), 1)

    def test_pod_is_idempotent_on_retry(self):
        """Kirim ulang dengan isi sama tidak menghasilkan POD kedua.

        Sinyal buruk di lapangan membuat pengulangan jadi hal biasa, bukan
        pengecualian.
        """
        stop = self._stop(self._trip())
        self.service.submit_pod(stop_id=stop.id, received_by="Pak Joko", photos=[FOTO])
        self.service.submit_pod(stop_id=stop.id, received_by="Pak Joko", photos=[FOTO])
        stop.invalidate_recordset()
        self.assertEqual(len(stop.pod_photo_ids), 1)

    # --- driver_update_trip ------------------------------------------------
    def test_rejected_trip_action_does_not_keep_the_new_odometer(self):
        """Odometer dan perubahan status jatuh atau berdiri bersama.

        Aksi yang ditolak aturan trip tidak boleh meninggalkan angka odometer
        baru — angka itu dipakai menghitung biaya per kilometer, dan angka yang
        naik tanpa perjalanan yang tercatat tidak akan pernah direkonsiliasi.
        """
        trip = self._trip()
        self.assertEqual(trip.state, "draft")
        before = trip.odometer_end

        result = self.service.driver_update_trip(
            trip_id=trip.id, action="deliver", odometer=999_999)

        self.assertIn("error", result, "Menyelesaikan trip draft memang harus ditolak.")
        self.assertEqual(result["error"]["code"], "rejected")
        trip.invalidate_recordset()
        self.assertEqual(
            trip.odometer_end, before,
            "Odometer berubah padahal aksinya ditolak.",
        )
        self.assertEqual(trip.state, "draft")

    def test_unknown_action_is_refused_before_anything_is_touched(self):
        """Daftar putih aksi diperiksa lebih dulu, bukan lewat exception."""
        trip = self._trip()
        result = self.service.driver_update_trip(
            trip_id=trip.id, action="hapus_semua", odometer=1234)
        self.assertEqual(result["error"]["code"], "bad_action")
        trip.invalidate_recordset()
        self.assertNotEqual(trip.odometer_start, 1234)
