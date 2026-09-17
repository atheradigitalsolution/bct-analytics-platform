# -*- coding: utf-8 -*-
"""What comes back, and whether it is worth keeping.

The question this answers is the one that distorts job margin more than any other in
this business: who pays for the part of the sheet that was not used. Charging it all
to the job that opened the sheet is simple and wrong -- the next three jobs get their
material free. Charging none of it is worse. So a remnant is measured against a
threshold: big enough to be used again, or waste.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"


class CustomSpkMaterialReturn(models.Model):
    _name = "custom.spk.material.return"
    _description = "Retur / Sisa Material"
    _inherit = ["pdp.audited.mixin", "mail.thread"]
    _order = "id desc"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="restrict",
        help="The job the material was issued to, and the one credited if the remnant "
        "is worth keeping.",
    )
    returned_by = fields.Many2one("hr.employee", string="Dikembalikan oleh")
    date = fields.Date(default=fields.Date.context_today, required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")], default="draft", required=True, tracking=True)
    line_ids = fields.One2many("custom.spk.material.return.line", "return_id")
    credit_total = fields.Monetary(
        string="Kredit ke SPK", compute="_compute_totals", store=True,
        currency_field="currency_id", groups=COST_GROUP)
    waste_total = fields.Monetary(
        string="Waste ke SPK", compute="_compute_totals", store=True,
        currency_field="currency_id", groups=COST_GROUP)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "custom.spk.material.return") or _("New")
        return super().create(vals_list)

    @api.depends("line_ids.credit_amount", "line_ids.waste_amount")
    def _compute_totals(self):
        for rec in self:
            rec.credit_total = sum(rec.line_ids.mapped("credit_amount"))
            rec.waste_total = sum(rec.line_ids.mapped("waste_amount"))

    def action_done(self):
        """Credit the job for reusable remnants; leave waste where it fell.

        The credit is an analytic line rather than a stock valuation adjustment,
        because what is being corrected is the job's cost, not the warehouse's. The
        remnant's own value enters stock separately as its offcut product.
        """
        AnalyticLine = self.env["account.analytic.line"].sudo()
        for rec in self:
            if rec.state == "done":
                raise UserError(_("%(name)s is already booked.", name=rec.name))
            if not rec.spk_id.analytic_account_id:
                raise UserError(
                    _("%(spk)s has no analytic account to credit.", spk=rec.spk_id.name))
            for line in rec.line_ids.filtered(lambda l: l.credit_amount > 0):
                vals = {
                    "name": _("Sisa material kembali: %(product)s",
                              product=line.product_id.display_name),
                    "date": rec.date,
                    "account_id": rec.spk_id.analytic_account_id.id,
                    # Positive: this reduces the job's cost, which is held negative.
                    "amount": abs(line.credit_amount),
                }
                # A credit belongs in the same bucket as the cost it reverses, or the
                # material variance would show the issue without the return.
                if "x_spk_cost_category" in AnalyticLine._fields:
                    vals["x_spk_cost_category"] = "material"
                AnalyticLine.create(vals)
            rec.state = "done"
        return True


class CustomSpkMaterialReturnLine(models.Model):
    _name = "custom.spk.material.return.line"
    _description = "Baris Retur Material"
    _order = "return_id, id"

    return_id = fields.Many2one(
        "custom.spk.material.return", required=True, ondelete="cascade", index=True)
    currency_id = fields.Many2one(related="return_id.currency_id", groups=COST_GROUP)
    product_id = fields.Many2one("product.product", required=True)
    qty_returned = fields.Float(string="Qty Kembali", required=True, default=1.0)
    remnant_share = fields.Float(
        string="Sisa % dari Unit",
        required=True,
        default=100.0,
        help="How much of a full unit this remnant still is. A 244x122 sheet with a "
        "0.9 m2 piece left is about 30%. Entered rather than derived, because the "
        "person holding the piece can see its shape and the system cannot.",
    )
    is_reusable = fields.Boolean(
        compute="_compute_classification", store=True,
        help="At or above the product's threshold. Below it, the piece is waste and the "
        "job keeps the cost.",
    )
    credit_amount = fields.Monetary(
        compute="_compute_classification", store=True,
        currency_field="currency_id", groups=COST_GROUP,
        help="What the originating job gets back: the remnant's discounted value.",
    )
    waste_amount = fields.Monetary(
        compute="_compute_classification", store=True,
        currency_field="currency_id", groups=COST_GROUP,
        help="What the job keeps carrying, for pieces too small to be worth storing.",
    )

    @api.depends("product_id", "qty_returned", "remnant_share")
    def _compute_classification(self):
        for rec in self:
            product = rec.product_id.sudo()
            template = product.product_tmpl_id
            full_value = (product.standard_price or 0.0) * (rec.qty_returned or 0.0)
            if not product or template.x_spk_material_class != "a_stock":
                # Only recut stock produces a remnant worth arguing about. A made-to-order
                # banner cut to one size has no second life, and pretending it does would
                # move real cost off the job that caused it.
                rec.is_reusable = False
                rec.credit_amount = 0.0
                rec.waste_amount = full_value
                continue
            rec.is_reusable = rec.remnant_share >= (template.x_spk_offcut_threshold_pct or 0.0)
            if rec.is_reusable:
                rec.credit_amount = full_value * (
                    (template.x_spk_offcut_valuation_pct or 0.0) / 100.0)
                rec.waste_amount = full_value - rec.credit_amount
            else:
                rec.credit_amount = 0.0
                rec.waste_amount = full_value

    @api.constrains("qty_returned", "remnant_share")
    def _check_values(self):
        for rec in self:
            if rec.qty_returned <= 0:
                raise ValidationError(_("A return of nothing is not a return."))
            if not 0.0 < rec.remnant_share <= 100.0:
                raise ValidationError(
                    _("A remnant is more than nothing and at most a whole unit; got "
                      "%(pct)s%%.", pct=rec.remnant_share)
                )
