# -*- coding: utf-8 -*-
"""Tes NLE tanpa jaringan: prasyarat, bentuk payload, dan pemetaan status."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNleGuards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "lgx_nle_enabled": True,
            "lgx_nle_base_url": "http://lgx-mock:4020",
            "lgx_nle_api_key": "uji",
            "lgx_nle_id_platform": "ATHERA-UJI",
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "PT Consignee NLE", "vat": "9911223344551122",
        })
        cls.carrier = cls.env["res.partner"].create({
            "name": "Maersk Uji", "lgx_is_carrier": True,
        })
        cls.job = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": cls.customer.id, "etd": "2026-09-01",
        })
        cls.shipment = cls.env["lgx.shipment"].create({
            "job_id": cls.job.id, "transport_mode": "sea",
            "direction": "import", "load_type": "fcl",
            "carrier_id": cls.carrier.id,
            "master_doc_no": "MAEU987654321",
        })
        cls.container = cls.env["lgx.container"].create({
            "shipment_id": cls.shipment.id,
            "container_no": "CSQU3054383",
            "container_type_id": cls.env.ref("custom_lgx_base.ctype_40hc").id,
        })

    def test_missing_id_platform_is_refused_with_the_real_reason(self):
        """Request tanpa id_platform ditolak NLE dengan pesan yang tidak menyebut penyebabnya.

        Karena itu penolakannya dilakukan di sini, di mana penyebabnya masih
        dapat dikatakan.
        """
        self.company.sudo().lgx_nle_id_platform = False
        with self.assertRaises(UserError) as ctx:
            self.shipment.action_request_do_online()
        self.assertIn("id_platform", str(ctx.exception))
        self.company.sudo().lgx_nle_id_platform = "ATHERA-UJI"

    def test_shipment_without_bl_cannot_request_do(self):
        shipment = self.env["lgx.shipment"].create({
            "job_id": self.job.id, "transport_mode": "sea",
            "direction": "import", "load_type": "fcl",
        })
        with self.assertRaises(UserError) as ctx:
            shipment.action_request_do_online()
        self.assertIn("B/L", str(ctx.exception))

    def test_do_is_not_requested_twice(self):
        """DO kedua untuk B/L yang sama adalah masalah di sisi pelayaran, bukan di sini."""
        self.shipment.nle_do_id = "sudah-ada"
        with self.assertRaises(UserError) as ctx:
            self.shipment.action_request_do_online()
        self.assertIn("sudah terbit", str(ctx.exception))
        self.shipment.nle_do_id = False

    def test_do_payload_shape(self):
        payload = self.shipment._do_payload()
        self.assertEqual(payload["bl_no"], "MAEU987654321")
        self.assertEqual(payload["id_platform"], "ATHERA-UJI")
        self.assertEqual(payload["npwp_cargo_owner"], "9911223344551122")
        self.assertEqual(len(payload["container"]), 1)
        self.assertEqual(payload["container"][0]["container_no"], "CSQU3054383")

    def test_sp2_requires_a_container(self):
        shipment = self.env["lgx.shipment"].create({
            "job_id": self.job.id, "transport_mode": "sea",
            "direction": "import", "load_type": "lcl",
            "master_doc_no": "MAEU111222333",
        })
        with self.assertRaises(UserError) as ctx:
            shipment.action_request_sp2()
        self.assertIn("kontainer", str(ctx.exception).lower())

    def test_status_becomes_a_milestone_with_source_nle(self):
        self.shipment._apply_nle_status({
            "document_status": "SPPB_TERBIT",
            "container": [],
        })
        milestone = self.job.milestone_ids.filtered(
            lambda m: m.milestone_type_id.code == "customs_released")
        self.assertTrue(milestone.actual_date)
        self.assertEqual(milestone.source, "nle")
        self.assertEqual(self.shipment.nle_last_document_status, "SPPB_TERBIT")

    def test_repeated_pull_does_not_duplicate_milestones(self):
        """Cron dua-jam-sekali tidak boleh menghasilkan dua puluh milestone sehari."""
        for _ in range(3):
            self.shipment._apply_nle_status({"document_status": "PIB_DITERIMA", "container": []})
        matching = self.job.milestone_ids.filtered(
            lambda m: m.milestone_type_id.code == "customs_submitted")
        self.assertEqual(len(matching), 1)

    def test_gate_out_fills_the_date_but_never_overwrites_a_typed_one(self):
        """Angka yang sudah diketik orang tidak ditimpa oleh tebakan dari luar."""
        self.shipment._apply_nle_status({
            "document_status": "GATE_OUT",
            "container": [{"container_no": "CSQU3054383", "status": "GATE_OUT"}],
        })
        self.assertTrue(self.container.gate_out_date)
        typed = self.container.gate_out_date
        self.container.gate_out_date = "2026-09-10"
        self.shipment._apply_nle_status({
            "document_status": "GATE_OUT",
            "container": [{"container_no": "CSQU3054383", "status": "GATE_OUT"}],
        })
        self.assertEqual(
            str(self.container.gate_out_date), "2026-09-10",
            "Tanggal gerbang yang sudah diisi tidak boleh ditimpa penarikan berikutnya.",
        )
        self.assertNotEqual(typed, self.container.gate_out_date)
