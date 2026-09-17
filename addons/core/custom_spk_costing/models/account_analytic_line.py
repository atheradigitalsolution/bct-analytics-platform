# -*- coding: utf-8 -*-
"""Stamp the cost category on the line, instead of inferring it later.

The first version of this module tried to work out what a line was by looking at
which fields happened to be populated. That is guesswork, and guesswork in a cost
report is worse than a gap: it produces a number that looks like an answer.

So the category is written when the line is created. Two rules, no inference:

* a line that carries a product is material — stock valuation is where material cost
  reaches a job, and those lines always have one;
* anything created by this suite's own code sets the field explicitly.

Anything else buckets to ``other``, which the report shows rather than hides.
"""

from __future__ import annotations

from odoo import api, fields, models

COST_CATEGORIES = [
    ("material", "Material"),
    ("labor", "Tenaga Kerja"),
    ("subcon", "Subcon"),
    ("delivery", "Delivery & Instalasi"),
    ("other", "Lain-lain"),
]


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    x_spk_cost_category = fields.Selection(
        COST_CATEGORIES,
        string="Kategori Biaya SPK",
        compute="_compute_spk_cost_category",
        store=True,
        readonly=False,
        index=True,
        help="Which bucket this line reports in. Computed with readonly=False so the "
        "producing code can set it and stock-derived lines still get classified.",
    )

    @api.depends("product_id")
    def _compute_spk_cost_category(self):
        for rec in self:
            if rec.x_spk_cost_category:
                # Already stated by whoever created it; do not overwrite a decision.
                continue
            rec.x_spk_cost_category = "material" if rec.product_id else "other"
