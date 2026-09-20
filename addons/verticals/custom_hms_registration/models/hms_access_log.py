# -*- coding: utf-8 -*-
"""Adds the encounter link to the audit trail.

The field lives here rather than in custom_hms_audit because hms.encounter is
introduced by this module; hms_audit sits below it and must stay installable
on its own.
"""
from odoo import fields, models


class HmsAccessLog(models.Model):
    _inherit = "hms.access.log"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", index=True, ondelete="set null")
