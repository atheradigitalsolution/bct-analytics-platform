# -*- coding: utf-8 -*-
"""Baris charge yang lahir dari kode harus mewarisi keputusan pajak masternya.

`_onchange_charge_code` hanya berjalan di formulir. Selama pewarisannya hanya
ada di sana, setiap baris yang dibuat API, impor, konversi penawaran, billing
gudang, atau data demo diam-diam kehilangan `wht_type` dan `is_freight_charge`.
Kerugiannya tidak terlihat di layar mana pun — ia muncul sebagai PPh 23 yang
tidak pernah terhitung.
"""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestChargeMasterDefaults(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({
            "name": "PT Pelanggan Uji Charge", "company_type": "company",
        })
        cls.job = cls.env["lgx.job"].create({
            "job_type": "trucking",
            "transport_mode": "land",
            "customer_id": cls.customer.id,
            "origin_location_id": cls.env.ref("custom_lgx_base.loc_idjkt").id,
            "destination_location_id": cls.env.ref("custom_lgx_base.loc_idsub").id,
        })

    def _create(self, code, **extra):
        vals = {
            "job_id": self.job.id,
            "charge_code_id": code.id,
            "kind": "revenue",
            "quantity": 1.0,
            "unit_price": 1_000_000,
            "currency_id": self.job.currency_id.id,
        }
        vals.update(extra)
        return self.env["lgx.job.charge"].create(vals)

    def test_wht_type_is_inherited_from_the_master(self):
        """Regresi terukur: baris TRK di athera_lgx menyimpan 'none', masternya 'pph23'.

        Akibatnya PPh 23 atas jasa trucking tidak pernah terhitung pada faktur
        yang barisnya dibuat dari kode — dan angka nol tidak terlihat salah.
        """
        code = self.env.ref("custom_lgx_base.charge_trk")
        self.assertEqual(code.default_wht_type, "pph23", "Prasyarat master berubah.")
        charge = self._create(code)
        self.assertEqual(
            charge.wht_type, "pph23",
            "Baris yang dibuat dari kode harus mewarisi pot-put masternya; "
            "kalau ia 'none', PPh 23 hilang tanpa jejak.",
        )

    def test_freight_flag_is_inherited_from_the_master(self):
        """`is_freight_charge` menentukan cabang PPN besaran tertentu.

        Kalau ia kosong pada baris ocean freight sebuah job JPT, fakturnya
        keluar dengan tarif umum, bukan 1,1% — selisih sepuluh kali lipat.
        """
        code = self.env.ref("custom_lgx_base.charge_ofr")
        self.assertTrue(code.is_freight_charge, "Prasyarat master berubah.")
        charge = self._create(code)
        self.assertTrue(charge.is_freight_charge)

    def test_nature_is_inherited_so_disbursement_stays_out_of_the_wht_base(self):
        """Talangan yang lahir sebagai 'service' ikut masuk jumlah bruto PPh 23."""
        code = self.env.ref("custom_lgx_base.charge_bm")
        self.assertEqual(code.default_nature, "disbursement", "Prasyarat master berubah.")
        charge = self._create(code, kind="cost")
        self.assertEqual(charge.nature, "disbursement")

    def test_explicit_values_still_win_over_the_master(self):
        """Pemanggil yang menyebut nilainya secara eksplisit tidak boleh ditimpa.

        Billing gudang sengaja memaksa nature='service' dan kepabeanan memaksa
        'disbursement'. Pewarisan yang menimpa keduanya akan memperbaiki satu
        cacat sambil membuat dua yang baru.
        """
        code = self.env.ref("custom_lgx_base.charge_trk")
        charge = self._create(code, wht_type="none", nature="disbursement")
        self.assertEqual(charge.wht_type, "none")
        self.assertEqual(charge.nature, "disbursement")

    def test_inheritance_survives_batch_create(self):
        """create() menerima daftar; pewarisan tidak boleh hanya mengenai elemen pertama."""
        trk = self.env.ref("custom_lgx_base.charge_trk")
        ofr = self.env.ref("custom_lgx_base.charge_ofr")
        charges = self.env["lgx.job.charge"].create([
            {"job_id": self.job.id, "charge_code_id": trk.id, "kind": "revenue",
             "quantity": 1.0, "unit_price": 1_000_000, "currency_id": self.job.currency_id.id},
            {"job_id": self.job.id, "charge_code_id": ofr.id, "kind": "revenue",
             "quantity": 1.0, "unit_price": 2_000_000, "currency_id": self.job.currency_id.id},
        ])
        self.assertEqual(charges.mapped("wht_type"), ["pph23", "pph23"])
        self.assertEqual(charges.mapped("is_freight_charge"), [True, True])
