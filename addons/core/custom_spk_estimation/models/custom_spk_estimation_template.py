# -*- coding: utf-8 -*-
"""Reusable bills of quantity.

A booth 3x3, a backdrop, a display table: these recur, and re-typing them is where
estimating time goes and where transcription errors enter. A template is the same
line structure without an SPK, applied onto a fresh estimation.

Deliberately a copy, not a link. Once applied, the estimate belongs to the job and
editing the template must not reach back and change what was quoted last month.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError

COST_GROUP = "custom_spk.group_spk_cost_viewer"


class CustomSpkEstimationTemplate(models.Model):
    _name = "custom.spk.estimation.template"
    _description = "Template Estimasi (BoQ)"
    _order = "name"

    name = fields.Char(required=True)
    booth_type = fields.Selection(
        [
            ("custom", "Custom Booth"),
            ("modular", "Modular"),
            ("mockup", "Mockup Produk"),
            ("display", "Display"),
        ],
        default="custom",
    )
    note = fields.Text()
    active = fields.Boolean(default=True)
    line_ids = fields.One2many("custom.spk.estimation.template.line", "template_id")
    overhead_rate = fields.Float(string="Overhead %", default=12.0)
    risk_rate = fields.Float(string="Contingency %", default=5.0)

    def action_apply_to(self, estimation):
        """Copy the template's lines onto an estimation, leaving the template alone."""
        self.ensure_one()
        if estimation.state != "draft":
            raise UserError(
                _("%(name)s is no longer a draft; applying a template would rewrite a "
                  "price that has already been quoted.", name=estimation.name)
            )
        Line = self.env["custom.spk.estimation.line"]
        for tmpl_line in self.line_ids:
            Line.create({
                "estimation_id": estimation.id,
                "category": tmpl_line.category,
                "name": tmpl_line.name,
                "product_id": tmpl_line.product_id.id or False,
                "work_item": tmpl_line.work_item,
                "quantity": tmpl_line.quantity,
                "uom_id": tmpl_line.uom_id.id or False,
                "unit_cost": tmpl_line.unit_cost,
                "waste_pct": tmpl_line.waste_pct,
            })
        estimation.write({
            "overhead_rate": self.overhead_rate,
            "risk_rate": self.risk_rate,
        })
        return estimation


class CustomSpkEstimationTemplateLine(models.Model):
    _name = "custom.spk.estimation.template.line"
    _description = "Baris Template Estimasi"
    _order = "template_id, category, id"

    template_id = fields.Many2one(
        "custom.spk.estimation.template", required=True, ondelete="cascade")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)
    category = fields.Selection(
        [
            ("material", "Material"),
            ("labor", "Tenaga Kerja"),
            ("subcon", "Subcon"),
            ("delivery", "Delivery & Instalasi"),
            ("venue", "Biaya Venue"),
        ],
        required=True, default="material",
    )
    name = fields.Char(string="Uraian", required=True)
    product_id = fields.Many2one("product.product")
    work_item = fields.Char(string="Item Pekerjaan")
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one("uom.uom")
    unit_cost = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    waste_pct = fields.Float(string="Waste %", default=0.0)
