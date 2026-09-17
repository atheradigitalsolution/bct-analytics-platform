# -*- coding: utf-8 -*-
"""The fence that a view-level one leaves open.

`standard_price` ships with no restricting group, so any user who can read a
product can read its cost -- through the list view, an export, `read_group`, or
the ORM over JSON-RPC. For a bill-of-quantity business that is most of the way to
the selling price, which is the one thing the Account Executive must not see.

Setting `groups` on the field makes the ORM itself refuse: the field is stripped
from reads for users outside the group and raises on write, so export and API go
the same way as the form.

`list_price` is deliberately left alone. In engineer-to-order work it is not the
quoted price -- the quotation carries that, and the AE has no access to
`sale.order` at all. Gating it would break website and portal flows that legitimately
read it, to close a door that is already shut elsewhere.
"""

from __future__ import annotations

from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    standard_price = fields.Float(groups="custom_spk.group_spk_cost_viewer")


class ProductProduct(models.Model):
    _inherit = "product.product"

    # The variant carries its own copy of the field, so fencing only the template
    # would leave the variant readable -- and the variant is what a stock move and a
    # bill of quantity actually point at.
    standard_price = fields.Float(groups="custom_spk.group_spk_cost_viewer")
