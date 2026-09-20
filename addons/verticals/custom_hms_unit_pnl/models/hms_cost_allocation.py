# -*- coding: utf-8 -*-
"""Overhead allocation driven by measurable activity."""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

DRIVERS = [
    ("area", "Luas Lantai (m²)"),
    ("visits", "Jumlah Kunjungan"),
    ("headcount", "Jumlah Staf"),
    ("patient_days", "Hari Rawat"),
    ("revenue", "Pendapatan"),
    ("manual", "Bobot Manual"),
]


class HmsCostPool(models.Model):
    _name = "hms.cost.pool"
    _description = "Pool Biaya Overhead"
    _order = "name"

    name = fields.Char(required=True)
    analytic_account_id = fields.Many2one(
        "account.analytic.account", "Akun Analitik Sumber",
        help="Akun tempat biaya overhead ini terkumpul sebelum dialokasikan.",
    )
    driver = fields.Selection(DRIVERS, required=True, default="revenue")
    manual_weights = fields.Text(
        "Bobot Manual (JSON)",
        help='Contoh: {"POLI-ANAK": 40, "POLI-PD": 60}. Kunci adalah kode unit.',
    )
    active = fields.Boolean(default=True)

    def driver_values(self, period_start, period_end):
        """Return {unit: weight} for this pool's driver over a period.

        Every driver is measured from data the hospital already records — not
        from a spreadsheet maintained beside the system, which is where
        allocation arguments usually start.
        """
        self.ensure_one()
        units = self.env["hms.unit"].search([
            ("is_revenue_unit", "=", True), ("overhead_pool", "=", False),
        ])
        weights = {}
        if self.driver == "manual":
            raw = json.loads(self.manual_weights or "{}")
            for unit in units:
                weights[unit] = float(raw.get(unit.code, 0.0))
            return weights
        for unit in units:
            if self.driver == "area":
                weights[unit] = unit.area_m2 or 0.0
            elif self.driver == "headcount":
                weights[unit] = float(unit.headcount)
            elif self.driver == "visits":
                weights[unit] = float(self.env["hms.encounter"].search_count([
                    ("unit_id", "=", unit.id),
                    ("arrival_at", ">=", f"{period_start} 00:00:00"),
                    ("arrival_at", "<=", f"{period_end} 23:59:59"),
                ]))
            elif self.driver == "patient_days":
                admissions = self.env["hms.admission"].search([
                    ("ward_id.unit_id", "=", unit.id),
                    ("admitted_at", "<=", f"{period_end} 23:59:59"),
                ])
                weights[unit] = float(sum(admissions.mapped("length_of_stay")))
            elif self.driver == "revenue":
                lines = self.env["hms.bill.line"].search([
                    ("unit_id", "=", unit.id), ("state", "=", "confirmed"),
                    ("service_date", ">=", period_start), ("service_date", "<=", period_end),
                ])
                weights[unit] = sum(lines.mapped("price_subtotal"))
        return weights


class HmsCostAllocationRun(models.Model):
    _name = "hms.cost.allocation.run"
    _description = "Jalankan Alokasi Overhead"
    _order = "period desc"

    name = fields.Char(required=True)
    period = fields.Char("Periode (YYYY-MM)", required=True, index=True)
    pool_ids = fields.Many2many("hms.cost.pool", string="Pool Biaya", required=True)
    amount_by_pool = fields.Text("Nominal per Pool (JSON)", required=True,
                                 help='Contoh: {"Listrik": 50000000}')
    state = fields.Selection(
        [("draft", "Draf"), ("done", "Selesai")], default="draft", required=True,
    )
    analytic_line_ids = fields.One2many(
        "account.analytic.line", "hms_allocation_run_id", "Baris Alokasi", readonly=True,
    )
    run_at = fields.Datetime(readonly=True)
    run_by_id = fields.Many2one("res.users", readonly=True)

    _period_uniq = models.Constraint(
        "unique(period, name)", "Sudah ada jalannya alokasi dengan nama itu di periode ini.",
    )

    def action_run(self):
        """Allocate, replacing any previous result for the same run.

        Re-running is expected: drivers change as the month's data lands. The
        previous analytic lines are deleted first so the result is a
        replacement, never an accumulation.
        """
        self.ensure_one()
        year, month = (int(p) for p in self.period.split("-"))
        period_start = f"{self.period}-01"
        if month == 12:
            period_end = f"{year}-12-31"
        else:
            next_month = fields.Date.to_date(f"{year}-{month + 1:02d}-01")
            period_end = fields.Date.to_string(fields.Date.subtract(next_month, days=1))

        self.analytic_line_ids.unlink()
        amounts = json.loads(self.amount_by_pool or "{}")
        AnalyticLine = self.env["account.analytic.line"]
        created = AnalyticLine
        for pool in self.pool_ids:
            total = float(amounts.get(pool.name, 0.0))
            if not total:
                continue
            weights = pool.driver_values(period_start, period_end)
            weight_sum = sum(weights.values())
            if not weight_sum:
                raise UserError(
                    _("Driver '%(d)s' untuk pool %(p)s bernilai nol pada periode %(per)s; "
                      "alokasi tidak dapat dihitung.")
                    % {"d": dict(DRIVERS).get(pool.driver), "p": pool.name, "per": self.period}
                )
            for unit, weight in weights.items():
                if not weight:
                    continue
                share = total * weight / weight_sum
                created |= AnalyticLine.create({
                    "name": _("Alokasi %(pool)s %(period)s") % {
                        "pool": pool.name, "period": self.period,
                    },
                    "date": period_end,
                    "account_id": unit.sudo()._ensure_analytic().id,
                    "amount": -share,
                    "hms_allocation_run_id": self.id,
                    "hms_cost_pool_id": pool.id,
                })
        self.write({
            "state": "done", "run_at": fields.Datetime.now(), "run_by_id": self.env.uid,
        })
        self.env["hms.event"].emit("pnl.run.done", {
            "run_id": self.id, "period": self.period, "lines": len(created),
        })
        return created


class AccountAnalyticLine(models.Model):
    _inherit = "account.analytic.line"

    hms_allocation_run_id = fields.Many2one(
        "hms.cost.allocation.run", "Jalannya Alokasi SIMRS", index=True, ondelete="cascade",
    )
    hms_cost_pool_id = fields.Many2one("hms.cost.pool", "Pool Biaya", index=True)
