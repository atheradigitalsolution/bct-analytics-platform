# -*- coding: utf-8 -*-
"""Dasar dan tarif pot-put — termasuk dua hal yang paling sering salah.

Yang pertama: baris talangan dikeluarkan dari jumlah bruto (PMK 141/2015).
Yang kedua: yang diuji NPWP-nya adalah PENERIMA PENGHASILAN, bukan lawan
transaksi. Keduanya menghasilkan selisih 100% ketika salah, dan keduanya tidak
terlihat salah di layar.
"""
from odoo.tests import tagged

from .common import LgxTaxCommon

NPWP_16 = "0011223344556677"


@tagged("post_install", "-at_install")
class TestWithholding(LgxTaxCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company.partner_id.vat = NPWP_16

    def test_disbursement_is_excluded_from_the_gross_base(self):
        """PMK 141/2015 — reimbursement tidak masuk jumlah bruto PPh 23.

        Memasukkannya berarti memotong 2% dari uang yang bukan penghasilan
        siapa pun. Uji ini menahan angkanya terpisah, bukan sekadar mengecek
        totalnya.
        """
        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_freight, "revenue", 20_000_000,
                         partner=self.customer)
        self._add_charge(job, self.charge_disb, "revenue", 5_000_000,
                         partner=self.customer, proof=True)
        invoice = self._invoice_for(job)

        self.assertAlmostEqual(invoice.lgx_wht_base, 20_000_000.0, places=2)
        self.assertAlmostEqual(
            invoice.lgx_wht_excluded, 5_000_000.0, places=2,
            msg="Nilai yang dikecualikan harus tetap terlihat, bukan hilang dari "
                "dokumen — saat pemeriksaan, angka inilah yang harus dijelaskan.",
        )
        self.assertEqual(invoice.lgx_wht_type, "pph23")
        self.assertAlmostEqual(invoice.lgx_wht_rate, 2.0, places=2)
        self.assertAlmostEqual(invoice.lgx_wht_amount, 400_000.0, places=2)

    def test_rate_doubles_when_the_recipient_has_no_npwp(self):
        """UU PPh Pasal 23 ayat 1a — tanpa NPWP penerima, tarifnya 100% lebih tinggi."""
        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_freight, "cost", 10_000_000)
        job.action_confirm()
        job.action_post_accrual()

        self.vendor.vat = False
        bill = job.lgx_create_vendor_bills()
        self.assertAlmostEqual(
            bill.lgx_wht_rate, 4.0, places=2,
            msg="Vendor tanpa NPWP harus dipotong 4%%, bukan 2%%.",
        )

        self.vendor.vat = NPWP_16
        bill.invalidate_recordset()
        bill._compute_lgx_wht()
        self.assertAlmostEqual(bill.lgx_wht_rate, 2.0, places=2)

    def test_recipient_on_a_sales_invoice_is_our_own_company(self):
        """Pada faktur penjualan, pelanggan memotong KITA — jadi NPWP kita yang diuji.

        Menguji NPWP pelanggan di sini menghasilkan tarif yang salah setiap kali
        salah satu pihak tidak ber-NPWP, dan arah salahnya tidak konsisten.
        """
        self.customer.vat = False
        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_freight, "revenue", 10_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        self.assertEqual(invoice._lgx_wht_recipient(), self.company.partner_id)
        self.assertAlmostEqual(
            invoice.lgx_wht_rate, 2.0, places=2,
            msg="Pelanggan tanpa NPWP tidak boleh menaikkan tarif atas penghasilan KITA.",
        )

    def test_rate_follows_the_invoice_date_not_today(self):
        """Faktur lama yang dibuka kembali harus memakai tarif yang berlaku saat itu.

        Kalau tidak, membuka dokumen lama diam-diam mengubah angkanya, dan
        rekonsiliasi terhadap bukti potong yang sudah diterbitkan tidak pernah
        cocok lagi.
        """
        seeded = self.env.ref("custom_lgx_tax_id.wht_pph23")
        seeded.valid_to = "2025-12-31"
        self.env["lgx.wht.rate"].create({
            "name": "PPh 23 — tarif uji sesudah 2026",
            "wht_type": "pph23", "rate": 3.0, "rate_no_npwp": 6.0,
            "valid_from": "2026-01-01",
        })

        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_freight, "revenue", 10_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        invoice.invoice_date = "2025-06-01"
        self.assertAlmostEqual(
            invoice.lgx_wht_rate, 2.0, places=2,
            msg="Faktur bertanggal 2025 harus memakai tarif 2025.",
        )
        invoice.invoice_date = "2026-06-01"
        self.assertAlmostEqual(invoice.lgx_wht_rate, 3.0, places=2)

    def test_pph15_domestic_air_is_not_final(self):
        """Butir A4 — SE-35/PJ.4/1996: 1,8%% penerbangan dalam negeri dapat dikreditkan.

        Banyak sumber sekunder menyebutnya final. Mengikutinya berarti membuang
        kredit pajak yang sah, setiap tahun, tanpa ada yang menagihnya kembali.
        """
        air = self.env.ref("custom_lgx_tax_id.wht_pph15_air")
        sea = self.env.ref("custom_lgx_tax_id.wht_pph15_sea")
        self.assertFalse(air.is_final, "PPh 15 penerbangan dalam negeri TIDAK final.")
        self.assertTrue(sea.is_final, "PPh 15 pelayaran dalam negeri final.")
        self.assertAlmostEqual(air.rate, 1.8, places=2)
        self.assertAlmostEqual(sea.rate, 1.2, places=2)

    def test_charge_lines_inherit_pph23_from_the_master(self):
        """Jembatan ke perbaikan di lgx.job.charge.create().

        Fixture ini tidak pernah menyebut `wht_type`, persis seperti API dan
        impor. Kalau pewarisannya hilang lagi, PPh 23 di sini kembali nol dan
        uji ini yang menangkapnya.
        """
        job = self._make_job(job_type="ff_import")
        charge = self._add_charge(job, self.charge_freight, "revenue", 10_000_000,
                                  partner=self.customer)
        self.assertEqual(charge.wht_type, "pph23")
        self.assertTrue(charge.is_freight_charge)
