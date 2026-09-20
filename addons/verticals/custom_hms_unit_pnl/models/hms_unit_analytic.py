# -*- coding: utf-8 -*-
"""Bind each service unit to an analytic account."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

PLAN_NAME = "Unit Layanan"


class HmsUnit(models.Model):
    _inherit = "hms.unit"

    analytic_account_id = fields.Many2one(
        "account.analytic.account", "Akun Analitik", copy=False,
        help="Semua pendapatan dan biaya unit ini dikaitkan ke akun analitik tersebut.",
    )
    cost_center_code = fields.Char("Kode Cost Center")
    headcount = fields.Integer("Jumlah Staf", compute="_compute_headcount")
    overhead_pool = fields.Boolean(
        "Unit Overhead",
        help="Unit yang biayanya dialokasikan ke unit penghasil pendapatan, "
             "mis. manajemen, IT, laundry.",
    )

    def _compute_headcount(self):
        for unit in self:
            unit.headcount = len(unit.practitioner_ids)

    @api.model
    def _analytic_plan(self):
        Plan = self.env["account.analytic.plan"]
        plan = Plan.search([("name", "=", PLAN_NAME)], limit=1)
        if not plan:
            plan = Plan.create({"name": PLAN_NAME})
        return plan

    def action_create_analytic_account(self):
        """Create the analytic account for units that do not have one yet."""
        plan = self._analytic_plan()
        for unit in self.filtered(lambda u: not u.analytic_account_id):
            unit.analytic_account_id = self.env["account.analytic.account"].create({
                "name": unit.name,
                "code": unit.code,
                "plan_id": plan.id,
                "company_id": self.env.company.id,
            })
        return True

    def _ensure_analytic(self):
        self.ensure_one()
        if not self.analytic_account_id:
            self.action_create_analytic_account()
        return self.analytic_account_id


class HmsTariffCategory(models.Model):
    _inherit = "hms.tariff.category"

    revenue_account_id = fields.Many2one(
        "account.account", "Akun Pendapatan",
        help="Dipakai bila kategori ini tidak punya produk jurnal tersendiri.",
    )
    tax_ids = fields.Many2many("account.tax", string="Pajak")


class HmsBillLine(models.Model):
    _inherit = "hms.bill.line"

    def _prepare_move_line_vals(self, portion):
        """Tag every invoice line with the delivering unit's analytic account.

        This is the single hook that makes unit P&L possible; without it the
        general ledger knows what was earned but not by whom.
        """
        vals = super()._prepare_move_line_vals(portion)
        unit = self.unit_id or self.bill_id.unit_id
        if unit:
            account = unit.sudo()._ensure_analytic()
            if account:
                vals["analytic_distribution"] = {str(account.id): 100.0}
        if self.category_id.revenue_account_id and not vals.get("product_id"):
            vals["account_id"] = self.category_id.revenue_account_id.id
        return vals
