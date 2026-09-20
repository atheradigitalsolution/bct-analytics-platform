# -*- coding: utf-8 -*-
"""Tes NLE terhadap lgx-mock. Ditandai `lgx_live`, di luar lari default."""
import socket

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


def mock_reachable(host="lgx-mock", port=4020, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@tagged("-standard", "lgx_live")
class TestNleAgainstMock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "lgx_nle_enabled": True,
            "lgx_nle_base_url": "http://lgx-mock:4020",
            "lgx_nle_api_key": "dev-nle-key",
            "lgx_nle_id_platform": "ATHERA-DEV",
        })

    def setUp(self):
        super().setUp()
        if not mock_reachable():
            self.skipTest("Container lgx-mock tidak dapat dihubungi.")

    def test_wrong_api_key_is_rejected(self):
        self.company.sudo().lgx_nle_api_key = "kunci-salah"
        with self.assertRaises(UserError) as ctx:
            self.env["lgx.nle.client"]._call(
                self.company, "GET", "/V1/NLE/customs/status",
                params={"bl_no": "MAEU987654321"})
        self.assertIn("403", str(ctx.exception))
        self.company.sudo().lgx_nle_api_key = "dev-nle-key"

    def test_malformed_request_fails_with_http_400(self):
        """Permintaan yang bentuknya salah ditolak dengan 400, dan itu galat permanen."""
        with self.assertRaises(UserError) as ctx:
            self.env["lgx.nle.client"]._call(
                self.company, "POST", "/V1/NLE/document_do/final",
                payload={"bl_no": "MAEU987654321"})  # field wajib sengaja tidak lengkap
        self.assertIn("400", str(ctx.exception))

    def test_business_rejection_arrives_as_http_200_and_is_still_a_failure(self):
        """NLE menjawab 200 dengan `status: Failed` untuk penolakan aturan bisnis.

        Bentuk permintaannya benar; isinya yang ditolak. Klien yang hanya
        memeriksa kode HTTP akan mencatat kegagalan ini sebagai SUKSES — dan DO
        yang tidak pernah terbit akan tampak terbit, sampai ada yang menanyakan
        kenapa kontainer tidak bisa diambil.
        """
        with self.assertRaises(UserError) as ctx:
            self.env["lgx.nle.client"]._call(
                self.company, "POST", "/V1/NLE/document_do/final",
                payload={
                    "shipping_name": "Maersk", "forwarder_name": "ATHERA",
                    "bl_no": "UNKNOWN-123", "npwp_cargo_owner": "9911223344551122",
                    "id_platform": "ATHERA-DEV",
                })
        self.assertIn("menolak", str(ctx.exception).lower())
        self.assertIn("tidak ditemukan", str(ctx.exception).lower())
