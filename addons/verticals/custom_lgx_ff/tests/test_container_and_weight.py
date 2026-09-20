# -*- coding: utf-8 -*-
"""LGX-B02, B04, B05 — berat yang ditagih, ISO 6346, dan demurrage/detensi."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_lgx_ff.models.lgx_container import iso6346_check_digit


@tagged("post_install", "-at_install")
class TestContainerAndWeight(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({"name": "PT Uji Forwarding"})
        cls.job = cls.env["lgx.job"].create({
            "job_type": "ff_import",
            "transport_mode": "sea",
            "customer_id": cls.customer.id,
            "etd": "2026-09-01",
            "eta": "2026-09-20",
        })
        cls.shipment = cls.env["lgx.shipment"].create({
            "job_id": cls.job.id,
            "transport_mode": "sea",
            "direction": "import",
            "load_type": "fcl",
        })
        cls.ctype = cls.env.ref("custom_lgx_base.ctype_20gp")

    # --- LGX-B04 : ISO 6346 ------------------------------------------------
    def test_iso6346_matches_the_published_example(self):
        """CSQU3054383 adalah contoh kanonik di standar ISO 6346.

        Diuji terhadap contoh yang diterbitkan standarnya, bukan terhadap nomor
        yang saya karang sendiri — algoritme yang hanya diuji dengan datanya
        sendiri membuktikan bahwa ia konsisten, bukan bahwa ia benar.
        """
        self.assertEqual(iso6346_check_digit("CSQU305438"), 3)

    def test_valid_container_number_is_accepted(self):
        container = self.env["lgx.container"].create({
            "shipment_id": self.shipment.id,
            "container_no": "CSQU3054383",
            "container_type_id": self.ctype.id,
        })
        self.assertEqual(container.container_no, "CSQU3054383")

    def test_wrong_check_digit_is_rejected_and_names_the_right_one(self):
        """Menolak tanpa menyebut digit yang benar memaksa orang menebak."""
        with self.assertRaises(ValidationError) as ctx:
            self.env["lgx.container"].create({
                "shipment_id": self.shipment.id,
                "container_no": "CSQU3054380",
                "container_type_id": self.ctype.id,
            })
        message = str(ctx.exception)
        self.assertIn("ISO 6346", message)
        self.assertIn("3", message, "Pesan harus menyebut digit periksa yang benar.")

    def test_malformed_container_number_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["lgx.container"].create({
                "shipment_id": self.shipment.id,
                "container_no": "ABC123",
                "container_type_id": self.ctype.id,
            })

    # --- LGX-B02 : berat yang ditagih --------------------------------------
    def test_air_chargeable_weight_uses_volumetric_when_it_wins(self):
        """Udara: max(berat kotor, volume_cm3 / pembagi), dan dasarnya disebut."""
        air_job = self.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "air",
            "customer_id": self.customer.id, "etd": "2026-09-01",
        })
        shipment = self.env["lgx.shipment"].create({
            "job_id": air_job.id, "transport_mode": "air",
            "direction": "import", "load_type": "air",
        })
        self.env["lgx.package"].create({
            "shipment_id": shipment.id,
            "description": "Kardus ringan memakan ruang",
            "quantity": 1,
            "length_cm": 100, "width_cm": 100, "height_cm": 100,
            "gross_weight_kg": 50.0,
        })
        shipment.invalidate_recordset()
        # 1.000.000 cm3 / 6000 = 166,67 kg volumetrik > 50 kg aktual
        self.assertEqual(shipment.chargeable_basis, "volume")
        self.assertAlmostEqual(shipment.chargeable_weight, 167.0, places=0)

    def test_air_chargeable_weight_uses_actual_when_it_wins(self):
        """Kontrol negatif: barang padat ditagih menurut beratnya, bukan volumenya."""
        air_job = self.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "air",
            "customer_id": self.customer.id, "etd": "2026-09-01",
        })
        shipment = self.env["lgx.shipment"].create({
            "job_id": air_job.id, "transport_mode": "air",
            "direction": "import", "load_type": "air",
        })
        self.env["lgx.package"].create({
            "shipment_id": shipment.id, "description": "Besi",
            "quantity": 1, "length_cm": 20, "width_cm": 20, "height_cm": 20,
            "gross_weight_kg": 300.0,
        })
        shipment.invalidate_recordset()
        self.assertEqual(shipment.chargeable_basis, "berat")
        self.assertAlmostEqual(shipment.chargeable_weight, 300.0, places=1)

    def test_sea_lcl_uses_weight_or_measurement(self):
        """Laut LCL: max(ton, CBM) — dikenal sebagai W/M."""
        self.env["lgx.package"].create({
            "shipment_id": self.shipment.id, "description": "Kardus",
            "quantity": 10, "length_cm": 100, "width_cm": 100, "height_cm": 100,
            "gross_weight_kg": 200.0,
        })
        self.shipment.invalidate_recordset()
        # 10 m3 volume versus 2 ton berat -> volume menang
        self.assertEqual(self.shipment.chargeable_basis, "volume")
        self.assertAlmostEqual(self.shipment.chargeable_weight, 10.0, places=1)

    def test_volumetric_divisor_comes_from_rate_card_not_from_code(self):
        """Pembagi volumetrik berasal dari rate card; carrier boleh berbeda."""
        card = self.env["lgx.rate.card"].create({
            "name": "Beli udara pembagi 5000",
            "direction": "buy", "transport_mode": "air",
            "volumetric_divisor": 5000.0, "weight_rounding": 0.5,
            "valid_from": "2026-01-01",
            "line_ids": [(0, 0, {
                "charge_code_id": self.env.ref("custom_lgx_base.charge_afr").id,
                "basis": "per_kg", "price": 25000,
            })],
        })
        card.action_activate()
        air_job = self.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "air",
            "customer_id": self.customer.id, "etd": "2026-09-01",
        })
        shipment = self.env["lgx.shipment"].create({
            "job_id": air_job.id, "transport_mode": "air", "direction": "import",
            "load_type": "air", "rate_card_id": card.id,
        })
        self.env["lgx.package"].create({
            "shipment_id": shipment.id, "description": "Kardus",
            "quantity": 1, "length_cm": 100, "width_cm": 100, "height_cm": 100,
            "gross_weight_kg": 50.0,
        })
        shipment.invalidate_recordset()
        # 1.000.000 / 5000 = 200 kg, bukan 166,67 kg
        self.assertAlmostEqual(shipment.chargeable_weight, 200.0, places=1)

    # --- LGX-B05 : demurrage dan detensi -----------------------------------
    def test_demurrage_and_detention_are_counted_per_container(self):
        container = self.env["lgx.container"].create({
            "shipment_id": self.shipment.id,
            "container_no": "CSQU3054383",
            "container_type_id": self.ctype.id,
            "discharge_date": "2026-09-01",
            "free_days_demurrage": 5,
            "gate_out_date": "2026-09-10",
            "free_days_detention": 3,
            "gate_in_date": "2026-09-20",
        })
        # Demurrage: bongkar 1 Sep + 5 hari bebas = batas 6 Sep; keluar 10 Sep -> 4 hari
        self.assertEqual(container.demurrage_days, 4)
        # Detensi: keluar 10 Sep + 3 hari bebas = batas 13 Sep; kembali 20 Sep -> 7 hari
        self.assertEqual(container.detention_days, 7)
        self.assertTrue(container.is_returned)

    def test_job_cannot_complete_while_a_container_is_out(self):
        """LGX-B05 — kontainer yang belum kembali MENAHAN penyelesaian job.

        Ini aturan yang menutup kebocoran paling umum di forwarding: detensi
        ditagihkan carrier berminggu-minggu kemudian, dan job yang sudah ditutup
        tidak pernah meneruskannya ke pelanggan.
        """
        self.env["lgx.container"].create({
            "shipment_id": self.shipment.id,
            "container_no": "CSQU3054383",
            "container_type_id": self.ctype.id,
            "discharge_date": "2026-09-01",
            "gate_out_date": "2026-09-05",
        })
        self.env["lgx.job.charge"].create({
            "job_id": self.job.id,
            "charge_code_id": self.env.ref("custom_lgx_base.charge_ofr").id,
            "kind": "revenue", "nature": "service",
            "quantity": 1, "unit_price": 1000, "amount_estimated": 1000,
            "currency_id": self.job.currency_id.id,
        })
        self.job.action_confirm()
        self.job.milestone_ids.filtered("is_mandatory").write({"actual_date": "2026-09-20 08:00:00"})
        self.job.invalidate_recordset()
        with self.assertRaises(UserError) as ctx:
            self.job.action_complete()
        self.assertIn("CSQU3054383", str(ctx.exception),
                      "Pesan harus menyebut kontainer mana yang belum kembali.")
