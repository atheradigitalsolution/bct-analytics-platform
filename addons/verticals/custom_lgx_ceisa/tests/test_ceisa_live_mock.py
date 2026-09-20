# -*- coding: utf-8 -*-
"""Tes yang BENAR-BENAR memanggil lgx-mock.

Ditandai `lgx_live` dan dikecualikan dari lari default, karena ia bergantung
pada container `lgx-mock` yang hidup. Menjalankannya:

    odoo -d athera_lgx -u custom_lgx_ceisa --test-enable --test-tags lgx_live

Nilainya bukan menguji mock-nya, melainkan menguji bahwa BENTUK panggilan kita
— header, amplop, penanganan token — cocok dengan sesuatu yang berbicara HTTP
sungguhan. Tes yang hanya memakai mock objek Python akan tetap hijau meski kita
salah menulis nama header.
"""
import socket

from odoo.tests import TransactionCase, tagged


def mock_reachable(host="lgx-mock", port=4020, timeout=2):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@tagged("-standard", "lgx_live")
class TestCeisaAgainstMock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            "lgx_ceisa_enabled": True,
            "lgx_ceisa_base_url": "http://lgx-mock:4020",
            "lgx_ceisa_client_id": "athera-lgx-dev",
            "lgx_ceisa_client_secret": "dev-secret",
        })

    def setUp(self):
        super().setUp()
        if not mock_reachable():
            self.skipTest("Container lgx-mock tidak dapat dihubungi.")

    def test_token_round_trip(self):
        client = self.env["lgx.ceisa.client"]
        token = client._lgx_ceisa_token(self.company, force_refresh=True)
        self.assertTrue(token)
        self.assertTrue(self.company.sudo().lgx_ceisa_token_expiry)

    def test_wrong_credentials_are_reported_not_retried_forever(self):
        """Kredensial salah adalah galat PERMANEN, bukan bahan retry.

        Mencobanya ulang seribu kali tidak akan membuatnya benar; yang terjadi
        hanyalah antrian penuh dan galat sesungguhnya terkubur.
        """
        from odoo.addons.queue_job.exception import RetryableJobError
        from odoo.exceptions import UserError
        self.company.sudo().lgx_ceisa_client_secret = "salah"
        client = self.env["lgx.ceisa.client"]
        try:
            with self.assertRaises(UserError) as ctx:
                client._lgx_ceisa_token(self.company, force_refresh=True)
            self.assertNotIsInstance(
                ctx.exception, RetryableJobError,
                "Kredensial salah tidak boleh dicoba ulang: delapan percobaan dengan "
                "backoff sampai dua jam hanya mengubur penyebabnya di percobaan pertama.",
            )
            self.assertIn("401", str(ctx.exception))
        finally:
            self.company.sudo().lgx_ceisa_client_secret = "dev-secret"
