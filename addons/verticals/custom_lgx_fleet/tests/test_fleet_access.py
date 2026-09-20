# -*- coding: utf-8 -*-
"""Peran trucking harus boleh membuka menu armada yang modul ini kirim sendiri.

Cacat yang diuji di sini ditemukan dari TANGKAPAN LAYAR, bukan dari suite:
mengeklik menu "Dokumen Kendaraan" sebagai manajer trucking memunculkan dialog
Access Error pada fleet.vehicle. Modul mengirim menunya, tidak mengirim haknya.

Tidak ada uji yang pernah menyentuhnya karena semuanya berjalan sebagai
superuser, dan admin pun kebetulan tidak punya grup Fleet — jadi tidak ada
jalur yang pernah membuka menu itu sebagai pengguna sungguhan.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFleetAccess(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        model = cls.env["fleet.vehicle.model"].search([], limit=1)
        if not model:
            brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Uji Akses"})
            model = cls.env["fleet.vehicle.model"].create({
                "name": "Tronton Uji Akses", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({
            "model_id": model.id, "license_plate": "B 4321 AKS",
            "lgx_is_freight": True, "lgx_jbi_kg": 24000,
        })

    def _pengguna(self, *xmlid_grup, login="peran@uji.invalid"):
        grup = [self.env.ref("base.group_user").id]
        grup += [self.env.ref(x).id for x in xmlid_grup]
        return self.env["res.users"].create({
            "name": "Peran Uji", "login": login, "group_ids": [(6, 0, grup)],
        })

    def test_trucking_manager_can_open_the_vehicle_menu(self):
        """Ini yang gagal di produksi: dialog Access Error pada fleet.vehicle."""
        u = self._pengguna("custom_lgx_base.group_lgx_trucking_manager",
                           login="manajer.trucking@uji.invalid")
        hasil = self.env["fleet.vehicle"].with_user(u).search(
            [("id", "=", self.vehicle.id)])
        self.assertTrue(
            hasil,
            "Manajer trucking tidak dapat membaca fleet.vehicle — menu "
            "'Dokumen Kendaraan' yang dikirim modul ini akan memunculkan "
            "Access Error untuknya.",
        )

    def test_dispatcher_can_read_vehicles(self):
        """Dispatcher menugaskan kendaraan ke trip; tanpa hak baca ia buta."""
        u = self._pengguna("custom_lgx_base.group_lgx_trucking_dispatcher",
                           login="dispatcher@uji.invalid")
        self.assertTrue(
            self.env["fleet.vehicle"].with_user(u).search([("id", "=", self.vehicle.id)]))

    def test_manager_can_maintain_vehicle_master(self):
        """Manajer memelihara JBI, dimensi tipe, KIR — itu menulis, bukan membaca."""
        u = self._pengguna("custom_lgx_base.group_lgx_trucking_manager",
                           login="manajer.tulis@uji.invalid")
        self.vehicle.with_user(u).write({"lgx_type_length_mm": 9000})
        self.assertEqual(self.vehicle.lgx_type_length_mm, 9000)

    def test_the_grant_is_not_too_wide(self):
        """Kontrol positif terbalik: peran yang TIDAK mengurus armada tetap tertutup.

        Hibah yang terlalu lebar akan lolos ketiga uji di atas dengan gemilang
        sambil memberi seluruh pengguna LGX hak atas armada perusahaan.
        """
        u = self._pengguna("custom_lgx_base.group_lgx_customs_manager",
                           login="manajer.pabean@uji.invalid")
        with self.assertRaises(AccessError):
            self.env["fleet.vehicle"].with_user(u).search(
                [("id", "=", self.vehicle.id)])

    def test_granting_is_idempotent(self):
        """Dijalankan tiap update; menjalankannya lagi tidak boleh menambah apa pun."""
        Groups = self.env["res.groups"]
        Groups._lgx_apply_fleet_group_implications()
        self.assertEqual(Groups._lgx_apply_fleet_group_implications(), 0)

    def test_wms_implications_still_work(self):
        """Dua modul yang menghibahkan grup tidak boleh saling menimpa.

        Kalau berkas ini memakai nama method yang sama dengan custom_lgx_wms,
        definisi yang dimuat belakangan menang dan hibah WMS berhenti berjalan
        — tanpa galat, dan gejalanya muncul jauh kemudian sebagai operator
        gudang yang tidak berhak membaca stock.picking.
        """
        Groups = self.env["res.groups"]
        self.assertTrue(hasattr(Groups, "_lgx_apply_group_implications"))
        self.assertTrue(hasattr(Groups, "_lgx_apply_fleet_group_implications"))
        operator = self.env.ref("custom_lgx_base.group_lgx_wh_operator")
        stock_user = self.env.ref("stock.group_stock_user")
        self.assertIn(stock_user, operator.implied_ids,
                      "Hibah WMS hilang — kemungkinan tertimpa method senama.")
