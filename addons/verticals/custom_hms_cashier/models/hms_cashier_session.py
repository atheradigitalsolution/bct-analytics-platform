# -*- coding: utf-8 -*-
"""Cashier shifts and their closing."""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_round

from odoo.addons.custom_hms_billing.models.hms_deposit import PAYMENT_METHODS


class HmsCashierCounter(models.Model):
    _name = "hms.cashier.counter"
    _description = "Loket Kasir"
    _order = "code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    qms_counter_id = fields.Many2one("hms.qms.counter", "Loket Antrian")
    journal_cash_id = fields.Many2one(
        "account.journal", "Jurnal Kas", domain="[('type', '=', 'cash')]",
    )
    printer_id = fields.Many2one("hms.qms.printer", "Printer Kwitansi")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode loket kasir harus unik.")


class HmsCashierSession(models.Model):
    _name = "hms.cashier.session"
    _description = "Shift Kasir"
    _order = "opened_at desc"

    name = fields.Char(readonly=True, default=lambda s: _("Baru"), copy=False)
    counter_id = fields.Many2one("hms.cashier.counter", "Loket", required=True, index=True)
    user_id = fields.Many2one("res.users", "Kasir", required=True,
                              default=lambda s: s.env.user, index=True)
    opened_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    closed_at = fields.Datetime(readonly=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True, readonly=True,
    )
    opening_cash = fields.Monetary("Modal Awal", required=True, default=0.0)
    payment_ids = fields.One2many("hms.payment", "session_id", "Pembayaran")
    line_ids = fields.One2many("hms.cashier.session.line", "session_id", "Rekap per Metode")
    expected_cash = fields.Monetary("Kas Seharusnya", compute="_compute_totals", store=True)
    total_collected = fields.Monetary("Total Diterima", compute="_compute_totals", store=True)
    difference = fields.Monetary("Selisih", compute="_compute_totals", store=True)
    state = fields.Selection(
        [("open", "Terbuka"), ("closing", "Penghitungan"), ("closed", "Ditutup")],
        default="open", required=True, index=True,
    )
    deposit_move_id = fields.Many2one("account.move", "Jurnal Setoran", readonly=True)
    note = fields.Text()

    _name_uniq = models.Constraint("unique(name)", "Nomor shift kasir harus unik.")
    _one_open_per_user = models.UniqueIndex(
        "(user_id, counter_id) WHERE state != 'closed'",
    )

    @api.depends("payment_ids.amount", "payment_ids.state", "payment_ids.method",
                 "opening_cash", "line_ids.counted_amount")
    def _compute_totals(self):
        for session in self:
            done = session.payment_ids.filtered(lambda p: p.state == "done")
            cash = sum(done.filtered(lambda p: p.method == "cash").mapped("amount"))
            change = sum(done.filtered(lambda p: p.method == "cash").mapped("change"))
            session.expected_cash = session.opening_cash + cash - change
            session.total_collected = sum(done.mapped("amount"))
            counted = sum(session.line_ids.mapped("counted_amount"))
            expected = sum(session.line_ids.mapped("expected_amount"))
            session.difference = counted - expected if session.line_ids else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.cashier.session") or "/"
        sessions = super().create(vals_list)
        for session in sessions:
            session.env["hms.event"].emit("cashier.session.opened", {
                "session_id": session.id, "counter_id": session.counter_id.id,
                "user": session.user_id.name,
            })
        return sessions

    @api.model
    def current(self, user=None, raise_if_missing=True):
        """The open shift for a cashier, or a clear refusal."""
        user = user or self.env.user
        session = self.search([
            ("user_id", "=", user.id), ("state", "in", ("open", "closing")),
        ], limit=1)
        if not session and raise_if_missing:
            raise UserError(
                _("%s belum membuka shift kasir. Buka shift terlebih dahulu sebelum "
                  "menerima pembayaran.") % user.name
            )
        return session

    def action_start_closing(self):
        """Freeze the shift and prepare the count sheet, one row per method."""
        self.ensure_one()
        if self.state != "open":
            raise UserError(_("Shift tidak dalam status terbuka."))
        self.line_ids.unlink()
        done = self.payment_ids.filtered(lambda p: p.state == "done")
        methods = {}
        for payment in done:
            methods.setdefault(payment.method, 0.0)
            methods[payment.method] += payment.amount - (
                payment.change if payment.method == "cash" else 0.0
            )
        methods.setdefault("cash", 0.0)
        methods["cash"] += self.opening_cash
        self.env["hms.cashier.session.line"].create([{
            "session_id": self.id,
            "method": method,
            "expected_amount": float_round(amount, precision_digits=2),
        } for method, amount in sorted(methods.items())])
        self.write({"state": "closing"})
        return True

    def action_close(self):
        """Close the shift, recording the difference rather than hiding it."""
        self.ensure_one()
        if self.state != "closing":
            raise UserError(_("Mulai penghitungan fisik terlebih dahulu."))
        unexplained = self.line_ids.filtered(
            lambda l: float_compare(l.difference, 0.0, precision_digits=2) != 0 and not l.note
        )
        if unexplained:
            raise UserError(
                _("Selisih pada metode %s harus dijelaskan sebelum shift ditutup.")
                % ", ".join(
                    dict(PAYMENT_METHODS).get(l.method, l.method) for l in unexplained
                )
            )
        self.write({"state": "closed", "closed_at": fields.Datetime.now()})
        self.env["hms.event"].emit("cashier.session.closed", {
            "session_id": self.id,
            "difference": self.difference,
            "total": self.total_collected,
        })
        return True

    def closing_summary(self):
        """Numbers the closing report and the dashboard both read."""
        self.ensure_one()
        done = self.payment_ids.filtered(lambda p: p.state == "done")
        by_payer = {}
        for payment in done:
            payer = payment.bill_id.payer_id.name or _("Umum")
            by_payer[payer] = by_payer.get(payer, 0.0) + payment.amount
        return {
            "session": self.name,
            "cashier": self.user_id.name,
            "counter": self.counter_id.name,
            "opened_at": fields.Datetime.to_string(self.opened_at),
            "closed_at": fields.Datetime.to_string(self.closed_at),
            "opening_cash": self.opening_cash,
            "by_method": [{
                "method": dict(PAYMENT_METHODS).get(line.method, line.method),
                "expected": line.expected_amount,
                "counted": line.counted_amount,
                "difference": line.difference,
                "note": line.note or "",
            } for line in self.line_ids],
            "by_payer": by_payer,
            "transaction_count": len(done),
            "void_count": len(self.payment_ids.filtered(lambda p: p.state == "void")),
            "total": self.total_collected,
            "difference": self.difference,
        }


class HmsCashierSessionLine(models.Model):
    _name = "hms.cashier.session.line"
    _description = "Rekap Metode Pembayaran Shift"
    _order = "method"

    session_id = fields.Many2one("hms.cashier.session", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="session_id.currency_id", readonly=True)
    method = fields.Selection(PAYMENT_METHODS, required=True)
    expected_amount = fields.Monetary("Seharusnya", readonly=True)
    counted_amount = fields.Monetary("Hitungan Fisik")
    difference = fields.Monetary("Selisih", compute="_compute_difference", store=True)
    note = fields.Char("Keterangan Selisih")

    @api.depends("expected_amount", "counted_amount")
    def _compute_difference(self):
        for line in self:
            line.difference = line.counted_amount - line.expected_amount


class HmsPayment(models.Model):
    _inherit = "hms.payment"

    session_id = fields.Many2one("hms.cashier.session", "Shift Kasir", index=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Attach every payment to the cashier's open shift.

        The requirement only bites once the hospital has actually configured
        cashier counters. A site that settles bills from the back office —
        and the module's own installation, before any counter exists — keeps
        working; the moment shift control is set up, it is enforced.

        Deposits and receivable conversions are exempt either way: they never
        pass through a cashier's drawer. So is anything posted with
        `hms_back_office=True`, which is how finance records a guarantor
        settlement that arrives by bank transfer rather than at a counter.
        """
        Session = self.env["hms.cashier.session"]
        if self.env.context.get("hms_back_office"):
            return super().create(vals_list)
        shift_control = bool(self.env["hms.cashier.counter"].sudo().search_count([]))
        for vals in vals_list:
            if vals.get("session_id") or vals.get("method") in ("deposit", "receivable"):
                continue
            session = Session.current(raise_if_missing=False)
            if not session and shift_control:
                raise UserError(
                    _("Buka shift kasir terlebih dahulu sebelum menerima pembayaran. "
                      "Setiap penerimaan uang harus dapat ditelusuri ke satu shift.")
                )
            vals["session_id"] = session.id if session else False
        return super().create(vals_list)
