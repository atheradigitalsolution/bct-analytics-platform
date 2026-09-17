# -*- coding: utf-8 -*-
"""Bill of quantity, and the price derived from it."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

CATEGORIES = [
    ("material", "Material"),
    ("labor", "Tenaga Kerja"),
    ("subcon", "Subcon"),
    ("delivery", "Delivery & Instalasi"),
    ("venue", "Biaya Venue"),
]

COST_GROUP = "custom_spk.group_spk_cost_viewer"
PRICE_GROUP = "custom_spk.group_spk_price_viewer"


class CustomSpkEstimation(models.Model):
    _name = "custom.spk.estimation"
    _description = "Estimasi / Bill of Quantity"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one("custom.spk", string="SPK", index=True, ondelete="cascade")
    partner_id = fields.Many2one(related="spk_id.partner_id", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related="company_id.currency_id", store=True, groups=COST_GROUP)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("superseded", "Superseded")],
        default="draft", required=True, tracking=True,
    )
    revision = fields.Integer(default=1, readonly=True)
    line_ids = fields.One2many("custom.spk.estimation.line", "estimation_id")

    # ---- rates. Ratios, so they are not money and stay visible to the estimator ----
    overhead_rate = fields.Float(
        string="Overhead %", default=12.0,
        help="Applied to direct cost. Workshop rent, tools, indirect staff.",
    )
    risk_rate = fields.Float(
        string="Contingency %", default=5.0,
        help="Raise it for a new client or a timeline that leaves no room to be wrong.",
    )
    target_margin = fields.Float(
        string="Target Margin %", default=30.0, groups=PRICE_GROUP,
        help="The margin wanted ON THE PRICE, which is why the price divides rather "
        "than multiplies. See _compute_price.",
    )

    # ---- cost: for whoever estimates ----
    material_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    labor_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    subcon_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    delivery_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    venue_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    direct_cost = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    overhead_amount = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    total_cost = fields.Monetary(
        string="Total Cost (HPP)", compute="_compute_totals", store=True,
        currency_field="currency_id", groups=COST_GROUP)
    contingency_amount = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    base_price = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id", groups=COST_GROUP)
    waste_allowance = fields.Monetary(
        string="Waste Allowance", compute="_compute_totals", store=True,
        currency_field="currency_id", groups=COST_GROUP,
        help="The part of material cost that is expected to become offcut and waste. "
        "Carried separately so the finished job can be measured against it.",
    )

    # ---- price and margin: owner and finance only ----
    quoted_price = fields.Monetary(
        compute="_compute_price", store=True, currency_field="currency_id", groups=PRICE_GROUP)
    margin_amount = fields.Monetary(
        compute="_compute_price", store=True, currency_field="currency_id", groups=PRICE_GROUP)

    @api.depends("line_ids.subtotal", "line_ids.category", "line_ids.waste_amount",
                 "overhead_rate", "risk_rate")
    def _compute_totals(self):
        for rec in self:
            buckets = dict.fromkeys([c[0] for c in CATEGORIES], 0.0)
            for line in rec.line_ids:
                buckets[line.category] = buckets.get(line.category, 0.0) + line.subtotal
            rec.material_cost = buckets["material"]
            rec.labor_cost = buckets["labor"]
            rec.subcon_cost = buckets["subcon"]
            rec.delivery_cost = buckets["delivery"]
            rec.venue_cost = buckets["venue"]
            rec.waste_allowance = sum(rec.line_ids.mapped("waste_amount"))
            rec.direct_cost = sum(buckets.values())
            rec.overhead_amount = rec.direct_cost * (rec.overhead_rate / 100.0)
            rec.total_cost = rec.direct_cost + rec.overhead_amount
            rec.contingency_amount = rec.total_cost * (rec.risk_rate / 100.0)
            rec.base_price = rec.total_cost + rec.contingency_amount

    @api.depends("base_price", "target_margin")
    def _compute_price(self):
        """price = cost / (1 - margin), NOT cost * (1 + margin).

        The markup form is the usual error and it is always short. Mark 100 up by
        30% and the result is 130, whose margin is 30/130 = 23%. Quoting that way
        for a year is how a business believes it runs on 30% and does not.

        A target of 100% or more has no solution, so it is refused rather than
        producing an infinity somebody would ship.
        """
        for rec in self:
            margin_fraction = (rec.target_margin or 0.0) / 100.0
            if margin_fraction >= 1.0:
                rec.quoted_price = 0.0
                rec.margin_amount = 0.0
                continue
            rec.quoted_price = rec.base_price / (1.0 - margin_fraction)
            rec.margin_amount = rec.quoted_price - rec.base_price

    @api.constrains("overhead_rate", "risk_rate", "target_margin")
    def _check_rates(self):
        for rec in self:
            if rec.overhead_rate < 0 or rec.risk_rate < 0:
                raise ValidationError(_("Overhead and contingency cannot be negative."))
            if rec.target_margin >= 100.0:
                raise ValidationError(
                    _("A target margin of %(pct)s%% has no price that satisfies it: "
                      "margin is taken ON the price, so 100%% would need an infinite one.",
                      pct=rec.target_margin)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "custom.spk.estimation") or _("New")
        return super().create(vals_list)

    def action_approve(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(
                    _("%(name)s has no lines, so its price is derived from nothing.",
                      name=rec.name)
                )
            rec.state = "approved"
        return True

    def action_revise(self):
        """Supersede rather than overwrite, so a negotiation keeps its history."""
        new_records = self.env["custom.spk.estimation"]
        for rec in self:
            copy = rec.copy({
                "revision": rec.revision + 1,
                "state": "draft",
                "name": _("New"),
            })
            rec.state = "superseded"
            new_records |= copy
        return new_records


class CustomSpkEstimationLine(models.Model):
    _name = "custom.spk.estimation.line"
    _description = "Baris Estimasi"
    _order = "estimation_id, category, id"

    estimation_id = fields.Many2one(
        "custom.spk.estimation", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="estimation_id.currency_id", groups=COST_GROUP)
    category = fields.Selection(CATEGORIES, required=True, default="material")
    name = fields.Char(string="Uraian", required=True)
    product_id = fields.Many2one("product.product", string="Produk")
    work_item = fields.Char(
        string="Item Pekerjaan",
        help="Which part of the job this belongs to, e.g. Booth Utama 6x6. Free text "
        "rather than a model: the breakdown differs per job and a taxonomy would be "
        "maintained by nobody.",
    )
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one("uom.uom", string="Satuan")
    unit_cost = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    waste_pct = fields.Float(
        string="Waste %", default=0.0,
        help="Expected loss for this material: a sheet is not consumed in the shape a "
        "booth needs. Zero for labour and subcontract lines.",
    )
    waste_amount = fields.Monetary(
        compute="_compute_subtotal", store=True, currency_field="currency_id", groups=COST_GROUP)
    subtotal = fields.Monetary(
        compute="_compute_subtotal", store=True, currency_field="currency_id", groups=COST_GROUP)

    @api.depends("quantity", "unit_cost", "waste_pct")
    def _compute_subtotal(self):
        for rec in self:
            base = (rec.quantity or 0.0) * (rec.unit_cost or 0.0)
            rec.waste_amount = base * ((rec.waste_pct or 0.0) / 100.0)
            rec.subtotal = base + rec.waste_amount

    @api.constrains("quantity", "waste_pct")
    def _check_values(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError(_("A line with no quantity estimates nothing."))
            if not 0.0 <= rec.waste_pct < 100.0:
                raise ValidationError(
                    _("Waste of %(pct)s%% is not an allowance; it says the material is "
                      "entirely lost.", pct=rec.waste_pct)
                )
