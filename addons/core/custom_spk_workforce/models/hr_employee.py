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

    def spk_missing_shift_rate(self) -> bool:
        """A daily worker with no rate produces attendance that costs nothing.

        This was an @api.constrains on hr.employee, and that was the wrong place. It
        fired on every employee write in every module -- including fixtures in
        custom_hr_payroll_id, which knows nothing about SPK and whose own tests it
        broke. A validation that reaches that far is a validation in the wrong layer.

        The rate matters when a shift is costed, not when a person is hired, so the
        check now lives at attendance approval: that is where the money is, and where
        the person reading the error can actually fix it.
        """
        self.ensure_one()
        return bool(
            self.x_custom_employment_type == "pegawai_tidak_tetap"
            and self.x_spk_shift_rate <= 0
        )
