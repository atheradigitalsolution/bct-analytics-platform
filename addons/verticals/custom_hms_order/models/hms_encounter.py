# -*- coding: utf-8 -*-
"""Orders on the encounter, and the closing rules they impose."""
from odoo import _, api, fields, models


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    order_ids = fields.One2many("hms.order", "encounter_id", "Order Klinis")
    order_line_ids = fields.One2many("hms.order.line", "encounter_id", "Baris Order")
    open_order_count = fields.Integer("Order Terbuka", compute="_compute_open_orders")

    @api.depends("order_line_ids.state")
    def _compute_open_orders(self):
        for enc in self:
            enc.open_order_count = len(
                enc.order_line_ids.filtered(lambda l: l.state in ("ordered", "in_progress"))
            )

    def _closing_blockers(self):
        """Open orders block closing.

        Closing around an unfinished lab test means the result arrives with
        nowhere to land and the charge never reaches the bill — the patient
        goes home having paid for less than they received.
        """
        blockers = super()._closing_blockers()
        if self.open_order_count:
            pending = self.order_line_ids.filtered(
                lambda l: l.state in ("ordered", "in_progress")
            )
            blockers.append(
                _("%(n)s order belum selesai: %(items)s")
                % {"n": len(pending), "items": ", ".join(pending.mapped("name")[:5])}
            )
        return blockers
