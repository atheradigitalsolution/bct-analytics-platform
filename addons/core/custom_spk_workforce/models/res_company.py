# -*- coding: utf-8 -*-
"""Where a paid shift goes when no job can take it.

A daily worker present with nothing to build is still paid. Pushing that onto
whichever SPK happens to be open makes a job carry cost it did not incur, which is
the same distortion this module exists to remove. So the company names the accounts
that absorb it, and the supervisor picks one.
"""

from __future__ import annotations

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    x_spk_idle_analytic_id = fields.Many2one(
        "account.analytic.account",
        string="Analytic: Idle Workshop",
        help="Present, paid, no work available. The share of shifts landing here is a "
        "planning signal, not an accident to be hidden.",
    )
    x_spk_internal_analytic_id = fields.Many2one(
        "account.analytic.account",
        string="Analytic: Pekerjaan Internal",
        help="Tool maintenance, workshop repairs, housekeeping.",
    )
    x_spk_labor_allocation_method = fields.Selection(
        [
            ("shift_count", "Per jumlah shift (direkomendasikan)"),
            ("direct_cost", "Rata terhadap direct cost"),
        ],
        string="Alokasi Gaji Pekerja Tetap",
        default="shift_count",
        help="Shift count charges each job for the shifts permanent staff actually "
        "worked on it. Spreading over direct cost is cheaper to compute and makes "
        "jobs staffed by permanent workers look more profitable than they were.",
    )


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    x_spk_idle_analytic_id = fields.Many2one(
        related="company_id.x_spk_idle_analytic_id", readonly=False)
    x_spk_internal_analytic_id = fields.Many2one(
        related="company_id.x_spk_internal_analytic_id", readonly=False)
    x_spk_labor_allocation_method = fields.Selection(
        related="company_id.x_spk_labor_allocation_method", readonly=False)
