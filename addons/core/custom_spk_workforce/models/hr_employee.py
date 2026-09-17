# -*- coding: utf-8 -*-
"""Two dimensions the classification needs, and one it already has.

``x_custom_employment_type`` (pegawai tetap / tidak tetap / bukan pegawai) is NOT
redefined here. It lives in ``custom_hr_payroll_id`` and PPh 21 is computed from
it; a second field would be two answers to one question, and costing would follow
whichever was stale.

What is missing is the orthogonal axis. Permanent-vs-daily says how someone is
paid; direct-vs-indirect says whether their time belongs to a job at all. A
supervisor is usually permanent AND indirect, so their cost is overhead. A welder
may be permanent and direct, and still has to reach COGS.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    x_spk_labor_category = fields.Selection(
        [
            ("direct", "Direct (produksi)"),
            ("indirect", "Indirect (supervisi / support)"),
        ],
        string="Kategori Tenaga Kerja",
        default="direct",
        tracking=True,
        help="Direct labour is charged to a job. Indirect labour is overhead and is "
        "never allocated per SPK, however many shifts it works.",
    )
    x_spk_shift_rate = fields.Monetary(
        string="Tarif per Shift",
        currency_field="x_spk_currency_id",
        groups="custom_spk.group_spk_cost_viewer",
        help="What one shift pays a daily worker, before the shift multiplier. "
        "Meaningless for a permanent employee, whose salary is monthly.",
    )
    x_spk_currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        groups="custom_spk.group_spk_cost_viewer",
    )
    x_spk_is_daily = fields.Boolean(
        string="Pekerja Harian",
        compute="_compute_spk_is_daily",
        store=True,
        help="Derived from the payroll classification so there is one source of truth. "
        "Stored because attendance and work logs filter on it constantly.",
    )

    @api.depends("x_custom_employment_type")
    def _compute_spk_is_daily(self):
        for rec in self:
            rec.x_spk_is_daily = rec.x_custom_employment_type == "pegawai_tidak_tetap"

    @api.constrains("x_custom_employment_type", "x_spk_shift_rate")
    def _check_daily_has_a_rate(self):
        """A daily worker with no rate produces attendance that costs nothing.

        Caught here rather than at payroll time, because by then the shifts have
        already been worked and the week is being paid.
        """
        for rec in self:
            if rec.x_custom_employment_type == "pegawai_tidak_tetap" and rec.x_spk_shift_rate <= 0:
                raise ValidationError(
                    _("%(name)s is a daily worker, so a shift rate is required — "
                      "without it every shift they work costs nothing and the job "
                      "looks cheaper than it was.", name=rec.name or "?")
                )
