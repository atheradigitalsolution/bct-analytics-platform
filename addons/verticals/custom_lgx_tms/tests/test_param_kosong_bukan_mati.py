# -*- coding: utf-8 -*-
"""Mengosongkan parameter penjaga TIDAK mematikannya.

Uji ini tidak memperbaiki apa pun — ia MEMAKU perilaku Odoo supaya tidak
ditemukan ulang dengan mahal. `ir.config_parameter.get_param` berbunyi
`return self._get_param(key) or default`, dan `or default` ada di luar
ormcache (yang menempel di `_get_param` yang privat). Karena itu dua keadaan
yang berbeda di penyimpanan — "ada tapi kosong" dan "tidak pernah disetel" —
menjadi TIDAK DAPAT DIBEDAKAN oleh setiap pemanggil `get_param`, yaitu oleh
semua kode yang benar.

Untuk penjaga yang defaultnya "1", akibatnya: operator yang mengosongkan
isiannya mengira sudah mematikan aturan, padahal aturan itu tetap menyala.
Arahnya aman, keyakinannya tidak.
"""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

KUNCI = "lgx.driver_single_open_advance"


@tagged("post_install", "-at_install")
class TestParamKosongBukanMati(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.driver_partner = cls.env["res.partner"].create({"name": "Pengemudi Parameter"})
        cls.driver = cls.env["lgx.driver"].create({
            "name": "Pengemudi Parameter",
            "partner_id": cls.driver_partner.id,
            "sim_number": "9911-2233-4455",
            "sim_class": "b2_umum",
            "sim_expiry_date": "2030-12-31",
        })
        model = cls.env["fleet.vehicle.model"].search([], limit=1)
        if not model:
            brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Uji Param"})
            model = cls.env["fleet.vehicle.model"].create({
                "name": "Tronton Param", "brand_id": brand.id,
            })
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id,
            "license_plate": "B 9911 PRM",
            "lgx_is_freight": True,
            "lgx_jbb_kg": 26000,
            "lgx_jbi_kg": 24000,
            "lgx_kerb_weight_kg": 9000,
            "lgx_kir_expiry_date": "2030-01-01",
            "lgx_stnk_expiry_date": "2030-01-01",
            "lgx_body_length_mm": 9000,
            "lgx_body_width_mm": 2400,
            "lgx_body_height_mm": 2100,
            "lgx_type_length_mm": 9000,
            "lgx_type_width_mm": 2400,
            "lgx_type_height_mm": 2100,
        })
        cls.route = cls.env["lgx.route"].create({
            "origin_location_id": cls.env.ref("custom_lgx_base.loc_idjkt").id,
            "destination_location_id": cls.env.ref("custom_lgx_base.loc_bandung").id,
            "distance_km": 180,
            "tariff_ids": [(0, 0, {
                "pricing_basis": "per_trip",
                "price": 3_500_000,
                "standard_advance": 800_000,
                "valid_from": "2026-01-01",
            })],
        })

    def _trip(self):
        return self.env["lgx.trip"].create({
            "trip_type": "ftl",
            "vehicle_id": self.vehicle.id,
            "driver_id": self.driver.id,
            "route_id": self.route.id,
            "cargo_weight_kg": 10_000,
            "planned_start": "2026-09-20 06:00:00",
            "planned_end": "2026-09-20 18:00:00",
        })

    def _satu_sudah_terbuka(self):
        """Pengemudi ini sudah memegang satu uang jalan yang disetujui."""
        pertama = self._trip()
        pertama.action_create_advance()      # uang jalan tidak terbit sendiri
        pertama.advance_id.action_approve()
        self.assertEqual(pertama.advance_id.state, "approved")
        kedua = self._trip()
        kedua.action_create_advance()
        return kedua.advance_id              # calon kedua, masih draf

    # --- inti persoalannya, diukur langsung --------------------------------
    def test_01_beda_nyata_di_privat_hilang_di_publik(self):
        self.params.set_param("lgx.uji_kosong", "")
        self.params.search([("key", "=", "lgx.uji_hilang")]).unlink()

        # di tingkat privat kedua keadaan masih dapat dibedakan
        self.assertEqual(self.params._get_param("lgx.uji_kosong"), "")
        self.assertFalse(self.params._get_param("lgx.uji_hilang"))

        # lewat API publik keduanya runtuh jadi nilai yang sama
        self.assertEqual(self.params.get_param("lgx.uji_kosong", "BAWAAN"), "BAWAAN")
        self.assertEqual(self.params.get_param("lgx.uji_hilang", "BAWAAN"), "BAWAAN")

    # --- akibatnya pada penjaga yang sungguhan -----------------------------
    def test_02_mengisi_nol_benar_benar_mematikan(self):
        """Jalan yang didokumentasikan harus bekerja, kalau tidak sisanya sia-sia."""
        self.params.set_param(KUNCI, "0")
        kedua = self._satu_sudah_terbuka()
        kedua.action_approve()
        self.assertEqual(kedua.state, "approved")

    def test_03_mengosongkan_TIDAK_mematikan(self):
        """Gerakan paling alami operator, dan ia tidak bekerja.

        Kalau uji ini suatu hari gagal, artinya perilaku Odoo berubah atau
        defaultnya diubah — dan pesan galat di `_check_single_open_advance`
        yang menyuruh "isi 0" harus ditinjau ulang bersamaan.
        """
        self.params.set_param(KUNCI, "")
        kedua = self._satu_sudah_terbuka()
        with self.assertRaises(ValidationError):
            kedua.action_approve()

    def test_04_menghapus_record_juga_TIDAK_mematikan(self):
        self.params.search([("key", "=", KUNCI)]).unlink()
        kedua = self._satu_sudah_terbuka()
        with self.assertRaises(ValidationError):
            kedua.action_approve()

    def test_05_pesan_galat_menyebut_angkanya(self):
        """Pesan yang hanya menyebut nama parameter mengundang operator
        mengosongkannya — satu-satunya cara yang tidak bekerja."""
        self.params.set_param(KUNCI, "1")
        kedua = self._satu_sudah_terbuka()
        with self.assertRaises(ValidationError) as ctx:
            kedua.action_approve()
        pesan = str(ctx.exception).lower()
        self.assertIn("0", pesan,
                      "pesan harus menyebut angka yang dipakai untuk mematikan")
        self.assertIn("mengosongkan", pesan,
                      "pesan harus memperingatkan bahwa mengosongkan tidak bekerja")
