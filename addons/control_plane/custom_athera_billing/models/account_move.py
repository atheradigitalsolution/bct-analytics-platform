# -*- coding: utf-8 -*-
"""Kaitan faktur ke langganan, plus dua penanda yang membuat cron idempoten."""

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

#: Basis URL portal klien (ATHERA Insight). Sengaja sebuah parameter, bukan konstanta —
#: lihat `_compute_athera_portal_url`.
PORTAL_URL_PARAM = "athera_billing.portal_url"


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

    athera_portal_url = fields.Char(
        string="URL portal tagihan klien", compute="_compute_athera_portal_url",
        help="Alamat halaman tagihan klien di ATHERA Insight, dirakit dari parameter "
             "`athera_billing.portal_url`. Kosong kalau parameter itu belum diisi, dan surat "
             "penagihan menghilangkan tautannya alih-alih mengirim alamat yang salah.",
    )

    #: TANPA @api.depends, dan itu disengaja. Nilainya tidak berasal dari field mana pun; ia
    #: berasal dari sebuah parameter konfigurasi. Mendaftarkan dependensi palsu ke `company_id`
    #: hanya akan berbohong kepada mesin invalidasi. Pola yang sama dipakai `portal.mixin`
    #: bawaan Odoo untuk `access_url`. Field ini tidak disimpan, jadi ia dihitung saat dibaca.
    def _compute_athera_portal_url(self):
        """Alamat portal tagihan — DARI KONFIGURASI, tidak pernah dari konstanta.

        Sebuah hostname produksi yang ditanam di berkas repo akan tetap bekerja setelah
        parameter yang seharusnya mengendalikannya dikosongkan, sehingga tidak ada yang pernah
        menemukan bahwa konfigurasinya salah. Alasan yang sama sudah dipakai `email_from` di
        `data/mail_template.xml`. Repo publik menambahkan satu alasan lagi: hostname pelanggan
        bukan bagian dari produk.

        Kosong menghasilkan False, dan surat memakai `t-if` sehingga yang dikirim adalah surat
        tanpa tautan, bukan surat berisi tautan ke tempat yang tidak ada.
        """
        base = (
            self.env["ir.config_parameter"].sudo().get_param(PORTAL_URL_PARAM) or ""
        ).strip().rstrip("/")
        for move in self:
            move.athera_portal_url = (base + "/billing") if base else False

    @api.depends("invoice_date_due", "athera_subscription_id.grace_days")
    def _compute_athera_suspend_on(self):
        for move in self:
            sub = move.athera_subscription_id
            if sub and move.invoice_date_due:
                move.athera_suspend_on = move.invoice_date_due + relativedelta(days=sub.grace_days)
            else:
                move.athera_suspend_on = False
