# -*- coding: utf-8 -*-
"""Material class, and the offcut rule that follows from it."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"

MATERIAL_CLASSES = [
    ("a_stock", "A — Stock item (dihitung ulang)"),
    ("b_consumable", "B — Consumable (standar pemakaian)"),
    ("c_fixed_unit", "C — Fixed unit (utuh)"),
    ("d_made_to_order", "D — Custom / made to order"),
]


class ProductTemplate(models.Model):
    _inherit = "product.template"

    x_spk_material_class = fields.Selection(
        MATERIAL_CLASSES,
        string="Kelas Material",
        default="a_stock",
        help="Decides how the material is charged and what happens to what is left. "
        "Applying one rule to everything overcharges the first job to use a sheet and "
        "undercharges the ones after it.",
    )
    x_spk_offcut_product_id = fields.Many2one(
        "product.product",
        string="Produk Sisa",
        help="Where a reusable remnant lands. A separate product on purpose: a remnant "
        "is not interchangeable with a full sheet, and pretending otherwise makes "
        "availability reports lie.",
    )
    x_spk_offcut_threshold_pct = fields.Float(
        string="Threshold Sisa %",
        default=30.0,
        help="A remnant at or above this share of a full unit is worth keeping. Below "
        "it, the job carries it as waste.",
    )
    x_spk_offcut_valuation_pct = fields.Float(
        string="Valuasi Sisa %",
        default=60.0,
        help="What a remnant is worth against a full unit. Must be a real discount: at "
        "100% the offcut rack becomes a way of moving cost off jobs instead of a stock "
        "of usable material.",
    )
    x_spk_standard_usage = fields.Float(
        string="Standar Pemakaian",
        help="For class B, the quantity charged per unit of output — e.g. kg of paint "
        "per square metre. Nobody is going to weigh the thinner.",
    )

    @api.constrains("x_spk_offcut_threshold_pct", "x_spk_offcut_valuation_pct")
    def _check_offcut_rates(self):
        for rec in self:
            if not 0.0 < rec.x_spk_offcut_threshold_pct < 100.0:
                raise ValidationError(
                    _("An offcut threshold of %(pct)s%% classifies either everything or "
                      "nothing as reusable.", pct=rec.x_spk_offcut_threshold_pct)
                )
            if not 0.0 < rec.x_spk_offcut_valuation_pct <= 100.0:
                raise ValidationError(_("Offcut valuation must be a share of full value."))
            if rec.x_spk_offcut_valuation_pct >= 100.0 and rec.x_spk_offcut_product_id:
                raise ValidationError(
                    _("Valuing a remnant at full price turns the offcut rack into a way "
                      "of moving cost off jobs. Set a real discount.")
                )

    @api.constrains("x_spk_material_class", "x_spk_offcut_product_id")
    def _check_class_consistency(self):
        for rec in self:
            if rec.x_spk_offcut_product_id and rec.x_spk_material_class != "a_stock":
                raise ValidationError(
                    _("%(name)s is not a class A stock item, so it has no remnant to "
                      "return. Only recut material produces reusable offcut.",
                      name=rec.name or "?")
                )
