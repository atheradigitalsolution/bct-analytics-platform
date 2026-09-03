# -*- coding: utf-8 -*-
"""Kaitan faktur ke langganan, plus dua penanda yang membuat cron idempoten."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    athera_subscription_id = fields.Many2one(
        "athera.subscription", string="Langganan ATHERA", index=True, copy=False, readonly=True,
    )
    athera_period_start = fields.Date(string="Periode mulai", copy=False, readonly=True)
    athera_period_end = fields.Date(string="Periode selesai", copy=False, readonly=True)
    #: Sudah pernah memperpanjang hak akses. Penandanya ada DI FAKTUR, bukan di langganan, supaya
    #: satu langganan dengan banyak faktur tidak bisa menerapkan pembayaran yang sama dua kali.
    athera_access_applied = fields.Boolean(
        string="Akses sudah diperpanjang", default=False, copy=False, readonly=True,
    )
    #: Sudah pernah memicu penangguhan. Tanpa ini cron menangguhkan ulang setiap jam dan
    #: action_log terisi baris yang sama tanpa henti — audit yang berisik adalah audit yang diabaikan.
    athera_arrears_enforced = fields.Boolean(
        string="Penangguhan sudah dijalankan", default=False, copy=False, readonly=True,
    )

    #: Sampai di mana tangga penagihan sudah dinaiki. Tersimpan DI FAKTUR supaya satu langganan
    #: dengan banyak faktur tidak saling menghapus tahap yang lain.
    athera_dunning_stage = fields.Selection(
        [
            ("none", "Belum ada"),
            ("reminder", "Pengingat terkirim"),
            ("final", "Peringatan akhir terkirim"),
            ("suspended", "Pemberitahuan penangguhan terkirim"),
        ],
        string="Tahap penagihan", default="none", copy=False, readonly=True,
    )
    athera_suspend_on = fields.Date(
        string="Akses ditutup pada", compute="_compute_athera_suspend_on",
        help="Jatuh tempo ditambah masa tenggang. Tanggal inilah yang disebut di surat penagihan — "
             "klien yang tahu tanggalnya bisa bertindak.",
    )

    @api.depends("invoice_date_due", "athera_subscription_id.grace_days")
    def _compute_athera_suspend_on(self):
        for move in self:
            sub = move.athera_subscription_id
            if sub and move.invoice_date_due:
                move.athera_suspend_on = move.invoice_date_due + relativedelta(days=sub.grace_days)
            else:
                move.athera_suspend_on = False
