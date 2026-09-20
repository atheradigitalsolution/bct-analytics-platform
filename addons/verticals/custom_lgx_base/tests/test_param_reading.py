# -*- coding: utf-8 -*-
"""Parameter angka yang salah ketik tidak boleh menghentikan pekerjaan.

Tiga mode, dan hanya satu yang berbahaya — diukur, bukan diasumsikan:

    tidak ada         -> default          Odoo aman
    ada tapi kosong   -> default          Odoo memakai `or default`
    ada berisi "lima" -> "lima"           int() MELEMPAR ValueError

Mode ketiga dicari setelah sesi SIMRS melaporkan padanannya di os.environ:
`os.environ.get(key, default)` TIDAK mencapai default-nya ketika kuncinya ada
tapi kosong, karena compose meneruskan ${VAR:-}. Odoo tidak punya masalah itu;
yang dipunyainya masalah ketiga, dan itu baru terlihat setelah ditanyakan.
"""
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

KUNCI = "lgx.__uji_param__"


@tagged("post_install", "-at_install")
class TestParamReading(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.P = cls.env["ir.config_parameter"].sudo()

    def test_missing_key_uses_the_default(self):
        self.P.search([("key", "=", KUNCI)]).unlink()
        self.assertEqual(self.P.lgx_int(KUNCI, 480), 480)

    def test_empty_value_uses_the_default(self):
        """Odoo memakai `or default`, jadi kosong sudah aman.

        Dipegang sebagai tes supaya kalau perilaku itu berubah di versi
        berikutnya, kita tahu — dan bukan lewat angka yang diam-diam menjadi
        nol di perhitungan biaya.
        """
        self.P.set_param(KUNCI, "")
        self.assertEqual(self.P.lgx_int(KUNCI, 480), 480)

    @mute_logger("odoo.addons.custom_lgx_base.models.ir_config_parameter")
    def test_unreadable_value_falls_back_instead_of_raising(self):
        """Inilah yang diperbaiki. Sebelumnya int("lima") melempar ValueError.

        Parameter diisi manusia lewat layar Pengaturan; salah ketik di sana
        bukan kemungkinan teoretis.
        """
        self.P.set_param(KUNCI, "lima")
        self.assertEqual(self.P.lgx_int(KUNCI, 480), 480)
        self.assertAlmostEqual(self.P.lgx_float(KUNCI, 1.5), 1.5, places=3)

    def test_a_real_value_is_still_used(self):
        """Kontrol positif: penjaga tidak boleh menelan nilai yang sah.

        Penjaga yang selalu mengembalikan default akan lulus ketiga uji di atas
        dengan gemilang dan membuat seluruh parameter berhenti berfungsi.
        """
        self.P.set_param(KUNCI, "615")
        self.assertEqual(self.P.lgx_int(KUNCI, 480), 615)
        self.P.set_param(KUNCI, "2.75")
        self.assertAlmostEqual(self.P.lgx_float(KUNCI, 1.0), 2.75, places=3)

    @mute_logger("odoo.addons.custom_lgx_base.models.ir_config_parameter")
    def test_numeric_string_with_spaces_is_still_read(self):
        """Spasi di ujung adalah hasil tempel-salin, bukan salah ketik."""
        self.P.set_param(KUNCI, " 90 ")
        self.assertEqual(self.P.lgx_int(KUNCI, 30), 90)

    def tearDown(self):
        self.P.search([("key", "=", KUNCI)]).unlink()
        super().tearDown()
