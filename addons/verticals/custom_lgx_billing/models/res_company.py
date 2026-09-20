# -*- coding: utf-8 -*-
"""Peta akun logistik, di tingkat perusahaan.

Empat akun, dan masing-masing ada karena satu kesalahan tertentu mahal:

* ``lgx_disbursement_account_id``  talangan tidak boleh menyentuh pendapatan dan
                                   beban. Akun kliring ini yang menahannya di
                                   neraca.
* ``lgx_accrual_account_id``       biaya estimasi yang belum ditagih vendor.
                                   Tanpa ini, laba bulan berjalan selalu terlalu
                                   optimistis lalu dikoreksi turun belakangan.
* ``lgx_provision_account_id``     sisa akrual pada job yang ditutup finansial.
                                   Tagihan yang datang kemudian membebani
                                   provisi, bukan laba rugi periode berjalan.
* ``lgx_variance_account_id``      selisih estimasi versus aktual, terlihat
                                   sebagai satu angka yang bisa ditanyakan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    lgx_disbursement_account_id = fields.Many2one(
        "account.account", "Akun Kliring Talangan",
        domain="[('account_type','in',('asset_current','asset_receivable','liability_current'))]",
        help="Akun NERACA. Talangan masuk dan keluar lewat sini sehingga dampaknya "
             "ke laba rugi nol. Saldo yang tersisa pada job tertutup berarti ada "
             "talangan yang tidak pernah ditagihkan.",
    )
    lgx_accrual_account_id = fields.Many2one(
        "account.account", "Akun Akrual Biaya Belum Ditagih",
        domain="[('account_type','in',('liability_current','liability_payable'))]",
    )
    lgx_provision_account_id = fields.Many2one(
        "account.account", "Akun Provisi Job Tertutup",
        domain="[('account_type','in',('liability_current','liability_payable'))]",
    )
    lgx_variance_account_id = fields.Many2one(
        "account.account", "Akun Varians Biaya Job",
        domain="[('account_type','in',('expense','expense_direct_cost','income_other'))]",
    )
    lgx_accrual_journal_id = fields.Many2one(
        "account.journal", "Jurnal Akrual & Provisi", domain="[('type','=','general')]",
    )

    def lgx_check_accounts(self):
        """Gagal lebih awal dan menyebut apa yang kurang.

        Dipanggil sebelum setiap posting. Menemukan akun yang belum diatur saat
        jurnal sudah separuh terbentuk jauh lebih mahal daripada menolaknya di
        depan.
        """
        self.ensure_one()
        missing = []
        for fname, label in (
            ("lgx_disbursement_account_id", _("Akun Kliring Talangan")),
            ("lgx_accrual_account_id", _("Akun Akrual Biaya Belum Ditagih")),
            ("lgx_provision_account_id", _("Akun Provisi Job Tertutup")),
            ("lgx_variance_account_id", _("Akun Varians Biaya Job")),
            ("lgx_accrual_journal_id", _("Jurnal Akrual & Provisi")),
        ):
            if not self[fname]:
                missing.append(label)
        if missing:
            raise UserError(_(
                "Peta akun logistik belum lengkap pada perusahaan %s:\n\n%s\n\n"
                "Atur di Pengaturan → Logistik. Tanpa akun-akun ini, talangan akan "
                "melewati laba rugi dan margin per job menjadi angka yang salah.",
                self.display_name, "\n".join("• " + m for m in missing),
            ))
        return True

    # --- penyiapan otomatis -------------------------------------------------
    # Kode akun di bawah mengikuti bagan 10 digit Indonesia (l10n_id_coa_10d):
    # 5xxx pendapatan, 6xxx beban pokok. Dipisah per kelompok jasa dan bukan satu
    # akun tunggal, karena laporan laba per segmen di §H01 dihitung dari akun ini;
    # satu akun untuk semuanya berarti segmen hanya bisa dipisah lewat analitik,
    # dan analitik adalah hal pertama yang berhenti diisi orang.
    LGX_REVENUE_ACCOUNTS = [
        ("5101900001", "Pendapatan Jasa Freight", ("freight", "thc")),
        ("5101900002", "Pendapatan Jasa Dokumen & Handling",
         ("documentation", "handling", "customs", "insurance", "vas", "other", "demurrage", "detention")),
        ("5101900003", "Pendapatan Jasa Trucking", ("trucking",)),
        ("5101900004", "Pendapatan Jasa Pergudangan", ("storage",)),
    ]
    LGX_EXPENSE_ACCOUNTS = [
        ("6101900001", "Beban Pokok Freight", ("freight", "thc")),
        ("6101900002", "Beban Pokok Dokumen & Handling",
         ("documentation", "handling", "customs", "insurance", "vas", "other", "demurrage", "detention")),
        ("6101900003", "Beban Pokok Trucking", ("trucking",)),
        ("6101900004", "Beban Pokok Pergudangan", ("storage",)),
    ]

    def _lgx_ensure_account(self, code, name, account_type, reconcile=False):
        self.ensure_one()
        Account = self.env["account.account"]
        account = Account.search(
            [("code", "=", code), ("company_ids", "in", self.id)], limit=1)
        if not account:
            account = Account.create({
                "code": code,
                "name": name,
                "account_type": account_type,
                "reconcile": reconcile,
                "company_ids": [(4, self.id)],
            })
        return account

    def lgx_setup_default_accounts(self):
        """Siapkan seluruh peta akun logistik, idempoten.

        Ditulis sebagai method dan bukan skrip sekali pakai karena tiga tempat
        membutuhkannya dengan hasil yang harus identik: penyiapan tenant baru,
        tombol di Pengaturan, dan setUpClass tes. Skrip yang dijalankan sekali di
        shell adalah bentuk yang membuat database produksi dan database tes
        diam-diam berbeda.
        """
        for company in self:
            if not company.lgx_disbursement_account_id:
                company.lgx_disbursement_account_id = company._lgx_ensure_account(
                    "1108900001", "Kliring Talangan Logistik", "asset_current", True)
            if not company.lgx_accrual_account_id:
                company.lgx_accrual_account_id = company._lgx_ensure_account(
                    "2103900001", "Akrual Biaya Logistik Belum Ditagih", "liability_current", True)
            if not company.lgx_provision_account_id:
                company.lgx_provision_account_id = company._lgx_ensure_account(
                    "2103900002", "Provisi Job Logistik Tertutup", "liability_current", True)
            if not company.lgx_variance_account_id:
                company.lgx_variance_account_id = company._lgx_ensure_account(
                    "6109900001", "Varians Biaya Job Logistik", "expense")
            if not company.lgx_accrual_journal_id:
                journal = self.env["account.journal"].search(
                    [("code", "=", "LGXAP"), ("company_id", "=", company.id)], limit=1)
                if not journal:
                    journal = self.env["account.journal"].create({
                        "name": "Akrual & Provisi Logistik",
                        "code": "LGXAP",
                        "type": "general",
                        "company_id": company.id,
                    })
                company.lgx_accrual_journal_id = journal

            revenue_by_category = {}
            for code, name, categories in company.LGX_REVENUE_ACCOUNTS:
                account = company._lgx_ensure_account(code, name, "income")
                for category in categories:
                    revenue_by_category[category] = account
            expense_by_category = {}
            for code, name, categories in company.LGX_EXPENSE_ACCOUNTS:
                account = company._lgx_ensure_account(code, name, "expense_direct_cost")
                for category in categories:
                    expense_by_category[category] = account

            # Hanya kode charge yang BELUM punya akun yang diisi. Pemetaan yang
            # sudah disesuaikan tangan tidak boleh ditimpa oleh penyiapan ulang.
            charge_codes = self.env["lgx.charge.code"].with_context(active_test=False).search([])
            for charge_code in charge_codes:
                vals = {}
                if not charge_code.revenue_account_id:
                    account = revenue_by_category.get(charge_code.category)
                    if account:
                        vals["revenue_account_id"] = account.id
                if not charge_code.expense_account_id:
                    account = expense_by_category.get(charge_code.category)
                    if account:
                        vals["expense_account_id"] = account.id
                if vals:
                    charge_code.write(vals)
        return True
