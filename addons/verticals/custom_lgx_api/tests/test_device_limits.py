# -*- coding: utf-8 -*-
"""Batas penerbitan kunci perangkat punya DUA dimensi, dan satu angka tidak cukup.

Pola dari sesi SIMRS: satu angka untuk dua batas. `max_call_count = 3` mereka
benar sebagai hitungan dan diam sepenuhnya soal rentang waktunya, sehingga tiga
ketukan dalam lima detik menandai pasien tidak hadir.

Di sini bentuknya lebih telanjang: endpoint pendaftaran perangkat tidak punya
batas SAMA SEKALI. Dedup nama mencabut kunci lama hanya bila namanya sama, jadi
"hp-budi", "hp-budi-2", dan "hp budi" adalah tiga perangkat dengan tiga kunci
hidup 90 hari.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDeviceLimits(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.params = cls.env["ir.config_parameter"].sudo()
        cls.Device = cls.env["lgx.api.device"]
        cls.user = cls.env["res.users"].create({
            "name": "Pengemudi Perangkat", "login": "perangkat@uji.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.env.ref("custom_lgx_base.group_lgx_driver").id,
            ])],
        })

    def _terbitkan(self, nama):
        return self.Device.lgx_issue_key(self.user, "driver", nama)

    def test_active_device_count_is_capped(self):
        """Dimensi KEADAAN: berapa banyak yang hidup sekaligus."""
        self.params.set_param("lgx.device_max_active", 3)
        self.params.set_param("lgx.device_issue_max_per_window", 0)  # matikan dimensi laju
        for i in range(3):
            self._terbitkan("perangkat-%s" % i)
        with self.assertRaises(UserError) as ctx:
            self._terbitkan("perangkat-keempat")
        self.assertIn("batasnya", str(ctx.exception).lower())

    def test_revoking_frees_a_slot(self):
        """Kontrol positif: batas keadaan menghitung yang AKTIF, bukan yang pernah ada.

        Penjaga yang menghitung seluruh riwayat akan mengunci pengemudi yang
        jujur mengganti telepon tiga kali dalam setahun.
        """
        self.params.set_param("lgx.device_max_active", 2)
        self.params.set_param("lgx.device_issue_max_per_window", 0)
        d1, _k = self._terbitkan("lama")
        self._terbitkan("kedua")
        d1.action_revoke()
        device, kunci = self._terbitkan("pengganti")
        self.assertTrue(kunci)
        self.assertEqual(device.state, "active")

    def test_issue_rate_is_capped_within_a_window(self):
        """Dimensi LAJU: berapa cepat diterbitkan.

        Inilah yang menangkap akun yang disalahgunakan — ia mencetak banyak
        dalam waktu singkat, sementara pengemudi sungguhan mendaftar sekali
        lalu berhenti. Batas keadaan saja melewatkannya bila diselingi
        pencabutan.
        """
        self.params.set_param("lgx.device_max_active", 0)  # matikan dimensi keadaan
        self.params.set_param("lgx.device_issue_window_hours", 24)
        self.params.set_param("lgx.device_issue_max_per_window", 3)
        for i in range(3):
            device, _k = self._terbitkan("cepat-%s" % i)
            device.action_revoke()          # dicabut, jadi dimensi keadaan tidak menahan
        with self.assertRaises(UserError) as ctx:
            self._terbitkan("cepat-keempat")
        self.assertIn("jam", str(ctx.exception).lower())

    def test_re_registering_the_same_device_is_not_a_new_issue(self):
        """Kontrol positif: mengganti kunci perangkat yang SAMA tidak kena batas.

        Kalau ia kena, pengemudi yang aplikasinya terpasang ulang akan terkunci
        justru pada jalur yang paling wajar.
        """
        self.params.set_param("lgx.device_max_active", 1)
        self.params.set_param("lgx.device_issue_max_per_window", 1)
        self._terbitkan("hp-budi")
        device, kunci = self._terbitkan("hp-budi")
        self.assertTrue(kunci, "Pendaftaran ulang perangkat yang sama harus tetap bisa.")
        self.assertEqual(
            self.Device.search_count([("user_id", "=", self.user.id)]), 1,
            "Perangkat yang sama tidak boleh menjadi dua baris.")
