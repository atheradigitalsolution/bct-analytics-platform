# -*- coding: utf-8 -*-
"""LGX-F09 — talangan tidak boleh melewati akun pendapatan dan beban.

Tiga tes yang spesifikasi sebut sebagai wajib ada di Fase 1 dan bukan belakangan,
karena keduanya menentukan BENTUK JURNAL: memperbaikinya setelah ada data
produksi jauh lebih mahal daripada membangunnya benar sejak awal.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import LgxAccountingCommon


@tagged("post_install", "-at_install")
class TestDisbursementClearing(LgxAccountingCommon):

    def test_all_disbursement_job_has_zero_profit_and_loss(self):
        """Job yang seluruh charge-nya talangan menghasilkan laba rugi NOL.

        Ini uji yang paling menentukan di modul ini. Pada job impor, bea masuk
        rutin berkali lipat nilai jasanya; kalau ia ikut lewat pendapatan dan
        HPP, omzet dan HPP sama-sama menggelembung, margin_pct menjadi angka
        yang tidak berarti, dan dasar pemotongan PPh 23 ikut salah.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_disb, "cost", 100_000_000, nature="disbursement")
        self._add_charge(job, self.charge_disb, "revenue", 100_000_000,
                         nature="disbursement", partner=self.customer, proof=True)
        job.action_confirm()
        job.action_post_accrual()

        bills = job.lgx_create_vendor_bills()
        bills.action_post()
        invoice = job.lgx_create_customer_invoice()
        invoice.action_post()

        pl_lines = self.env["account.move.line"].search([
            ("lgx_job_id", "=", job.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "in",
             ("income", "income_other", "expense", "expense_direct_cost", "expense_depreciation")),
        ])
        self.assertEqual(
            sum(pl_lines.mapped("balance")), 0.0,
            "Job yang seluruh charge-nya talangan menyentuh laba rugi sebesar %s. "
            "Talangan harus mengalir lewat akun kliring di neraca." % sum(pl_lines.mapped("balance")),
        )
        self.assertEqual(
            job.margin, 0.0,
            "Margin job talangan murni harus nol; yang terhitung %s." % job.margin,
        )

    def test_clearing_account_returns_to_zero_after_invoice(self):
        """Akun kliring talangan per job bersaldo NOL setelah faktur pelanggan diposting.

        Saldo yang tersisa berarti ada talangan yang dibayarkan tetapi tidak
        pernah ditagihkan kembali — kas yang hilang diam-diam, dan itulah yang
        laporan 'Talangan Belum Tertagih' cari.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_disb, "cost", 55_000_000, nature="disbursement")
        self._add_charge(job, self.charge_disb, "revenue", 55_000_000,
                         nature="disbursement", partner=self.customer, proof=True)
        job.action_confirm()
        job.action_post_accrual()
        job.lgx_create_vendor_bills().action_post()
        job.lgx_create_customer_invoice().action_post()

        balance = self._balance_of(self.company.lgx_disbursement_account_id, job)
        self.assertAlmostEqual(
            balance, 0.0, places=2,
            msg="Akun kliring talangan job %s bersaldo %s, seharusnya nol." % (job.name, balance),
        )

    def test_disbursement_without_proof_cannot_be_invoiced(self):
        """Talangan tanpa bukti pihak ketiga ditolak, dan pesannya menyebut barisnya.

        PMK 141/2015: jumlah bruto dasar PPh 23 tidak termasuk reimbursement
        sepanjang DAPAT DIBUKTIKAN dengan faktur tagihan dan/atau bukti
        pembayaran dari pihak ketiga. Tanpa lampiran itu, pengecualiannya tidak
        dapat dipertahankan.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_disb, "revenue", 10_000_000,
                         nature="disbursement", partner=self.customer, proof=False)
        job.action_confirm()
        with self.assertRaises(UserError) as ctx:
            job.lgx_create_customer_invoice()
        self.assertIn(
            self.charge_disb.code, str(ctx.exception),
            "Pesan penolakan harus menyebut baris mana yang kurang bukti.",
        )

    def test_service_job_profit_and_loss_is_not_zero(self):
        """Kontrol negatif: job jasa biasa TETAP menyentuh laba rugi.

        Tanpa tes ini, sebuah bug yang membuat semua posting tidak pernah
        mencapai laba rugi akan membuat ketiga tes di atas hijau. Tes yang tidak
        pernah bisa merah tidak menguji apa pun.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_service, "revenue", 20_000_000,
                         nature="service", partner=self.customer)
        self._add_charge(job, self.charge_service, "cost", 12_000_000, nature="service")
        job.action_confirm()
        job.action_post_accrual()
        job.lgx_create_customer_invoice().action_post()

        pl_lines = self.env["account.move.line"].search([
            ("lgx_job_id", "=", job.id),
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "in",
             ("income", "income_other", "expense", "expense_direct_cost")),
        ])
        self.assertNotEqual(
            sum(pl_lines.mapped("balance")), 0.0,
            "Job jasa harus menyentuh laba rugi. Nol di sini berarti posting tidak "
            "pernah sampai ke akun laba rugi, dan tes talangan menjadi tidak berarti.",
        )
        self.assertEqual(job.margin, 8_000_000.0)
