# -*- coding: utf-8 -*-
"""Lapisan akuntansi job: akrual, faktur, tagihan, provisi, varians.

BENTUK JURNAL YANG DIJAGA MODUL INI
-----------------------------------
Untuk satu baris biaya JASA dengan estimasi X dan tagihan vendor Y:

    1. Konfirmasi baris   Dr Beban X          Cr Akrual X
    2. Tagihan vendor     Dr Akrual Y         Cr Utang usaha Y
    3. Varians (Y - X)    Dr Varians (Y-X)    Cr Akrual (Y-X)

    Akrual berakhir nol. Beban tetap X — angka yang sudah dilaporkan tidak
    berubah — dan selisihnya berdiri sendiri di akun varians, tempat ia bisa
    ditanyakan.

Untuk satu baris biaya TALANGAN, langkah yang sama tetapi kaki bebannya diganti
akun kliring neraca:

    1. Konfirmasi baris   Dr Kliring X        Cr Akrual X
    2. Tagihan vendor     Dr Akrual Y         Cr Utang usaha Y
    3. Varians (Y - X)    Dr Kliring (Y-X)    Cr Akrual (Y-X)
    4. Ditagihkan ke klien Dr Piutang Z       Cr Kliring Z

    Dampak ke laba rugi NOL, dan kliring berakhir nol saat Z = Y. Kliring yang
    tidak nol berarti ada talangan yang tidak pernah ditagihkan — kas yang
    hilang diam-diam, dan itu laporan tersendiri.

Akrual DIBALIK OLEH TAGIHANNYA, bukan oleh pembalikan otomatis di awal periode
berikutnya. Pembalikan otomatis membuat biaya menghilang selama beberapa minggu
sampai tagihan datang, yang justru mengembalikan masalah yang akrual ini ada
untuk menutupinya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxJobCharge(models.Model):
    _inherit = "lgx.job.charge"

    accrual_line_id = fields.Many2one("account.move.line", "Baris Akrual", readonly=True, copy=False)
    provision_line_id = fields.Many2one("account.move.line", "Baris Provisi", readonly=True, copy=False)
    variance_line_id = fields.Many2one("account.move.line", "Baris Varians", readonly=True, copy=False)
    provision_date = fields.Date("Tanggal Provisi", readonly=True, copy=False)
    provision_age_days = fields.Integer("Umur Provisi (hari)", compute="_compute_provision_age")

    @api.depends("provision_date")
    def _compute_provision_age(self):
        today = fields.Date.context_today(self)
        for line in self:
            line.provision_age_days = (today - line.provision_date).days if line.provision_date else 0

    def _lgx_expense_account(self):
        """Kaki debit akrual: beban untuk jasa, kliring untuk talangan."""
        self.ensure_one()
        company = self.job_id.company_id
        if self.nature == "disbursement":
            return company.lgx_disbursement_account_id
        account = self.charge_code_id.expense_account_id
        if not account:
            product = self.charge_code_id.product_id
            account = product.product_tmpl_id.get_product_accounts(fiscal_pos=None)["expense"]
        if not account:
            raise UserError(_(
                "Kode charge %s tidak punya akun beban, dan produknya (%s) juga tidak. "
                "Akrual tidak dapat dibentuk tanpa akun tujuan.",
                self.charge_code_id.code, self.charge_code_id.product_id.display_name,
            ))
        return account

    def _lgx_revenue_account(self):
        """Kaki kredit faktur: pendapatan untuk jasa, kliring untuk talangan."""
        self.ensure_one()
        company = self.job_id.company_id
        if self.nature == "disbursement":
            return company.lgx_disbursement_account_id
        account = self.charge_code_id.revenue_account_id
        if not account:
            product = self.charge_code_id.product_id
            account = product.product_tmpl_id.get_product_accounts(fiscal_pos=None)["income"]
        if not account:
            raise UserError(_(
                "Kode charge %s tidak punya akun pendapatan, dan produknya juga tidak.",
                self.charge_code_id.code,
            ))
        return account

    def _lgx_bill_account(self):
        """Akun yang dipakai baris tagihan vendor.

        Akrual bila sudah diakrualkan, provisi bila job sudah ditutup finansial,
        dan akun beban langsung bila baris ini tidak pernah diakrualkan sama
        sekali. Tiga kasus, bukan satu, karena tagihan yang datang setelah
        penutupan harus membebani provisi — bukan membuka kembali laba rugi
        periode yang sudah dilaporkan.
        """
        self.ensure_one()
        company = self.job_id.company_id
        if self.state == "provisioned" and self.provision_line_id:
            return company.lgx_provision_account_id
        if self.accrual_line_id:
            return company.lgx_accrual_account_id
        return self._lgx_expense_account()

    def action_release_provision(self):
        """Lepaskan provisi yang tidak akan pernah ditagih, dengan persetujuan.

        Dr Provisi / Cr Varians. Provisi yang dilepas adalah keuntungan periode
        berjalan, bukan koreksi ke periode lama — periode lama sudah dilaporkan.
        """
        if not self.env.user.has_group("custom_lgx_base.group_lgx_finance_manager"):
            raise UserError(_("Hanya manajer keuangan yang dapat melepaskan provisi."))
        for line in self:
            if line.state != "provisioned" or not line.provision_line_id:
                continue
            company = line.job_id.company_id
            company.lgx_check_accounts()
            move = self.env["account.move"].create({
                "move_type": "entry",
                "journal_id": company.lgx_accrual_journal_id.id,
                "date": fields.Date.context_today(line),
                "ref": _("Pelepasan provisi %s — job %s", line.charge_code_id.code, line.job_id.name),
                "lgx_job_id": line.job_id.id,
                "line_ids": [
                    (0, 0, {
                        "name": _("Pelepasan provisi %s", line.charge_code_id.code),
                        "account_id": company.lgx_provision_account_id.id,
                        "debit": line.amount_estimated,
                        "credit": 0.0,
                        "lgx_charge_id": line.id,
                    }),
                    (0, 0, {
                        "name": _("Pelepasan provisi %s", line.charge_code_id.code),
                        "account_id": company.lgx_variance_account_id.id,
                        "debit": 0.0,
                        "credit": line.amount_estimated,
                    }),
                ],
            })
            move.action_post()
            line.write({"state": "closed", "is_actual_known": True, "amount_actual": 0.0})
        return True


class LgxJob(models.Model):
    _inherit = "lgx.job"

    invoice_ids = fields.One2many("account.move", "lgx_job_id", "Dokumen Akuntansi")
    invoice_count = fields.Integer("Jumlah Dokumen", compute="_compute_invoice_stats")
    amount_invoiced = fields.Monetary("Sudah Difakturkan", compute="_compute_invoice_stats", store=True)
    amount_to_invoice = fields.Monetary("Belum Difakturkan", compute="_compute_invoice_stats", store=True)
    accrual_posted = fields.Boolean("Akrual Terposting", compute="_compute_invoice_stats", store=True)

    @api.depends("charge_ids.state", "charge_ids.amount_effective", "charge_ids.kind",
                 "charge_ids.invoice_line_id", "charge_ids.accrual_line_id", "invoice_ids.state")
    def _compute_invoice_stats(self):
        for job in self:
            revenue = job.charge_ids.filtered(lambda c: c.kind == "revenue" and c.state != "cancelled")
            invoiced = revenue.filtered("invoice_line_id")
            job.amount_invoiced = sum(invoiced.mapped("amount_effective"))
            job.amount_to_invoice = sum((revenue - invoiced).mapped("amount_effective"))
            job.invoice_count = len(job.invoice_ids)
            job.accrual_posted = any(job.charge_ids.mapped("accrual_line_id"))

    # --- akrual ------------------------------------------------------------
    def action_post_accrual(self):
        """Bentuk akrual untuk baris biaya yang sudah dikonfirmasi.

        Idempoten: baris yang sudah punya ``accrual_line_id`` dilewati, sehingga
        menambah baris biaya lalu menekan tombol ini lagi hanya mengakrualkan
        yang baru.
        """
        Move = self.env["account.move"]
        moves = Move.browse()
        for job in self:
            company = job.company_id
            company.lgx_check_accounts()
            pending = job.charge_ids.filtered(
                lambda c: c.kind == "cost" and c.state == "confirmed"
                and not c.accrual_line_id and not c.is_actual_known and c.amount_estimated
            )
            if not pending:
                continue
            lines = []
            total = 0.0
            for charge in pending:
                amount = charge.amount_estimated * (charge.fx_rate_book or 1.0)
                total += amount
                lines.append((0, 0, {
                    "name": _("Akrual %s — %s", charge.charge_code_id.code, job.name),
                    "account_id": charge._lgx_expense_account().id,
                    "partner_id": charge.partner_id.id or False,
                    "debit": amount,
                    "credit": 0.0,
                    "lgx_charge_id": charge.id,
                }))
            lines.append((0, 0, {
                "name": _("Akrual biaya belum ditagih — %s", job.name),
                "account_id": company.lgx_accrual_account_id.id,
                "debit": 0.0,
                "credit": total,
            }))
            move = Move.create({
                "move_type": "entry",
                "journal_id": company.lgx_accrual_journal_id.id,
                "date": fields.Date.context_today(job),
                "ref": _("Akrual biaya job %s", job.name),
                "lgx_job_id": job.id,
                "line_ids": lines,
            })
            move.action_post()
            for charge in pending:
                charge.accrual_line_id = move.line_ids.filtered(lambda l: l.lgx_charge_id == charge)[:1]
            moves |= move
        return moves

    def _lgx_post_variance(self, source_move):
        """Bereskan akrual setelah tagihan vendor diposting.

        Dipanggil dari ``account.move._post``. Selisih antara estimasi dan
        tagihan tidak dibiarkan menggantung di akun akrual: ia dipindahkan ke
        akun varians (untuk jasa) atau kembali ke kliring (untuk talangan),
        supaya saldo akrual selalu berarti "yang benar-benar belum ditagih".
        """
        self.ensure_one()
        if source_move.move_type not in ("in_invoice", "in_refund"):
            return False
        company = self.company_id
        charges = source_move.line_ids.mapped("lgx_charge_id").filtered(
            lambda c: c.accrual_line_id and not c.variance_line_id
        )
        entries = []
        for charge in charges:
            delta = (charge.amount_actual - charge.amount_estimated) * (charge.fx_rate_book or 1.0)
            if company.currency_id.is_zero(delta):
                continue
            counter = (company.lgx_disbursement_account_id if charge.nature == "disbursement"
                       else company.lgx_variance_account_id)
            entries.append((charge, delta, counter))
        if not entries:
            return False
        company.lgx_check_accounts()
        lines = []
        net = 0.0
        for charge, delta, counter in entries:
            net += delta
            lines.append((0, 0, {
                "name": _("Varians %s — %s", charge.charge_code_id.code, self.name),
                "account_id": counter.id,
                "debit": delta if delta > 0 else 0.0,
                "credit": -delta if delta < 0 else 0.0,
                "lgx_charge_id": charge.id,
            }))
        lines.append((0, 0, {
            "name": _("Penyesuaian akrual — %s", self.name),
            "account_id": company.lgx_accrual_account_id.id,
            "debit": -net if net < 0 else 0.0,
            "credit": net if net > 0 else 0.0,
        }))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": company.lgx_accrual_journal_id.id,
            "date": source_move.date,
            "ref": _("Varians biaya job %s (%s)", self.name, source_move.name),
            "lgx_job_id": self.id,
            "line_ids": lines,
        })
        move.action_post()
        for charge, _delta, _counter in entries:
            charge.variance_line_id = move.line_ids.filtered(lambda l: l.lgx_charge_id == charge)[:1]
        return move

    # --- faktur pelanggan --------------------------------------------------
    def action_open_invoice_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Buat Faktur dari Job"),
            "res_model": "lgx.job.invoice.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_job_id": self.id},
        }

    def lgx_create_customer_invoice(self, charges=None):
        """Faktur pelanggan dari baris pendapatan yang sudah dikonfirmasi.

        Baris talangan memakai akun kliring, bukan akun pendapatan, dan tampil
        terpisah di badan faktur. Itu bukan kosmetik: memasukkannya ke pendapatan
        menggelembungkan omzet dan ikut menggelembungkan dasar pemotongan PPh 23
        yang justru seharusnya mengecualikannya.
        """
        self.ensure_one()
        company = self.company_id
        company.lgx_check_accounts()
        charges = charges or self.charge_ids.filtered(
            lambda c: c.kind == "revenue" and c.state == "confirmed" and not c.invoice_line_id
        )
        if not charges:
            raise UserError(_(
                "Tidak ada baris pendapatan yang siap difakturkan pada job %s. "
                "Baris harus berstatus 'Dikonfirmasi' dan belum pernah difakturkan.", self.name,
            ))
        missing_proof = charges.filtered(
            lambda c: c.nature == "disbursement" and not c.third_party_proof_ids
        )
        if missing_proof:
            raise UserError(_(
                "Baris talangan berikut belum punya bukti pihak ketiga dan karena itu "
                "tidak dapat difakturkan:\n\n%s\n\n"
                "Bukti faktur tagihan atau bukti pembayaran dari pihak ketiga adalah dasar "
                "pengecualiannya dari jumlah bruto PPh 23 (PMK 141/2015).",
                "\n".join("• %s — %s" % (c.charge_code_id.code, c.name) for c in missing_proof),
            ))
        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError(_("Perusahaan %s belum punya jurnal penjualan.", company.display_name))
        lines = []
        for charge in charges:
            lines.append((0, 0, {
                "name": "%s — %s" % (charge.charge_code_id.code, charge.name or charge.charge_code_id.name),
                "product_id": charge.charge_code_id.product_id.id,
                "quantity": charge.quantity or 1.0,
                "price_unit": charge.amount_effective / (charge.quantity or 1.0),
                "product_uom_id": charge.uom_id.id or charge.charge_code_id.product_id.uom_id.id,
                "account_id": charge._lgx_revenue_account().id,
                "tax_ids": [(6, 0, charge.tax_ids.ids)],
                "lgx_charge_id": charge.id,
            }))
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.customer_id.id,
            "invoice_date": fields.Date.context_today(self),
            "journal_id": journal.id,
            "currency_id": self.currency_id.id,
            "invoice_origin": self.name,
            "lgx_job_id": self.id,
            "operating_unit_id": self.operating_unit_id.id or False,
            "invoice_line_ids": lines,
        })
        return invoice

    def lgx_create_vendor_bills(self):
        """Satu tagihan per vendor, dari baris biaya yang sudah dikonfirmasi.

        Dikelompokkan per vendor dan bukan per baris, karena satu tagihan vendor
        di dunia nyata memuat beberapa charge sekaligus, dan rekonsiliasinya
        menjadi mustahil kalau sistem memecahnya.
        """
        self.ensure_one()
        company = self.company_id
        company.lgx_check_accounts()
        pending = self.charge_ids.filtered(
            lambda c: c.kind == "cost" and c.state in ("confirmed", "provisioned")
            and not c.bill_line_id and c.partner_id
        )
        if not pending:
            raise UserError(_(
                "Tidak ada baris biaya yang siap ditagihkan pada job %s. Baris harus "
                "sudah dikonfirmasi dan menunjuk vendor.", self.name,
            ))
        journal = self.env["account.journal"].search(
            [("type", "=", "purchase"), ("company_id", "=", company.id)], limit=1)
        if not journal:
            raise UserError(_("Perusahaan %s belum punya jurnal pembelian.", company.display_name))
        bills = self.env["account.move"].browse()
        for partner in pending.mapped("partner_id"):
            partner_charges = pending.filtered(lambda c: c.partner_id == partner)
            lines = []
            for charge in partner_charges:
                amount = charge.amount_actual if charge.is_actual_known else charge.amount_estimated
                lines.append((0, 0, {
                    "name": "%s — %s" % (charge.charge_code_id.code, charge.name or ""),
                    "product_id": charge.charge_code_id.product_id.id,
                    "quantity": charge.quantity or 1.0,
                    "price_unit": amount / (charge.quantity or 1.0),
                    "product_uom_id": charge.uom_id.id or charge.charge_code_id.product_id.uom_id.id,
                    "account_id": charge._lgx_bill_account().id,
                    "tax_ids": [(6, 0, charge.tax_ids.ids)],
                    "lgx_charge_id": charge.id,
                }))
            bills |= self.env["account.move"].create({
                "move_type": "in_invoice",
                "partner_id": partner.id,
                "invoice_date": fields.Date.context_today(self),
                "journal_id": journal.id,
                "currency_id": self.currency_id.id,
                "invoice_origin": self.name,
                "lgx_job_id": self.id,
                "operating_unit_id": self.operating_unit_id.id or False,
                "invoice_line_ids": lines,
            })
        return bills

    def action_create_vendor_bills(self):
        bills = self.lgx_create_vendor_bills()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tagihan Vendor"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", bills.ids)],
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Dokumen Akuntansi Job %s", self.name),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("lgx_job_id", "=", self.id)],
            "context": {"default_lgx_job_id": self.id},
        }

    # --- penutupan finansial -----------------------------------------------
    def action_close_with_provision(self):
        """Tutup finansial: sisa estimasi DIBEKUKAN sebagai provisi, bukan dihapus.

        Inilah alasan status ``closed_provisioned`` ada. Aturan polos "tidak boleh
        tutup selama ada estimasi tanpa aktual" membuat hampir semua job
        menggantung, dan yang terjadi kemudian adalah staf menolkan estimasi
        supaya job bisa ditutup — persis kebocoran yang aturan itu ingin cegah.
        """
        for job in self:
            if job.state not in ("completed",):
                raise UserError(_(
                    "Job %s harus 'Selesai Operasi' lebih dulu. Penutupan finansial "
                    "tidak boleh mendahului selesainya pekerjaan fisik.", job.name,
                ))
            company = job.company_id
            company.lgx_check_accounts()
            remaining = job.charge_ids.filtered(
                lambda c: c.kind == "cost" and c.state == "confirmed"
                and not c.is_actual_known and c.accrual_line_id and c.amount_estimated
            )
            if remaining:
                lines = []
                total = 0.0
                for charge in remaining:
                    amount = charge.amount_estimated * (charge.fx_rate_book or 1.0)
                    total += amount
                    lines.append((0, 0, {
                        "name": _("Provisi %s — %s", charge.charge_code_id.code, job.name),
                        "account_id": company.lgx_provision_account_id.id,
                        "partner_id": charge.partner_id.id or False,
                        "debit": 0.0,
                        "credit": amount,
                        "lgx_charge_id": charge.id,
                    }))
                lines.append((0, 0, {
                    "name": _("Pemindahan akrual ke provisi — %s", job.name),
                    "account_id": company.lgx_accrual_account_id.id,
                    "debit": total,
                    "credit": 0.0,
                }))
                move = self.env["account.move"].create({
                    "move_type": "entry",
                    "journal_id": company.lgx_accrual_journal_id.id,
                    "date": fields.Date.context_today(job),
                    "ref": _("Provisi penutupan job %s", job.name),
                    "lgx_job_id": job.id,
                    "line_ids": lines,
                })
                move.action_post()
                today = fields.Date.context_today(job)
                for charge in remaining:
                    charge.write({
                        "state": "provisioned",
                        "provision_date": today,
                        "provision_line_id": move.line_ids.filtered(
                            lambda l: l.lgx_charge_id == charge)[:1].id,
                    })
            job.write({"state": "closed_provisioned", "closed_date": fields.Date.context_today(job)})
        return True

    def _lgx_close_blockers(self):
        """Tambahkan penghalang finansial yang hanya diketahui modul ini."""
        blockers = super()._lgx_close_blockers()
        self.ensure_one()
        open_provision = self.charge_ids.filtered(lambda c: c.state == "provisioned")
        if open_provision:
            blockers.append(_(
                "%s baris masih berupa provisi yang belum terpakai atau dilepas.",
                len(open_provision),
            ))
        uninvoiced = self.charge_ids.filtered(
            lambda c: c.kind == "revenue" and c.state == "confirmed" and not c.invoice_line_id
        )
        if uninvoiced:
            blockers.append(_(
                "%s baris pendapatan belum difakturkan (%s).",
                len(uninvoiced), self.amount_to_invoice,
            ))
        return blockers

    @api.model
    def _cron_report_aged_provisions(self):
        """Provisi yang melewati umur ambang menjadi aktivitas, bukan hanya baris laporan."""
        days = int(self.env["ir.config_parameter"].sudo().get_param("lgx.provision_age_days", 90))
        cutoff = fields.Date.subtract(fields.Date.context_today(self), days=days)
        aged = self.env["lgx.job.charge"].search([
            ("state", "=", "provisioned"), ("provision_date", "<=", cutoff),
        ])
        for job in aged.mapped("job_id"):
            job.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Provisi lewat %s hari", days),
                note=_(
                    "Job ini memegang provisi yang sudah lebih tua dari %s hari. "
                    "Tagihan vendornya mungkin tidak akan pernah datang. Pelepasan "
                    "provisi membutuhkan persetujuan manajer keuangan.", days,
                ),
                user_id=(job.operator_id or job.salesperson_id or self.env.user).id,
            )
        return len(aged)
