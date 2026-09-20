# -*- coding: utf-8 -*-
"""Medication orders carry a prescription."""
from odoo import fields, models


class HmsOrder(models.Model):
    _inherit = "hms.order"

    prescription_ids = fields.One2many("hms.prescription", "order_id", "Resep")
    prescription_count = fields.Integer(compute="_compute_prescription_count")

    def _compute_prescription_count(self):
        for order in self:
            order.prescription_count = len(order.prescription_ids)


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    prescription_ids = fields.One2many("hms.prescription", "encounter_id", "Resep")

    def _closing_blockers(self):
        """An undispensed prescription holds the visit open.

        Closing first and dispensing afterwards is how a patient walks out of
        the pharmacy with medicine that was never charged.
        """
        from odoo import _
        blockers = super()._closing_blockers()
        pending = self.prescription_ids.filtered(
            lambda r: r.state in ("draft", "submitted", "verified", "preparing", "ready")
        )
        if pending:
            blockers.append(
                _("%(n)s resep belum diserahkan apotek (%(names)s).")
                % {"n": len(pending), "names": ", ".join(pending.mapped("name"))}
            )
        return blockers
