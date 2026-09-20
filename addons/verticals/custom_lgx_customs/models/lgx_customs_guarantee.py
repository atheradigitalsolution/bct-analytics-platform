# -*- coding: utf-8 -*-
"""Jaminan kepabeanan — TRANSAKSIONAL, bukan atribut master PPJK.

Customs bond bukan syarat izin PPJK. Ia melekat per transaksi atau per fasilitas:
impor sementara, BC 2.6.1, keberatan. Memodelkannya sebagai field pada master
akan membuat jaminan yang sudah dapat ditarik tidak pernah ditarik — tidak ada
record yang jatuh tempo, jadi tidak ada yang muncul di laporan mana pun.

⚠ VERIFIKASI: bentuk-bentuk jaminan di bawah berasal dari ringkasan PMK
168/PMK.04/2022 dan belum dibaca dari fulltext (Lampiran A butir A7).
"""
from odoo import _, api, fields, models


class LgxCustomsGuarantee(models.Model):
    _name = "lgx.customs.guarantee"
    _description = "Jaminan Kepabeanan"
    _order = "valid_until, id"
    _inherit = ["lgx.numbering.mixin", "mail.thread"]
    _lgx_sequence_code = "lgx.customs.guarantee"

    declaration_ids = fields.One2many("lgx.customs.declaration", "guarantee_id", "Deklarasi")
    guarantee_type = fields.Selection(
        [("cash", "Tunai"), ("bank", "Bank Garansi"), ("bond", "Customs Bond"),
         ("corporate", "Jaminan Perusahaan"), ("other", "Lainnya")],
        string="Bentuk", required=True, default="bank",
    )
    purpose = fields.Selection(
        [("temporary_import", "Impor Sementara"), ("bc261", "BC 2.6.1"),
         ("objection", "Keberatan"), ("facility", "Fasilitas"), ("other", "Lainnya")],
        string="Peruntukan", default="facility", required=True,
    )
    amount = fields.Monetary("Nilai", required=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    issuer_id = fields.Many2one("res.partner", "Penerbit")
    reference = fields.Char("Nomor Jaminan Penerbit")
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_until = fields.Date("Berlaku Sampai", required=True)
    released_date = fields.Date("Tanggal Ditarik", copy=False)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    state = fields.Selection(
        [("draft", "Draf"), ("active", "Berlaku"), ("releasable", "Dapat Ditarik"),
         ("released", "Sudah Ditarik"), ("expired", "Kedaluwarsa")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Text("Catatan")

    _period_valid = models.Constraint(
        "check(valid_until >= valid_from)",
        "Masa berlaku jaminan tidak boleh berakhir sebelum dimulai.",
    )
    _amount_positive = models.Constraint(
        "check(amount > 0)", "Nilai jaminan harus lebih besar dari nol.",
    )

    def action_activate(self):
        self.write({"state": "active"})
        return True

    def action_mark_releasable(self):
        self.write({"state": "releasable"})
        return True

    def action_release(self):
        self.write({"state": "released", "released_date": fields.Date.context_today(self)})
        return True

    @api.model
    def _cron_flag_guarantees(self):
        """Tandai yang kedaluwarsa, dan ingatkan yang sudah dapat ditarik.

        Jaminan yang sudah dapat ditarik tetapi belum ditarik adalah kas
        perusahaan yang menganggur di pihak lain. Ia laporan tersendiri justru
        karena tidak ada yang mengeluh kalau dilupakan.
        """
        today = fields.Date.context_today(self)
        expired = self.search([("state", "in", ("active", "releasable")), ("valid_until", "<", today)])
        expired.write({"state": "expired"})
        releasable = self.search([("state", "=", "releasable")])
        for guarantee in releasable:
            guarantee.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Jaminan %s sudah dapat ditarik", guarantee.name),
                note=_("Nilai %s. Jaminan yang dapat ditarik tetapi belum ditarik adalah "
                       "kas yang menganggur di pihak lain.", guarantee.amount),
                user_id=self.env.user.id,
            )
        return len(expired) + len(releasable)
