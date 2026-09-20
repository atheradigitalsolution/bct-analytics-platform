# -*- coding: utf-8 -*-
"""Uang jalan: tiga kontrol yang menutup kebocoran terbesar di trucking.

1. **Batas dari master rute.** Nilai yang disarankan berasal dari
   ``lgx.route.tariff.standard_advance``. Nilai di atasnya membutuhkan
   persetujuan DENGAN ALASAN TERCATAT — persetujuan tanpa alasan tidak dapat
   ditinjau kemudian, dan itu yang membuat batas berhenti berarti.
2. **Satu uang jalan terbuka per pengemudi.** Dapat dikonfigurasi, tetapi
   defaultnya menyala: pengemudi yang menumpuk beberapa uang muka terbuka adalah
   pola yang membuat pertanggungjawaban tidak pernah dapat direkonsiliasi.
3. **Trip tidak bisa ditutup sebelum pertanggungjawaban selesai.** Selisihnya
   otomatis menjadi piutang atau utang pengemudi — bukan dibulatkan hilang.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LgxTripAdvance(models.Model):
    _name = "lgx.trip.advance"
    _description = "Uang Jalan"
    _order = "create_date desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread"]
    _lgx_sequence_code = "lgx.trip.advance"

    trip_id = fields.Many2one("lgx.trip", "Trip", required=True, ondelete="cascade", index=True)
    driver_id = fields.Many2one("lgx.driver", "Pengemudi", required=True, index=True, tracking=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)

    amount_limit = fields.Monetary(
        "Batas dari Master Rute", currency_field="currency_id", readonly=True,
        help="Berasal dari lgx.route.tariff.standard_advance. Nol berarti rute "
             "atau tarifnya belum ada — dan itu yang harus diperbaiki, bukan "
             "dilewati dengan mengetik angka bebas.",
    )
    amount_requested = fields.Monetary("Diminta", currency_field="currency_id", tracking=True)
    amount_approved = fields.Monetary("Disetujui", currency_field="currency_id", tracking=True)
    amount_paid = fields.Monetary("Dibayarkan", currency_field="currency_id", tracking=True)
    paid_date = fields.Date("Tanggal Bayar")
    payment_method = fields.Selection(
        [("cash", "Tunai"), ("transfer", "Transfer"), ("card", "Kartu / E-money")],
        string="Cara Bayar", default="transfer",
    )

    expense_ids = fields.One2many("lgx.trip.expense", "advance_id", "Biaya")
    expense_total = fields.Monetary("Total Biaya", compute="_compute_balance", store=True,
                                    currency_field="currency_id")
    balance = fields.Monetary(
        "Saldo", compute="_compute_balance", store=True, currency_field="currency_id",
        help="Dibayarkan dikurangi biaya. Positif = kembalian dari pengemudi; "
             "negatif = penggantian kepada pengemudi.",
    )
    balance_direction = fields.Selection(
        [("return", "Kembalian dari Pengemudi"), ("reimburse", "Penggantian ke Pengemudi"),
         ("balanced", "Pas")],
        string="Arah Saldo", compute="_compute_balance", store=True,
    )
    settlement_date = fields.Date("Tanggal Pertanggungjawaban")
    approval_user_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True)
    approval_reason = fields.Char("Alasan Melebihi Batas")

    state = fields.Selection(
        [("draft", "Draf"), ("approved", "Disetujui"), ("paid", "Dibayarkan"),
         ("settled", "Dipertanggungjawabkan"), ("cancelled", "Batal")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Char("Catatan")

    _amounts_non_negative = models.Constraint(
        "check(amount_requested >= 0 and amount_approved >= 0 and amount_paid >= 0)",
        "Nilai uang jalan tidak boleh negatif.",
    )

    @api.depends("amount_paid", "expense_ids.amount")
    def _compute_balance(self):
        for advance in self:
            advance.expense_total = sum(advance.expense_ids.mapped("amount"))
            advance.balance = (advance.amount_paid or 0.0) - advance.expense_total
            if advance.currency_id.is_zero(advance.balance):
                advance.balance_direction = "balanced"
            elif advance.balance > 0:
                advance.balance_direction = "return"
            else:
                advance.balance_direction = "reimburse"

    @api.constrains("driver_id", "state")
    def _check_single_open_advance(self):
        """Satu pengemudi, satu uang jalan terbuka. Dapat dimatikan lewat parameter."""
        enabled = self.env["ir.config_parameter"].sudo().get_param(
            "lgx.driver_single_open_advance", "1") == "1"
        if not enabled:
            return
        for advance in self:
            if advance.state not in ("approved", "paid"):
                continue
            others = self.search([
                ("id", "!=", advance.id),
                ("driver_id", "=", advance.driver_id.id),
                ("state", "in", ("approved", "paid")),
            ])
            if others:
                raise ValidationError(_(
                    "Pengemudi %s masih punya uang jalan terbuka: %s. Satu pengemudi "
                    "hanya boleh memegang satu uang jalan terbuka; aturan ini dapat "
                    "dimatikan lewat parameter 'lgx.driver_single_open_advance' bila "
                    "memang dikehendaki.",
                    advance.driver_id.name, ", ".join(others.mapped("name")),
                ))

    def action_approve(self):
        for advance in self:
            if advance.state != "draft":
                raise UserError(_("Hanya uang jalan draf yang dapat disetujui."))
            amount = advance.amount_approved or advance.amount_requested
            tolerance = float(self.env["ir.config_parameter"].sudo().get_param(
                "lgx.advance_tolerance_pct", 10.0))
            ceiling = (advance.amount_limit or 0.0) * (1.0 + tolerance / 100.0)
            if advance.amount_limit and amount > ceiling and not advance.approval_reason:
                raise UserError(_(
                    "Nilai %(amount)s melebihi batas master rute %(limit)s (toleransi %(tol)s%%). "
                    "Isi 'Alasan Melebihi Batas' lebih dulu — persetujuan tanpa alasan "
                    "tercatat tidak dapat ditinjau kemudian.",
                    amount=amount, limit=advance.amount_limit, tol=tolerance,
                ))
            advance.write({
                "amount_approved": amount,
                "approval_user_id": self.env.user.id,
                "state": "approved",
            })
        return True

    def action_pay(self):
        for advance in self:
            if advance.state != "approved":
                raise UserError(_("Uang jalan %s belum disetujui.", advance.name))
            advance.write({
                "amount_paid": advance.amount_paid or advance.amount_approved,
                "paid_date": advance.paid_date or fields.Date.context_today(advance),
                "state": "paid",
            })
            if advance.trip_id.job_id:
                advance.trip_id.job_id.lgx_log_milestone("advance_paid", source="manual")
        return True

    def action_settle(self):
        """Tutup pertanggungjawaban. Selisihnya menjadi piutang atau utang pengemudi."""
        for advance in self:
            if advance.state != "paid":
                raise UserError(_("Uang jalan %s belum dibayarkan.", advance.name))
            if not advance.expense_ids:
                raise UserError(_(
                    "Uang jalan %s belum punya satu pun rincian biaya. Pertanggungjawaban "
                    "tanpa rincian adalah uang yang hilang tanpa jejak.", advance.name,
                ))
            advance.write({
                "state": "settled",
                "settlement_date": fields.Date.context_today(advance),
            })
            direction = dict(advance._fields["balance_direction"].selection).get(
                advance.balance_direction)
            advance.message_post(body=_(
                "Pertanggungjawaban ditutup. Dibayarkan %(paid)s, biaya %(spent)s, "
                "saldo %(balance)s (%(direction)s).",
                paid=advance.amount_paid, spent=advance.expense_total,
                balance=abs(advance.balance), direction=direction,
            ))
        return True

    def action_cancel(self):
        for advance in self:
            if advance.state == "settled":
                raise UserError(_("Uang jalan yang sudah dipertanggungjawabkan tidak dapat dibatalkan."))
            advance.state = "cancelled"
        return True
