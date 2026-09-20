# -*- coding: utf-8 -*-
"""LGX-F05 dan LGX-F10 — akrual, varians, dan penutupan finansial lewat provisi."""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import LgxAccountingCommon


@tagged("post_install", "-at_install")
class TestAccrualAndProvision(LgxAccountingCommon):

    def test_estimated_cost_forms_accrual(self):
        """Biaya estimasi membentuk akrual di buku besar, bukan sekadar angka di layar.

        Tanpa ini, laporan laba bulan berjalan selalu terlalu optimistis: seluruh
        pendapatan sudah tercatat sementara biaya vendor baru muncul dua sampai
        enam minggu kemudian.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_service, "cost", 30_000_000, nature="service")
        job.action_confirm()
        job.action_post_accrual()

        accrual_balance = self._balance_of(self.company.lgx_accrual_account_id, job)
        self.assertAlmostEqual(
            accrual_balance, -30_000_000.0, places=2,
            msg="Akrual seharusnya bersaldo kredit 30.000.000; yang terbaca %s." % accrual_balance,
        )
        self.assertTrue(job.accrual_posted)

    def test_vendor_bill_clears_accrual_and_books_variance(self):
        """Tagihan vendor membalik akrual; selisihnya masuk akun varians, bukan menggantung.

        Yang diuji bukan hanya angka variansnya, melainkan bahwa AKRUAL BERAKHIR
        NOL. Akrual yang tidak pernah nol adalah saldo yang berhenti berarti
        'yang benar-benar belum ditagih', dan begitu itu terjadi tidak ada lagi
        cara mengetahui seberapa dipercaya angka margin.
        """
        job = self._make_job()
        charge = self._add_charge(job, self.charge_service, "cost", 30_000_000, nature="service")
        job.action_confirm()
        job.action_post_accrual()

        bill = job.lgx_create_vendor_bills()
        bill.invoice_line_ids.write({"price_unit": 34_000_000})
        bill.action_post()

        self.assertTrue(charge.is_actual_known)
        self.assertAlmostEqual(charge.amount_actual, 34_000_000.0, places=2)
        self.assertAlmostEqual(charge.amount_variance, 4_000_000.0, places=2)

        accrual_balance = self._balance_of(self.company.lgx_accrual_account_id, job)
        self.assertAlmostEqual(
            accrual_balance, 0.0, places=2,
            msg="Akrual harus berakhir nol setelah tagihan vendor; yang terbaca %s." % accrual_balance,
        )
        variance_balance = self._balance_of(self.company.lgx_variance_account_id, job)
        self.assertAlmostEqual(
            variance_balance, 4_000_000.0, places=2,
            msg="Selisih estimasi versus tagihan harus berdiri di akun varians.",
        )

    def test_job_cannot_close_with_open_estimate(self):
        """Job tidak dapat 'closed' penuh selama ada estimasi tanpa aktual, dan alasannya disebut."""
        job = self._make_job()
        self._add_charge(job, self.charge_service, "revenue", 20_000_000,
                         nature="service", partner=self.customer)
        self._add_charge(job, self.charge_service, "cost", 12_000_000, nature="service")
        job.action_confirm()
        job.action_start()
        self._complete_mandatory_milestones(job)
        job.action_complete()

        self.assertTrue(job.close_blocked_reason, "close_blocked_reason harus terisi.")
        with self.assertRaises(UserError) as ctx:
            job.action_close()
        self.assertIn("estimasi", str(ctx.exception).lower())

    def test_close_with_provision_freezes_estimate_instead_of_deleting_it(self):
        """LGX-F10 — sisa estimasi DIBEKUKAN ke akun provisi, bukan dihapus.

        Aturan polos 'tidak boleh tutup selama ada estimasi tanpa aktual' membuat
        hampir semua job menggantung, dan yang terjadi di lapangan adalah staf
        menolkan estimasi supaya job bisa ditutup — persis kebocoran yang aturan
        itu ingin cegah. Karena itu penutupan finansial memindahkan nilainya,
        tidak menghilangkannya.
        """
        job = self._make_job()
        self._add_charge(job, self.charge_service, "revenue", 20_000_000,
                         nature="service", partner=self.customer)
        cost = self._add_charge(job, self.charge_service, "cost", 12_000_000, nature="service")
        job.action_confirm()
        job.action_post_accrual()
        job.lgx_create_customer_invoice().action_post()
        job.action_start()
        self._complete_mandatory_milestones(job)
        job.action_complete()
        job.action_close_with_provision()

        self.assertEqual(job.state, "closed_provisioned")
        self.assertEqual(cost.state, "provisioned")
        self.assertTrue(cost.provision_date)
        self.assertAlmostEqual(
            cost.amount_estimated, 12_000_000.0, places=2,
            msg="Nilai estimasi tidak boleh dinolkan oleh penutupan finansial.",
        )

        accrual = self._balance_of(self.company.lgx_accrual_account_id, job)
        provision = self._balance_of(self.company.lgx_provision_account_id, job)
        self.assertAlmostEqual(accrual, 0.0, places=2,
                               msg="Akrual harus kosong setelah dipindahkan ke provisi.")
        self.assertAlmostEqual(provision, -12_000_000.0, places=2,
                               msg="Provisi harus memegang sisa estimasi, bersaldo kredit.")

    def test_late_bill_charges_the_provision_not_the_period_profit(self):
        """Tagihan yang datang setelah penutupan membebani PROVISI, bukan laba rugi periode berjalan.

        Inilah alasan provisi ada. Kalau tagihan telat membuka kembali beban,
        margin periode yang sudah dilaporkan berubah setelah ditutup — dan angka
        yang berubah setelah dilaporkan adalah angka yang berhenti dipercaya.
        """
        job = self._make_job()
        cost = self._add_charge(job, self.charge_service, "cost", 12_000_000, nature="service")
        job.action_confirm()
        job.action_post_accrual()
        job.action_start()
        self._complete_mandatory_milestones(job)
        job.action_complete()
        job.action_close_with_provision()

        expense_before = self._balance_of(
            self.env["account.account"].browse(cost._lgx_expense_account().id), job)

        bill = job.lgx_create_vendor_bills()
        bill.action_post()

        expense_after = self._balance_of(
            self.env["account.account"].browse(cost._lgx_expense_account().id), job)
        self.assertAlmostEqual(
            expense_before, expense_after, places=2,
            msg="Tagihan telat mengubah beban dari %s menjadi %s. Ia seharusnya "
                "membebani provisi." % (expense_before, expense_after),
        )
        provision = self._balance_of(self.company.lgx_provision_account_id, job)
        self.assertAlmostEqual(
            provision, 0.0, places=2,
            msg="Provisi harus terpakai habis oleh tagihan yang datang; sisa %s." % provision,
        )
