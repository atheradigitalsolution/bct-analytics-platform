# -*- coding: utf-8 -*-
"""Langganan ATHERA — dan seam antara tagihan dan hak akses.

KENAPA MODUL INI ADA DI `athera_admin` DAN BUKAN DI LAYANAN TERSENDIRI. Schema
`tenant_registry` hidup di database yang sama dengan konsol ini. Artinya perubahan hak akses
dan baris auditnya bisa ditulis dalam SATU transaksi dengan perubahan fakturnya. Sebuah layanan
terpisah harus memanggil API, dan panggilan itu bisa gagal setelah faktur tercatat lunas —
menghasilkan klien yang sudah membayar tetapi aksesnya tetap tertutup, tepat pada kelas kesalahan
yang paling mahal untuk ditemukan.

ARAH ALIRANNYA SATU. Faktur adalah fakta; hak akses adalah akibatnya. Modul ini tidak pernah
membaca hak akses untuk memutuskan tagihan.

RANTAI HASH TIDAK DIHITUNG DI SINI. `tenant_registry.action_log` punya trigger BEFORE INSERT
(`_compute_action_hash`) dan trigger yang memblokir UPDATE/DELETE/TRUNCATE. Jadi kode ini hanya
melakukan INSERT; menghitung sendiri `prev_hash` berarti dua implementasi rantai yang sama, dan
yang satu pasti akan menyimpang.
"""

from __future__ import annotations

import json
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: Masa tenggang bawaan, dalam hari, sejak jatuh tempo sampai akses ditutup.
#: Keputusan user 2026-09-03: 14 hari, dan harus bisa diatur — jadi ia parameter, bukan konstanta.
DEFAULT_GRACE_DAYS = 14
GRACE_PARAM = "athera_billing.grace_days"

#: Tempo pembayaran: berapa hari sejak faktur terbit sampai jatuh tempo. Tanpa ini Odoo memakai
#: tanggal faktur itu sendiri, sehingga setiap faktur lahir dalam keadaan jatuh tempo dan masa
#: tenggang menjadi satu-satunya tempo yang benar-benar diberikan kepada klien.
DEFAULT_DUE_DAYS = 14
DUE_PARAM = "athera_billing.due_days"


class AtheraSubscription(models.Model):
    _name = "athera.subscription"
    _description = "Langganan ATHERA"
    _inherit = ["mail.thread"]
    _order = "next_invoice_date, id"
    _rec_name = "tenant_slug"

    tenant_slug = fields.Char(
        required=True, index=True, tracking=True,
        help="Slug tenant di tenant_registry.tenants. Inilah identitas yang dipakai gerbang login.",
    )
    partner_id = fields.Many2one(
        "res.partner", string="Pelanggan", required=True, tracking=True,
        help="Entitas yang ditagih. Boleh berbeda dari nama tenant.",
    )
    plan_code = fields.Char(required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True,
    )
    date_start = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    next_invoice_date = fields.Date(required=True, tracking=True)
    #: Kosong berarti pakai parameter global. Diisi berarti kesepakatan khusus dengan klien ini.
    grace_days_override = fields.Integer(
        string="Masa tenggang (hari)", default=0,
        help="0 = ikuti parameter sistem athera_billing.grace_days.",
    )
    grace_days = fields.Integer(compute="_compute_grace_days")
    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("active", "Aktif"),
            ("suspended", "Ditangguhkan"),
            ("cancelled", "Dibatalkan"),
        ],
        default="draft", required=True, tracking=True,
    )
    invoice_ids = fields.One2many("account.move", "athera_subscription_id", string="Faktur")
    invoice_count = fields.Integer(compute="_compute_invoice_count")
    #: Harga TIDAK disimpan di sini. Ia dibaca dari tenant_registry.plans saat faktur dibuat,
    #: karena registry adalah satu-satunya sumber kebenaran harga (editor: hub-portal /pricing).
    price_month = fields.Monetary(
        compute="_compute_plan", currency_field="currency_id", string="Harga/bulan",
    )
    products = fields.Char(compute="_compute_plan", string="Produk paket")

    _sql_constraints = [
        ("tenant_slug_uniq", "unique(tenant_slug)",
         "Satu tenant hanya boleh punya satu langganan."),
    ]

    # ------------------------------------------------------------------ compute

    @api.depends("grace_days_override")
    def _compute_grace_days(self):
        param = self.env["ir.config_parameter"].sudo().get_param(GRACE_PARAM)
        try:
            default = int(param) if param else DEFAULT_GRACE_DAYS
        except (TypeError, ValueError):
            _logger.warning("%s bukan bilangan bulat (%r); memakai %s", GRACE_PARAM, param,
                            DEFAULT_GRACE_DAYS)
            default = DEFAULT_GRACE_DAYS
        for sub in self:
            sub.grace_days = sub.grace_days_override or default

    @api.depends("invoice_ids")
    def _compute_invoice_count(self):
        for sub in self:
            sub.invoice_count = len(sub.invoice_ids)

    @api.depends("plan_code")
    def _compute_plan(self):
        for sub in self:
            plan = sub._registry_plan(sub.plan_code) if sub.plan_code else None
            sub.price_month = (plan or {}).get("price_month") or 0.0
            sub.products = ",".join((plan or {}).get("products") or [])

    # ------------------------------------------------------- tenant_registry I/O

    def _registry_plan(self, plan_code):
        """Harga dan produk paket, dari registry. None kalau paketnya tidak ada atau non-aktif."""
        self.env.cr.execute(
            "SELECT price_month, currency, products FROM tenant_registry.plans "
            "WHERE code = %s AND is_active",
            (plan_code,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return None
        return {"price_month": row[0], "currency": row[1], "products": list(row[2] or [])}

    def _registry_log(self, action, detail, outcome="success", error=None):
        """Satu baris audit, dalam transaksi yang sama dengan perubahan yang dicatatnya.

        `actor` sengaja menyebut pengguna Odoo DAN modulnya: baris yang hanya berbunyi
        "athera-billing" tidak bisa membedakan cron dari orang yang menekan tombol.
        """
        self.ensure_one()
        self.env.cr.execute(
            "INSERT INTO tenant_registry.action_log "
            "  (tenant_slug, action, actor, outcome, error, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
            (
                self.tenant_slug,
                action,
                "custom_athera_billing:%s" % (self.env.user.login or "system"),
                outcome,
                error,
                json.dumps(detail, default=str),
            ),
        )

    def _registry_tenant(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state, valid_until FROM tenant_registry.tenants WHERE slug = %s",
            (self.tenant_slug,),
        )
        return self.env.cr.fetchone()

    def _grant_access_until(self, until_date, invoice):
        """Perpanjang hak akses sampai `until_date`, dan bangunkan tenant yang tertangguh.

        `GREATEST` bukan hiasan: membayar faktur lama tidak boleh MEMENDEKKAN masa akses yang
        sudah lebih panjang karena faktur berikutnya sudah dibayar lebih dulu.
        """
        self.ensure_one()
        row = self._registry_tenant()
        if not row:
            raise UserError(_("Tenant '%s' tidak ada di tenant_registry.tenants.") % self.tenant_slug)
        state_before, valid_before = row
        self.env.cr.execute(
            "UPDATE tenant_registry.tenants "
            "   SET valid_until = GREATEST(COALESCE(valid_until, %s::timestamptz), %s::timestamptz), "
            "       state = CASE WHEN state = 'suspended' THEN 'active' ELSE state END, "
            "       suspended_at = CASE WHEN state = 'suspended' THEN NULL ELSE suspended_at END "
            " WHERE slug = %s "
            "RETURNING state, valid_until",
            (until_date, until_date, self.tenant_slug),
        )
        state_after, valid_after = self.env.cr.fetchone()
        self._registry_log(
            "billing_payment_applied",
            {
                "invoice": invoice.name,
                "amount": invoice.amount_total,
                "currency": invoice.currency_id.name,
                "valid_until_before": valid_before,
                "valid_until_after": valid_after,
                "state_before": state_before,
                "state_after": state_after,
                "via": "custom_athera_billing",
            },
        )
        return state_after, valid_after

    def _suspend_for_arrears(self, invoice):
        self.ensure_one()
        row = self._registry_tenant()
        if not row:
            return False
        state_before, _valid = row
        if state_before != "active":
            return False
        self.env.cr.execute(
            "UPDATE tenant_registry.tenants "
            "   SET state = 'suspended', suspended_at = now() "
            " WHERE slug = %s AND state = 'active'",
            (self.tenant_slug,),
        )
        self._registry_log(
            "billing_suspended_arrears",
            {
                "invoice": invoice.name,
                "due_date": invoice.invoice_date_due,
                "grace_days": self.grace_days,
                "amount_residual": invoice.amount_residual,
                "via": "custom_athera_billing",
            },
        )
        return True

    # ------------------------------------------------------------------ faktur

    def _plan_product(self):
        """Produk jasa untuk paket ini, dibuat sekali saat pertama dibutuhkan.

        Harganya TIDAK dipakai saat menagih — `price_unit` selalu diambil dari registry di
        `_create_invoice`. Ia disimpan hanya agar produk terlihat wajar di daftar produk.
        """
        self.ensure_one()
        code = "ATHERA-%s" % (self.plan_code or "").upper()
        product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
        plan = self._registry_plan(self.plan_code) or {}
        if not product:
            product = self.env["product.product"].create(
                {
                    "name": "Langganan ATHERA (%s)" % self.plan_code,
                    "default_code": code,
                    "type": "service",
                    "list_price": plan.get("price_month") or 0.0,
                    "taxes_id": [(6, 0, self.env.company.account_sale_tax_id.ids)],
                    "property_account_income_id": self._income_account().id,
                }
            )
        return product

    def _due_days(self):
        param = self.env["ir.config_parameter"].sudo().get_param(DUE_PARAM)
        try:
            return int(param) if param else DEFAULT_DUE_DAYS
        except (TypeError, ValueError):
            _logger.warning("%s bukan bilangan bulat (%r); memakai %s", DUE_PARAM, param,
                            DEFAULT_DUE_DAYS)
            return DEFAULT_DUE_DAYS

    def _income_account(self):
        """Akun pendapatan untuk langganan: PSAK 42000 "Pendapatan Jasa".

        Disetel EKSPLISIT di produk, bukan lewat default kategori produk. Chart PSAK tidak mengisi
        `property_account_income_categ_id`, sehingga baris faktur lahir tanpa akun dan Postgres
        menolaknya dengan `account_move_line_check_accountable_required_fields` — sebuah pelanggaran
        constraint yang sama sekali tidak menyebut "akun pendapatan hilang". Mengisi default global
        perusahaan akan memperbaikinya juga, tetapi itu keputusan akuntansi milik operator; modul
        billing hanya berhak menentukan akun untuk produknya sendiri.
        """
        account = self.env["account.account"].search(
            [("code", "=", "42000"), ("company_ids", "in", self.env.company.id)], limit=1
        )
        if not account:
            account = self.env["account.account"].search(
                [("account_type", "=", "income"), ("company_ids", "in", self.env.company.id)],
                limit=1,
            )
        if not account:
            raise UserError(
                _("Tidak ada akun pendapatan di chart perusahaan ini. Muat chart of accounts dulu.")
            )
        return account

    def _create_invoice(self):
        """Satu faktur untuk satu periode bulanan. Mengembalikan account.move yang sudah diposting."""
        self.ensure_one()
        plan = self._registry_plan(self.plan_code)
        if plan is None:
            raise UserError(
                _("Paket '%s' tidak ada atau non-aktif di tenant_registry.plans.") % self.plan_code
            )
        if plan["price_month"] is None:
            # Paket "Hubungi kami" (harga custom). Menagih nol diam-diam jauh lebih buruk
            # daripada menolak: yang pertama terlihat seperti klien yang sudah membayar.
            raise UserError(
                _("Paket '%s' berharga custom (NULL). Terbitkan faktur manual, bukan lewat cron.")
                % self.plan_code
            )
        period_start = self.next_invoice_date
        period_end = period_start + relativedelta(months=1) - relativedelta(days=1)
        due_date = period_start + relativedelta(days=self._due_days())
        product = self._plan_product()
        invoice = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": self.partner_id.id,
                "invoice_date": period_start,
                "invoice_date_due": due_date,
                "currency_id": self.currency_id.id,
                "athera_subscription_id": self.id,
                "athera_period_start": period_start,
                "athera_period_end": period_end,
                "invoice_line_ids": [
                    (0, 0, {
                        "product_id": product.id,
                        "name": "Langganan ATHERA %s — %s s.d. %s (tenant %s)" % (
                            self.plan_code, period_start, period_end, self.tenant_slug,
                        ),
                        "quantity": 1.0,
                        "price_unit": float(plan["price_month"]),
                    })
                ],
            }
        )
        invoice.action_post()
        self.next_invoice_date = period_start + relativedelta(months=1)
        self._registry_log(
            "billing_invoice_issued",
            {
                "invoice": invoice.name,
                "plan": self.plan_code,
                "period_start": period_start,
                "period_end": period_end,
                "amount_total": invoice.amount_total,
                "currency": invoice.currency_id.name,
                "via": "custom_athera_billing",
            },
        )
        return invoice

    # ------------------------------------------------------------------ aksi UI

    def action_activate(self):
        for sub in self:
            if not sub._registry_tenant():
                raise UserError(
                    _("Tenant '%s' tidak ada di tenant_registry.tenants.") % sub.tenant_slug
                )
            sub.state = "active"
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return True

    def action_create_invoice_now(self):
        """Terbitkan faktur periode berikutnya sekarang. Dipakai operator, bukan cron."""
        moves = self.env["account.move"]
        for sub in self.filtered(lambda s: s.state == "active"):
            moves |= sub._create_invoice()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "name": _("Faktur baru"),
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("athera_subscription_id", "=", self.id)],
            "name": _("Faktur %s") % self.tenant_slug,
        }

    # -------------------------------------------------------------------- cron

    @api.model
    def _cron_generate_invoices(self):
        today = fields.Date.context_today(self)
        due = self.search([("state", "=", "active"), ("next_invoice_date", "<=", today)])
        for sub in due:
            try:
                with self.env.cr.savepoint():
                    invoice = sub._create_invoice()
                _logger.info("billing: faktur %s untuk tenant %s", invoice.name, sub.tenant_slug)
            except Exception as exc:  # noqa: BLE001 - satu tenant gagal tidak boleh menghentikan sisanya
                _logger.exception("billing: gagal menerbitkan faktur untuk %s", sub.tenant_slug)
                with self.env.cr.savepoint():
                    sub._registry_log(
                        "billing_invoice_failed", {"plan": sub.plan_code},
                        outcome="failure", error=str(exc)[:500],
                    )

    @api.model
    def _cron_apply_payments(self):
        """Faktur lunas -> hak akses diperpanjang. Idempoten lewat penanda di faktur.

        Dipisahkan dari `write()` pada account.move dengan sengaja: pembayaran bisa mendarat lewat
        rekonsiliasi bank, wizard, atau impor, dan menempelkan efek samping pada satu jalur berarti
        dua jalur lain diam-diam tidak memperpanjang apa pun.
        """
        paid = self.env["account.move"].search(
            [
                ("athera_subscription_id", "!=", False),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "in", ("paid", "in_payment")),
                ("athera_access_applied", "=", False),
            ]
        )
        for invoice in paid:
            sub = invoice.athera_subscription_id
            try:
                with self.env.cr.savepoint():
                    state_after, valid_after = sub._grant_access_until(
                        invoice.athera_period_end, invoice
                    )
                    invoice.athera_access_applied = True
                    if sub.state == "suspended":
                        sub.state = "active"
                _logger.info(
                    "billing: %s lunas -> tenant %s state=%s valid_until=%s",
                    invoice.name, sub.tenant_slug, state_after, valid_after,
                )
            except Exception:  # noqa: BLE001
                _logger.exception("billing: gagal menerapkan pembayaran %s", invoice.name)

    @api.model
    def _cron_enforce_arrears(self):
        """Nunggak melewati masa tenggang -> tenant ditangguhkan."""
        today = fields.Date.context_today(self)
        candidates = self.env["account.move"].search(
            [
                ("athera_subscription_id", "!=", False),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("payment_state", "not in", ("paid", "in_payment", "reversed")),
                ("invoice_date_due", "!=", False),
                ("athera_arrears_enforced", "=", False),
            ]
        )
        for invoice in candidates:
            sub = invoice.athera_subscription_id
            deadline = invoice.invoice_date_due + relativedelta(days=sub.grace_days)
            if today <= deadline:
                continue
            try:
                with self.env.cr.savepoint():
                    suspended = sub._suspend_for_arrears(invoice)
                    invoice.athera_arrears_enforced = True
                    if suspended:
                        sub.state = "suspended"
                _logger.info(
                    "billing: %s nunggak > %s hari -> tenant %s ditangguhkan=%s",
                    invoice.name, sub.grace_days, sub.tenant_slug, suspended,
                )
            except Exception:  # noqa: BLE001
                _logger.exception("billing: gagal menangguhkan untuk %s", invoice.name)
