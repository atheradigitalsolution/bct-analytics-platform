# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PpobProduct(models.Model):
    _name = "custom.ppob.product"
    _description = "PPOB Product / SKU"
    _order = "class_id, denom, code"

    code = fields.Char(
        required=True,
        copy=False,
        help="Internal SKU (e.g., TSEL5, PLN20K, BPJS).",
    )
    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    class_id = fields.Many2one(
        comodel_name="custom.ppob.product.class",
        string="Class",
        required=True,
        ondelete="restrict",
    )
    denom = fields.Monetary(
        string="Denomination",
        currency_field="currency_id",
        help="Nominal value for fixed-denomination products (pulsa, token). "
        "0 means variable / open amount (PLN postpaid, BPJS).",
    )
    cost_price_default = fields.Monetary(
        string="Default Cost Price",
        currency_field="currency_id",
        help="Default buy price. Per-provider override on custom.ppob.provider.sku.map takes precedence.",
    )
    inquiry_required = fields.Boolean(
        string="Requires Inquiry",
        default=False,
        help="Check for products that need a 2-step flow (inquiry, then pay): PLN postpaid, BPJS, PDAM, etc.",
    )
    currency_id = fields.Many2one(
        comodel_name="res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    revenue_account_id = fields.Many2one(
        comodel_name="account.account",
        string="Revenue Account",
        domain="[('account_type', '=', 'income')]",
        help="Overrides the product class default.",
    )
    cogs_account_id = fields.Many2one(
        comodel_name="account.account",
        string="COGS Account",
        domain="[('account_type', '=', 'expense_direct_cost')]",
        help="Overrides the product class default.",
    )

    _code_uniq = models.Constraint(
        "unique(code)",
        "PPOB product code must be unique.",
    )

    #: product class code -> ppob.biller category. The ledger's category is a
    #: required Selection and dbt joins dim_biller on it, so an unmapped class
    #: lands in `other` rather than blocking a dispatch.
    LEDGER_BILLER_CATEGORY = {
        "TELKO": "telco",
        "PLN": "electricity",
        "PDAM": "water",
        "INTERNET": "internet",
        "BPJS": "insurance",
        "MULTIFINANCE": "multifinance",
        "PAJAK": "tax",
    }

    def _resolve_ledger_biller(self):
        """Return (creating if needed) the ppob.biller this product bills through.

        ``ppob.transaction.biller_id`` is required and dbt asserts the
        relationship to stg_ppob_biller, so every engine transaction needs one.
        The engine routes by provider and SKU, not by biller, so the biller is
        derived from the product class -- one biller per class, which is the
        grain dim_biller is meant to have.
        """
        self.ensure_one()
        klass = self.class_id
        if not klass:
            return self.env["ppob.biller"]
        Biller = self.env["ppob.biller"].sudo()
        code = (klass.code or "OTHER").upper()
        biller = Biller.search(
            [("code", "=", code), ("company_id", "in", [False, self.env.company.id])],
            limit=1,
        )
        if biller:
            return biller
        return Biller.create(
            {
                "name": klass.name or code,
                "code": code,
                "category": self.LEDGER_BILLER_CATEGORY.get(code, "other"),
                "company_id": self.env.company.id,
            }
        )

    def _get_revenue_account(self):
        self.ensure_one()
        return self.revenue_account_id or self.class_id.default_revenue_account_id

    def _get_cogs_account(self):
        self.ensure_one()
        return self.cogs_account_id or self.class_id.default_cogs_account_id

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
