# -*- coding: utf-8 -*-
"""Pilih baris mana yang masuk faktur kali ini.

Satu job dapat difakturkan bertahap — lazim di forwarding, karena freight sudah
bisa ditagih saat kapal berangkat sementara biaya pelabuhan tujuan baru diketahui
dua minggu kemudian. Wizard ini yang membuat pemilihan itu eksplisit alih-alih
memfakturkan semuanya sekaligus dan mengoreksinya dengan nota kredit.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxJobInvoiceWizard(models.TransientModel):
    _name = "lgx.job.invoice.wizard"
    _description = "Wizard Faktur dari Job"

    job_id = fields.Many2one("lgx.job", "Job", required=True, readonly=True)
    currency_id = fields.Many2one(related="job_id.currency_id", readonly=True)
    charge_ids = fields.Many2many(
        "lgx.job.charge", string="Baris yang Difakturkan",
        domain="[('job_id','=',job_id),('kind','=','revenue'),('state','=','confirmed'),('invoice_line_id','=',False)]",
    )
    amount_total = fields.Monetary("Total", compute="_compute_amount", currency_field="currency_id")
    disbursement_total = fields.Monetary("Di antaranya Talangan", compute="_compute_amount",
                                         currency_field="currency_id")
    missing_proof_count = fields.Integer("Talangan Tanpa Bukti", compute="_compute_amount")

    @api.depends("charge_ids")
    def _compute_amount(self):
        for wiz in self:
            wiz.amount_total = sum(wiz.charge_ids.mapped("amount_effective"))
            disb = wiz.charge_ids.filtered(lambda c: c.nature == "disbursement")
            wiz.disbursement_total = sum(disb.mapped("amount_effective"))
            wiz.missing_proof_count = len(disb.filtered(lambda c: not c.third_party_proof_ids))

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        job = self.env["lgx.job"].browse(vals.get("job_id") or self.env.context.get("default_job_id"))
        if job:
            vals["charge_ids"] = [(6, 0, job.charge_ids.filtered(
                lambda c: c.kind == "revenue" and c.state == "confirmed" and not c.invoice_line_id
            ).ids)]
        return vals

    def action_create_invoice(self):
        self.ensure_one()
        if not self.charge_ids:
            raise UserError(_("Pilih minimal satu baris untuk difakturkan."))
        invoice = self.job_id.lgx_create_customer_invoice(self.charge_ids)
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": invoice.id,
            "view_mode": "form",
        }
