# -*- coding: utf-8 -*-
"""Kaitan faktur ke langganan, plus dua penanda yang membuat cron idempoten."""

from odoo import fields, models


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
