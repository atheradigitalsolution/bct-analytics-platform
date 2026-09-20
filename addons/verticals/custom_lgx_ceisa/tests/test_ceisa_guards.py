# -*- coding: utf-8 -*-
"""Tes CEISA yang TIDAK menyentuh jaringan.

Sengaja dipisah dari tes yang memanggil mock. Tes yang gagal karena sebuah
container sedang mati adalah tes yang lama-lama diabaikan orang, dan tes yang
diabaikan sama saja dengan tidak ada — jadi aturan, bentuk payload, dan mesin
status diuji di sini tanpa socket sama sekali.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCeisaGuards(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "lgx_ceisa_enabled": True,
            "lgx_ceisa_base_url": "http://lgx-mock:4020",
            "lgx_ceisa_client_id": "uji",
            "lgx_ceisa_client_secret": "uji",
        })
        cls.customer = cls.env["res.partner"].create({
            "name": "PT Importir Uji", "vat": "9911223344556677",
            "lgx_nib": "1112223334445", "lgx_customs_access_type": "importer",
        })
        cls.ppjk = cls.env["res.partner"].create({
            "name": "PT PPJK Uji", "lgx_is_ppjk": True, "vat": "9900112233445599",
        })
        cls.expert = cls.env["lgx.customs.expert"].create({
            "name": "Ahli Uji", "certificate_no": "AK-UJI-0001",
            "certificate_expiry": "2030-01-01", "ppjk_partner_id": cls.ppjk.id,
        })
        cls.job = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": cls.customer.id, "etd": "2026-09-01",
        })
        cls.office_mandatory = cls.env.ref("custom_lgx_base.office_040300")
        cls.office_manual = cls.env.ref("custom_lgx_base.office_041100")

    def _declaration(self, office=None):
        return self.env["lgx.customs.declaration"].create({
            "job_id": self.job.id,
            "doc_type": "bc20_pib",
            "principal_id": self.customer.id,
            "ppjk_id": self.ppjk.id,
            "customs_expert_id": self.expert.id,
            "customs_office_id": (office or self.office_mandatory).id,
            "fx_rate_tax": 15900.0,
            "line_ids": [(0, 0, {
                "hs_code_id": self.env.ref("custom_lgx_customs.hs_84713020").id,
                "description": "Laptop", "quantity": 10, "customs_value": 5000.0,
            })],
        })

    def test_manual_office_is_never_sent(self):
        """Kantor yang belum wajib CEISA tidak dikirimi apa pun.

        Antrian yang penuh galat permanen adalah antrian yang berhenti dibaca
        orang — dan begitu berhenti dibaca, kegagalan yang sesungguhnya ikut
        tidak terlihat.
        """
        declaration = self._declaration(self.office_manual)
        self.assertEqual(declaration.submission_mode, "manual")
        declaration.action_submit()
        with self.assertRaises(UserError) as ctx:
            declaration.action_send_ceisa()
        self.assertIn("manual", str(ctx.exception).lower())

    def test_draft_declaration_is_not_sent(self):
        """Draf tidak dikirim: pemeriksaan ahli dan kelengkapan prinsipal ada di action_submit."""
        declaration = self._declaration()
        with self.assertRaises(UserError) as ctx:
            declaration.action_send_ceisa()
        self.assertIn("draf", str(ctx.exception).lower())

    def test_disabled_integration_refuses(self):
        self.company.lgx_ceisa_enabled = False
        declaration = self._declaration()
        declaration.action_submit()
        with self.assertRaises(UserError):
            declaration.action_send_ceisa()
        self.company.lgx_ceisa_enabled = True

    def test_payload_uses_nib_and_npwp_and_never_nik(self):
        """PMK 219/2019: identitas kepabeanan adalah NIB + NPWP + jenis akses.

        Tes ini menjaga sebuah KETIADAAN, dan itu disengaja: field 'NIK
        Kepabeanan' adalah hal yang gampang ditambahkan kembali oleh orang yang
        belum membaca PMK-nya, dan tidak ada yang akan menyadarinya sampai
        dokumen ditolak.
        """
        declaration = self._declaration()
        payload = declaration._ceisa_payload()
        self.assertEqual(payload["nibPengusaha"], "1112223334445")
        self.assertEqual(payload["npwpPengusaha"], "9911223344556677")
        self.assertEqual(payload["jenisAkses"], "importer")
        self.assertEqual(payload["nomorSertifikatAhli"], "AK-UJI-0001")
        flattened = str(payload).lower()
        self.assertNotIn("nik", flattened,
                         "Payload tidak boleh memuat NIK Kepabeanan dalam bentuk apa pun.")

    def test_payload_carries_the_tax_rate_not_the_book_rate(self):
        """ndpbm adalah kurs KMK. Kurs pembukuan di sini membuat nilai rupiah PIB salah."""
        declaration = self._declaration()
        declaration.fx_rate_tax = 16123.0
        payload = declaration._ceisa_payload()
        self.assertEqual(payload["ndpbm"], 16123.0)

    def test_status_never_moves_backwards(self):
        """Status yang bisa mundur membuat pelacakan bergoyang setiap kali cron jalan."""
        declaration = self._declaration()
        declaration.action_submit()
        declaration.action_receive()
        declaration.action_respond(channel="green")
        declaration.action_release()
        self.assertEqual(declaration.state, "released")
        declaration._apply_ceisa_status({"status": "RECEIVED", "jalur": "HIJAU"})
        self.assertEqual(
            declaration.state, "released",
            "Status dari CEISA tidak boleh memundurkan deklarasi yang sudah dikeluarkan.",
        )

    def test_status_moves_forward_and_logs_a_milestone(self):
        declaration = self._declaration()
        declaration.action_submit()
        declaration._apply_ceisa_status({
            "status": "RESPONDED", "jalur": "MERAH",
            "nomorPendaftaran": "004512", "tanggalPendaftaran": "2026-09-18",
        })
        self.assertEqual(declaration.state, "responded")
        self.assertEqual(declaration.channel, "red")
        self.assertEqual(declaration.registration_number, "004512")
        codes = declaration.job_id.milestone_ids.filtered("actual_date").mapped(
            "milestone_type_id.code")
        self.assertIn("customs_responded", codes)
        self.assertIn("customs_red_lane", codes,
                      "Jalur merah adalah kejadian pengecualian dan harus tercatat sebagai milestone.")
        sources = declaration.job_id.milestone_ids.filtered(
            lambda m: m.milestone_type_id.code == "customs_responded").mapped("source")
        self.assertEqual(sources, ["ceisa"],
                         "Sumber milestone harus 'ceisa', bukan 'manual'.")

    def test_token_is_reused_while_fresh_and_refetched_when_stale(self):
        """Token di-cache di DATABASE, dan kesegarannya diperiksa setiap kali.

        Tidak menyentuh jaringan: cache diisi tangan, lalu yang diuji adalah
        KEPUTUSANNYA — pakai ulang atau ambil baru.
        """
        from odoo import fields
        client = self.env["lgx.ceisa.client"]
        self.company.sudo().write({
            "lgx_ceisa_token": "token-masih-segar",
            "lgx_ceisa_token_expiry": fields.Datetime.add(fields.Datetime.now(), seconds=600),
        })
        self.assertEqual(client._lgx_ceisa_token(self.company), "token-masih-segar")

        # Kedaluwarsa dalam 5 detik, margin default 15 detik: harus dianggap basi
        # SEBELUM benar-benar mati, kalau tidak sebagian request berangkat dengan
        # token yang kedaluwarsa di tengah jalan.
        self.company.sudo().write({
            "lgx_ceisa_token_expiry": fields.Datetime.add(fields.Datetime.now(), seconds=5),
        })
        self.company.sudo().lgx_ceisa_base_url = "http://127.0.0.1:1"  # sengaja tidak dapat dihubungi
        from odoo.addons.queue_job.exception import RetryableJobError
        with self.assertRaises(RetryableJobError):
            client._lgx_ceisa_token(self.company)
