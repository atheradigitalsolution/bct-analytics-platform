# -*- coding: utf-8 -*-
"""§11.1 — alur keputusan PPN, tiap cabang dilewati sungguhan.

Ini logika paling berkonsekuensi hukum di seluruh vertikal: salah cabang berarti
selisih tarif sepuluh kali lipat dan pajak masukan yang dikreditkan padahal tidak
boleh. Sebelum berkas ini ada, tidak ada satu pun uji yang menyentuhnya.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LgxTaxCommon


@tagged("post_install", "-at_install")
class TestVatTreatment(LgxTaxCommon):

    def test_jpt_with_freight_charge_is_besaran_tertentu(self):
        """JPT + ada freight charge → 1,1%, kode faktur 05, PM tidak dapat dikreditkan.

        Syarat PMK 71/2022 ada dua dan keduanya harus terpenuhi bersama. Uji ini
        memegang kasus yang memang terpenuhi.
        """
        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_freight, "revenue", 25_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        self.assertTrue(invoice.lgx_has_freight_charge)
        self.assertEqual(invoice.lgx_vat_treatment, "besaran_tertentu")
        self.assertEqual(invoice.lgx_faktur_code, "05")
        self.assertTrue(
            invoice.lgx_input_vat_not_creditable,
            "Penyerahan JKP Tertentu membuat pajak masukan terkait tidak dapat "
            "dikreditkan; mengkreditkannya adalah koreksi saat pemeriksaan.",
        )

    def test_jpt_without_freight_charge_falls_back_to_normal_rate(self):
        """Butir A3 — tanpa freight charge, penyerahannya BUKAN JKP Tertentu.

        PMK 71/2022 mensyaratkan tagihan MEMUAT biaya transportasi. Tanpa itu
        syaratnya tidak terpenuhi dan tarif umum yang berlaku — dan pajak
        masukannya kembali dapat dikreditkan.
        """
        job = self._make_job(job_type="ff_import")
        self._add_charge(job, self.charge_nonfreight, "revenue", 3_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        self.assertFalse(invoice.lgx_has_freight_charge)
        self.assertEqual(invoice.lgx_vat_treatment, "standard")
        self.assertEqual(invoice.lgx_faktur_code, "01")
        self.assertFalse(invoice.lgx_input_vat_not_creditable)
        self.assertTrue(
            invoice.lgx_vat_warning,
            "Perbedaan 1,1% versus tarif umum tidak boleh terjadi tanpa seorang "
            "pun melihatnya; peringatannya wajib muncul.",
        )
        self.assertIn("71/2022", invoice.lgx_vat_warning)

    def test_default_without_freight_follows_the_parameter(self):
        """Tarif fallback datang dari parameter, bukan konstanta di kode.

        Kalau suatu saat tarif umum berubah atau DJP menegaskan perlakuan lain,
        yang berubah harus satu baris konfigurasi — bukan rilis modul.
        """
        self.env["ir.config_parameter"].sudo().set_param(
            "lgx.vat_default_without_freight", "not_collected")
        job = self._make_job(job_type="ff_export")
        self._add_charge(job, self.charge_nonfreight, "revenue", 3_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        self.assertEqual(invoice.lgx_vat_treatment, "not_collected")
        self.assertFalse(
            invoice.lgx_faktur_code,
            "Kode faktur 01 hanya sah untuk penyerahan normal; perlakuan lain "
            "tidak boleh diam-diam ikut memakai 01.",
        )

    def test_trucking_with_freight_charge_is_not_besaran_tertentu(self):
        """Trucking murni bukan JPT, meski barisnya freight charge.

        Inilah kasus yang paling mudah salah: kode biaya trucking ditandai
        freight, jadi separuh syaratnya terpenuhi. Yang menentukan tetap jenis
        job-nya, dan uji ini memegang perbedaan itu.
        """
        job = self._make_job(job_type="trucking")
        self.assertFalse(job.lgx_is_jpt())
        self._add_charge(job, self.charge_trucking, "revenue", 4_500_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)

        self.assertTrue(invoice.lgx_has_freight_charge)
        self.assertNotEqual(
            invoice.lgx_vat_treatment, "besaran_tertentu",
            "Freight charge saja tidak cukup; tanpa job JPT syarat PMK 71/2022 "
            "tidak terpenuhi.",
        )
        self.assertEqual(invoice.lgx_vat_treatment, "standard")
        self.assertFalse(invoice.lgx_input_vat_not_creditable)

    def test_export_service_zero_cannot_post_without_both_documents(self):
        """Ekspor jasa 0% diblokir posting sampai kontrak DAN bukti bayar ada.

        PMK 32/2019 menuntut keduanya. Fasilitas tarif nol yang tidak dapat
        dibuktikan gugur saat pemeriksaan, dan PPN-nya berbalik menjadi beban
        perusahaan sendiri — jadi ini validasi keras, bukan pengingat.
        """
        job = self._make_job(job_type="ff_export", direction="export")
        self._add_charge(job, self.charge_export, "revenue", 18_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)
        self.assertEqual(invoice.lgx_vat_treatment, "export_service_zero")
        self.assertEqual(invoice.lgx_faktur_code, "06")

        with self.assertRaises(UserError) as ctx:
            invoice.action_post()
        self.assertIn("kontrak", str(ctx.exception).lower())

        # Satu dokumen saja tetap tidak cukup.
        invoice.lgx_export_contract_ids = [(4, self._attachment("kontrak.pdf").id)]
        with self.assertRaises(UserError) as ctx:
            invoice.action_post()
        self.assertIn("bukti pembayaran", str(ctx.exception).lower())

        invoice.lgx_export_payment_proof_ids = [(4, self._attachment("swift.pdf").id)]
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_public_transport_exemption_demands_a_written_basis(self):
        """Pembebasan angkutan umum tidak boleh diputuskan diam-diam."""
        job = self._make_job(job_type="trucking")
        self._add_charge(job, self.charge_exempt, "revenue", 6_000_000,
                         partner=self.customer)
        invoice = self._invoice_for(job)
        self.assertEqual(invoice.lgx_vat_treatment, "exempt_public_transport")
        self.assertFalse(invoice.lgx_faktur_code)

        with self.assertRaises(UserError):
            invoice.action_post()

        invoice.lgx_exemption_basis = (
            "Angkutan umum berplat kuning, bukan sewa/charter, muatan lebih dari "
            "satu pihak dalam perjalanan yang sama."
        )
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    def test_invoice_without_job_is_left_alone(self):
        """Faktur non-logistik tidak boleh ikut diberi perlakuan PPN logistik.

        Modul ini mewarisi account.move secara global. Tanpa penjaga ini setiap
        faktur di seluruh database ikut dihitung, dan itu terlihat pertama kali
        sebagai kode faktur yang salah di penjualan yang sama sekali tidak
        berhubungan.
        """
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.customer.id,
        })
        self.assertFalse(move.lgx_vat_treatment)
        self.assertFalse(move.lgx_faktur_code)
        self.assertFalse(move.lgx_input_vat_not_creditable)
        self.assertFalse(move.lgx_has_freight_charge)
