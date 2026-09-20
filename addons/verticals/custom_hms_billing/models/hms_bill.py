# -*- coding: utf-8 -*-
"""The patient bill."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero


class HmsBill(models.Model):
    _name = "hms.bill"
    _description = "Tagihan Pasien"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "id desc"

    name = fields.Char("No. Tagihan", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    payer_id = fields.Many2one(related="encounter_id.payer_id", store=True)
    payer_plan_id = fields.Many2one(related="encounter_id.payer_plan_id", store=True)
    admission_id = fields.Many2one("hms.admission", "Admisi", index=True)
    unit_id = fields.Many2one(related="encounter_id.unit_id", store=True)

    line_ids = fields.One2many("hms.bill.line", "bill_id", "Baris Tagihan")
    deposit_ids = fields.One2many("hms.deposit", "bill_id", "Deposit")
    payment_ids = fields.One2many("hms.payment", "bill_id", "Pembayaran")
    authorization_ids = fields.One2many("hms.billing.authorization", "bill_id", "Otorisasi")

    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True, readonly=True,
    )
    amount_gross = fields.Monetary("Total Bruto", compute="_compute_amounts", store=True)
    amount_discount = fields.Monetary("Diskon", compute="_compute_amounts", store=True)
    amount_total = fields.Monetary("Total Tagihan", compute="_compute_amounts", store=True)
    amount_payer = fields.Monetary("Porsi Penjamin", compute="_compute_amounts", store=True)
    amount_patient = fields.Monetary("Porsi Pasien", compute="_compute_amounts", store=True)
    amount_deposit = fields.Monetary("Deposit Terpakai", compute="_compute_amounts", store=True)
    amount_paid = fields.Monetary("Sudah Dibayar", compute="_compute_amounts", store=True)
    amount_due = fields.Monetary("Sisa Bayar", compute="_compute_amounts", store=True)

    unpriced_line_count = fields.Integer(
        "Baris Tanpa Tarif", compute="_compute_unpriced", store=True,
    )
    state = fields.Selection(
        [("draft", "Berjalan"), ("open", "Siap Bayar"), ("paid", "Lunas"),
         ("closed", "Ditutup"), ("cancelled", "Batal")],
        default="draft", required=True, tracking=True, index=True,
    )
    closed_at = fields.Datetime(readonly=True)
    closed_by_id = fields.Many2one("res.users", readonly=True)
    move_ids = fields.One2many("account.move", "hms_bill_id", "Invoice")
    move_count = fields.Integer(compute="_compute_move_count")
    note = fields.Text()

    _name_uniq = models.Constraint("unique(name)", "Nomor tagihan harus unik.")
    _encounter_uniq = models.Constraint(
        "unique(encounter_id)",
        "Satu kunjungan hanya boleh punya satu tagihan. Tagihan kedua untuk "
        "kunjungan yang sama selalu berakhir sebagai selisih yang tidak tertagih.",
    )

    @api.depends("line_ids.price_subtotal", "line_ids.discount_amount", "line_ids.state",
                 "line_ids.amount_payer", "line_ids.amount_patient",
                 "deposit_ids.used_amount", "payment_ids.amount", "payment_ids.state")
    def _compute_amounts(self):
        for bill in self:
            lines = bill.line_ids.filtered(lambda l: l.state != "cancelled")
            bill.amount_gross = sum(lines.mapped("price_subtotal"))
            bill.amount_discount = sum(lines.mapped("discount_amount"))
            bill.amount_total = bill.amount_gross - bill.amount_discount
            bill.amount_payer = sum(lines.mapped("amount_payer"))
            bill.amount_patient = sum(lines.mapped("amount_patient"))
            bill.amount_deposit = sum(bill.deposit_ids.mapped("used_amount"))
            bill.amount_paid = sum(
                bill.payment_ids.filtered(lambda p: p.state == "done").mapped("amount")
            )
            bill.amount_due = bill.amount_patient - bill.amount_deposit - bill.amount_paid

    @api.depends("line_ids.price_missing", "line_ids.state")
    def _compute_unpriced(self):
        for bill in self:
            bill.unpriced_line_count = len(bill.line_ids.filtered(
                lambda l: l.price_missing and l.state != "cancelled"
            ))

    def _compute_move_count(self):
        for bill in self:
            bill.move_count = len(bill.move_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.bill") or "/"
        return super().create(vals_list)

    @api.model
    def get_or_create_for(self, encounter):
        """The single entry point for anything that needs to charge a visit."""
        bill = self.search([("encounter_id", "=", encounter.id)], limit=1)
        if bill:
            return bill
        admission = self.env["hms.admission"].search(
            [("encounter_id", "=", encounter.id)], limit=1
        )
        return self.create({
            "encounter_id": encounter.id,
            "admission_id": admission.id if admission else False,
        })

    # --- workflow ---------------------------------------------------------
    def action_open(self):
        """Freeze the bill for payment."""
        for bill in self:
            if bill.state != "draft":
                raise UserError(_("Tagihan %s tidak dalam status berjalan.") % bill.name)
            if not bill.line_ids:
                raise UserError(_("Tagihan %s belum memiliki baris.") % bill.name)
            if bill.unpriced_line_count:
                unpriced = bill.line_ids.filtered(
                    lambda l: l.price_missing and l.state != "cancelled"
                )
                raise UserError(
                    _("%(n)s layanan pada tagihan %(b)s belum punya tarif yang berlaku "
                      "dan tidak dapat ditagihkan:\n- %(items)s\n\n"
                      "Lengkapi harga tarifnya lebih dulu, atau batalkan barisnya bila "
                      "layanan itu memang tidak ditagihkan.")
                    % {"n": bill.unpriced_line_count, "b": bill.name,
                       "items": "\n- ".join(unpriced.mapped("name"))}
                )
            bill.write({"state": "open"})
            bill.env["hms.event"].emit("bill.opened", {
                "bill_id": bill.id, "encounter_id": bill.encounter_id.id,
                "patient": bill.patient_id.name, "amount_due": bill.amount_due,
            })
        return True

    def action_close(self):
        """Post the invoices. This is the accounting boundary."""
        for bill in self:
            if bill.state not in ("open", "paid"):
                raise UserError(
                    _("Tagihan %s harus berstatus siap bayar sebelum ditutup.") % bill.name
                )
            if bill.move_ids:
                raise UserError(_("Tagihan %s sudah memiliki invoice.") % bill.name)
            moves = bill._create_invoices()
            moves.action_post()
            bill.write({
                "state": "closed",
                "closed_at": fields.Datetime.now(),
                "closed_by_id": self.env.uid,
            })
            bill.env["hms.event"].emit("bill.closed", {
                "bill_id": bill.id, "move_ids": moves.ids, "total": bill.amount_total,
            })
        return True

    def _create_invoices(self):
        """One invoice per counterparty.

        A split bill produces two: the guarantor's portion addressed to the
        guarantor, the patient's to the patient. Putting both on one invoice
        would make the receivable ageing meaningless — the two are collected by
        different people on different terms.
        """
        self.ensure_one()
        Move = self.env["account.move"]
        moves = Move
        lines = self.line_ids.filtered(lambda l: l.state != "cancelled")

        payer_lines = lines.filtered(
            lambda l: not float_is_zero(l.amount_payer, precision_digits=2)
        )
        if payer_lines and self.payer_id.partner_id:
            moves |= Move.create(self._prepare_move_vals(
                self.payer_id.partner_id, payer_lines, "payer",
            ))

        patient_lines = lines.filtered(
            lambda l: not float_is_zero(l.amount_patient, precision_digits=2)
        )
        if patient_lines:
            moves |= Move.create(self._prepare_move_vals(
                self.patient_id.partner_id, patient_lines, "patient",
            ))
        if not moves:
            raise UserError(
                _("Tagihan %s tidak menghasilkan invoice: semua baris bernilai nol.") % self.name
            )
        return moves

    def _prepare_move_vals(self, partner, lines, portion):
        self.ensure_one()
        return {
            "move_type": "out_invoice",
            "partner_id": partner.id,
            "invoice_origin": self.name,
            "hms_bill_id": self.id,
            "invoice_date": fields.Date.context_today(self),
            "invoice_payment_term_id": (
                self.payer_id.payment_term_id.id if portion == "payer" else False
            ),
            "invoice_line_ids": [
                (0, 0, line._prepare_move_line_vals(portion)) for line in lines
            ],
        }

    def action_cancel(self):
        for bill in self:
            if bill.move_ids.filtered(lambda m: m.state == "posted"):
                raise UserError(
                    _("Tagihan %s sudah memiliki invoice terposting. Batalkan invoice "
                      "lewat modul Akuntansi terlebih dahulu.") % bill.name
                )
            bill.write({"state": "cancelled"})
        return True

    def action_reopen(self):
        for bill in self:
            if bill.state == "closed":
                raise UserError(
                    _("Tagihan yang sudah ditutup tidak dapat dibuka kembali karena "
                      "invoicenya sudah terposting.")
                )
            bill.write({"state": "draft"})
        return True

    def action_view_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Invoice"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.move_ids.ids)],
        }

    def _mark_paid_if_settled(self):
        for bill in self:
            if bill.state == "open" and float_compare(
                bill.amount_due, 0.0, precision_digits=2
            ) <= 0:
                bill.write({"state": "paid"})


class AccountMove(models.Model):
    _inherit = "account.move"

    hms_bill_id = fields.Many2one("hms.bill", "Tagihan SIMRS", index=True, copy=False)


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    bill_id = fields.Many2one("hms.bill", "Tagihan", compute="_compute_bill_id", store=True)

    @api.depends("name")
    def _compute_bill_id(self):
        for enc in self:
            enc.bill_id = self.env["hms.bill"].search(
                [("encounter_id", "=", enc.id)], limit=1
            )


class HmsAdmission(models.Model):
    _inherit = "hms.admission"

    def _extra_discharge_blockers(self):
        """An unpaid bill keeps the patient in the system, not in the bed.

        Reported as a blocker rather than enforced silently: hospitals do
        discharge patients with an outstanding balance, and when they do it is
        a supervisor's decision recorded as a forced discharge.
        """
        blockers = super()._extra_discharge_blockers()
        bill = self.env["hms.bill"].search([("encounter_id", "=", self.encounter_id.id)], limit=1)
        if bill and float_compare(bill.amount_due, 0.0, precision_digits=2) > 0:
            blockers.append(
                _("Sisa tagihan %(amt)s belum dilunasi.")
                % {"amt": bill.amount_due}
            )
        return blockers
