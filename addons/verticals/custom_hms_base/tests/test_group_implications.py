# -*- coding: utf-8 -*-
"""Hibah hak antar-modul yang tidak bisa ditulis sebagai record XML.

Yang dijaga di sini bukan logika, melainkan sebuah kegagalan SENYAP:
`noupdate` melekat pada baris `ir.model.data` milik grupnya, bukan pada modul
penulis, sehingga `<record model="res.groups">` yang menambah `implied_ids`
akan dilewati tanpa satu pun pesan — hak terlihat diberikan di kode dan tidak
diberikan di basis data. Satu-satunya cara membuktikannya adalah memeriksa
basis datanya, bukan sumbernya.
"""
from odoo.tests import TransactionCase, tagged

MANAGER_GROUP = "custom_hms_base.group_hms_manager"
ANALYTIC_GROUP = "analytic.group_analytic_accounting"


@tagged("post_install", "-at_install", "hms")
class TestGroupImplications(TransactionCase):

    def test_manager_implies_analytic_accounting(self):
        """Tanpa ini `/api/v1/reports/unit-pnl` 403 untuk SETIAP peran.

        Laporan P&L per unit membaca `account.analytic.line`. Manajemen
        adalah pembacanya yang dituju, jadi hak itu harus benar-benar ada,
        bukan diakali `sudo()` di pengontrol.
        """
        analytic = self.env.ref(ANALYTIC_GROUP, raise_if_not_found=False)
        if not analytic:
            self.skipTest("modul `analytic` tidak terpasang di basis data ini")
        manager = self.env.ref(MANAGER_GROUP)
        self.assertIn(analytic, manager.implied_ids)

    def test_a_manager_user_can_read_analytic_lines(self):
        """Bukti dari sisi pengguna, bukan dari daftar grup.

        `implied_ids` hanya berarti kalau ia benar-benar mendarat di
        `res_groups_users_rel` pengguna yang bersangkutan.
        """
        if not self.env.ref(ANALYTIC_GROUP, raise_if_not_found=False):
            self.skipTest("modul `analytic` tidak terpasang di basis data ini")
        if "account.analytic.line" not in self.env:
            self.skipTest("model account.analytic.line tidak ada di basis data ini")
        user = self.env["res.users"].create({
            "name": "Manajer Uji", "login": "zt-base-manager",
            "group_ids": [(4, self.env.ref(MANAGER_GROUP).id)],
        })
        self.assertTrue(user.has_group(ANALYTIC_GROUP))
        self.env["account.analytic.line"].with_user(user).check_access("read")

    def test_applying_the_implications_again_is_idempotent(self):
        """Dijalankan ulang pada setiap `-u`; pengulangan tidak boleh menumpuk."""
        before = len(self.env.ref(MANAGER_GROUP).implied_ids)
        granted = self.env["res.groups"]._hms_apply_group_implications()
        self.assertEqual(granted, 0)
        self.assertEqual(len(self.env.ref(MANAGER_GROUP).implied_ids), before)
