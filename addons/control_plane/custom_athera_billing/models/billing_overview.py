# -*- coding: utf-8 -*-
"""Ringkasan penagihan per tenant — satu view baca-saja untuk hub-portal.

KENAPA VIEW DAN BUKAN GRANT LANGSUNG. hub-portal tersambung sebagai `tenant_orchestrator`, role
hak-minimal yang hanya berhak atas `tenant_registry`. Memberinya SELECT pada `account_move` dan
`athera_subscription` berarti melebarkan role itu ke seluruh basis data Odoo, termasuk tabel yang
tidak ada hubungannya dengan penagihan. Yang diberikan cukup satu view berkolom terpilih — persis
pola `cms.published_*` yang sudah dipakai landing untuk membaca harga.

KENAPA `init()` DAN BUKAN `post_init_hook`. Hook hanya berjalan saat INSTALL. Sebuah view yang
lahir sekali lalu tidak pernah menyusul perubahan kolomnya adalah view yang diam-diam menyajikan
bentuk lama; `init()` dipanggil Odoo pada setiap upgrade modul, jadi definisi di sini selalu yang
berlaku. Ini juga cara Odoo sendiri memelihara view laporannya.
"""

import logging

from odoo import fields, models, tools

_logger = logging.getLogger(__name__)

#: Role yang dipakai hub-portal. Kalau belum ada (instalasi tanpa control plane), grant dilewati
#: dan itu bukan kegagalan — modul tetap berfungsi tanpa portal.
READER_ROLE = "tenant_orchestrator"


class AtheraBillingOverview(models.Model):
    _name = "athera.billing.overview"
    _description = "Ringkasan penagihan per tenant"
    _auto = False
    _order = "tenant_slug"

    tenant_slug = fields.Char(readonly=True)
    display_name = fields.Char(readonly=True)
    plan_code = fields.Char(readonly=True)
    subscription_state = fields.Char(readonly=True)
    tenant_state = fields.Char(readonly=True)
    valid_until = fields.Datetime(readonly=True)
    next_invoice_date = fields.Date(readonly=True)
    price_month = fields.Float(readonly=True)
    currency = fields.Char(readonly=True)
    invoice_count = fields.Integer(readonly=True)
    open_invoice_count = fields.Integer(readonly=True)
    outstanding = fields.Float(readonly=True)
    last_invoice_date = fields.Date(readonly=True)
    oldest_due_date = fields.Date(readonly=True)

    def init(self):
        # Skema terpisah, bukan `public`: grant di sini tidak boleh menyeret apa pun milik Odoo.
        self.env.cr.execute("CREATE SCHEMA IF NOT EXISTS billing")
        # Odoo mencari view model di `public`, hub-portal membacanya di `billing`. Keduanya
        # definisi yang sama, ditulis sekali.
        body = """
            SELECT
                s.id                                      AS id,
                s.tenant_slug,
                t.display_name,
                s.plan_code,
                s.state                                   AS subscription_state,
                t.state                                   AS tenant_state,
                t.valid_until,
                s.next_invoice_date,
                p.price_month,
                p.currency,
                COUNT(m.id) FILTER (WHERE m.state = 'posted')                      AS invoice_count,
                COUNT(m.id) FILTER (WHERE m.state = 'posted'
                    AND m.payment_state NOT IN ('paid', 'in_payment', 'reversed')) AS open_invoice_count,
                COALESCE(SUM(m.amount_residual) FILTER (WHERE m.state = 'posted'
                    AND m.payment_state NOT IN ('paid', 'in_payment', 'reversed')), 0) AS outstanding,
                MAX(m.invoice_date) FILTER (WHERE m.state = 'posted')              AS last_invoice_date,
                MIN(m.invoice_date_due) FILTER (WHERE m.state = 'posted'
                    AND m.payment_state NOT IN ('paid', 'in_payment', 'reversed')) AS oldest_due_date
            FROM athera_subscription s
            LEFT JOIN tenant_registry.tenants t ON t.slug = s.tenant_slug
            LEFT JOIN tenant_registry.plans   p ON p.code = s.plan_code
            LEFT JOIN account_move m
                   ON m.athera_subscription_id = s.id
                  AND m.move_type = 'out_invoice'
            GROUP BY s.id, s.tenant_slug, t.display_name, s.plan_code, s.state, t.state,
                     t.valid_until, s.next_invoice_date, p.price_month, p.currency
        """
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, body))
        self.env.cr.execute("CREATE OR REPLACE VIEW billing.subscription_overview AS (%s)" % body)

        self.env.cr.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER_ROLE,))
        if not self.env.cr.fetchone():
            _logger.warning(
                "role %s tidak ada; billing.subscription_overview dibuat tanpa grant", READER_ROLE
            )
            return
        # Nama role tidak bisa di-parameterkan di GRANT, jadi ia konstanta modul dan bukan masukan.
        self.env.cr.execute("GRANT USAGE ON SCHEMA billing TO %s" % READER_ROLE)
        self.env.cr.execute("GRANT SELECT ON billing.subscription_overview TO %s" % READER_ROLE)
        _logger.info("billing.subscription_overview siap; SELECT diberikan ke %s", READER_ROLE)
