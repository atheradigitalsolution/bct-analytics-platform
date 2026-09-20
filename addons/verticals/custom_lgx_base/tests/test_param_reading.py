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


@tagged("post_install", "-at_install")
class TestKbliRequirementsSeeded(TransactionCase):
    """Catatan regulasi harus SAMPAI ke database, bukan hanya ada di berkas.

    Record KBLI lahir di blok noupdate="1", jadi field yang ditambahkan
    kemudian tidak pernah menyebar ke database yang sudah terpasang. Percobaan
    pertama butir A11 menaruh permit_form dan requirement_note sebagai field di
    record, dan keduanya tetap NULL setelah upgrade — berkasnya benar, kolomnya
    kosong, dan tidak ada galat apa pun.

    Uji ini menanyakan ke DATABASE, bukan ke berkas. Itu bedanya dengan
    membaca XML dan merasa yakin.
    """

    def test_shipping_licence_note_reaches_the_database(self):
        """BATASNYA disebut: uji ini menangkap pemasangan BARU yang gagal disemai.

        Ia TIDAK menangkap pencabutan <function> pada database yang sudah
        terisi — nilainya sudah ada di sana dan tidak hilang. Diukur, bukan
        diduga: pemanggilan penyemai dicabut dari berkas data, suite tetap
        hijau.

        Menyebut batas ini alih-alih mendiamkannya, karena uji yang dikira
        menjaga sesuatu padahal tidak adalah bentuk yang kami kejar seharian.
        Yang menjaga penyemainya sendiri adalah uji di bawah.
        """
        kbli = self.env["lgx.kbli"].search([("code", "=", "50131")], limit=1)
        self.assertTrue(kbli, "Prasyarat: KBLI 50131 harus ada.")
        self.assertTrue(
            kbli.permit_form,
            "permit_form kosong — catatan regulasi tidak sampai ke database. "
            "Kemungkinan besar ia ditaruh sebagai field di record noupdate, "
            "bukan disemai lewat <function>.",
        )
        self.assertIn("SIUPAL", kbli.permit_form)
        self.assertIn("PP 31/2021", kbli.requirement_note or "")

    def test_seeder_restores_notes_that_were_wiped(self):
        """Inilah yang benar-benar menguji penyemainya.

        Kosongkan kolomnya — meniru database yang belum pernah disemai — lalu
        panggil penyemai dan pastikan ia mengisinya kembali. Berbeda dari uji
        di atas, yang ini merah kalau penyemainya rusak, bukan hanya kalau
        databasenya kebetulan kosong.
        """
        Kbli = self.env["lgx.kbli"]
        kbli = Kbli.search([("code", "=", "50131")], limit=1)
        kbli.write({"permit_form": False, "requirement_note": False})
        kbli.invalidate_recordset()
        self.assertFalse(kbli.permit_form, "Prasyarat: kolomnya harus kosong dulu.")

        Kbli._lgx_seed_requirements()
        kbli.invalidate_recordset()
        self.assertIn("SIUPAL", kbli.permit_form or "")
        self.assertIn("PP 31/2021", kbli.requirement_note or "")

    def test_seeding_is_idempotent(self):
        """Dijalankan tiap update, jadi ia harus aman dijalankan berkali-kali."""
        Kbli = self.env["lgx.kbli"]
        pertama = Kbli._lgx_seed_requirements()
        kedua = Kbli._lgx_seed_requirements()
        self.assertEqual(pertama, kedua)
        self.assertGreater(pertama["disemai"], 0)

    def test_seeding_does_not_touch_is_verified(self):
        """`is_verified` diisi manusia setelah konfirmasi ke OSS.

        Penyemai yang menimpanya akan menghapus kerja itu tiap upgrade, diam-
        diam, dan gejalanya baru muncul sebagai daftar yang tidak pernah
        selesai diverifikasi.
        """
        kbli = self.env["lgx.kbli"].search([("code", "=", "50131")], limit=1)
        kbli.is_verified = True
        self.env["lgx.kbli"]._lgx_seed_requirements()
        kbli.invalidate_recordset()
        self.assertTrue(kbli.is_verified, "Penyemai tidak boleh menyentuh is_verified.")
