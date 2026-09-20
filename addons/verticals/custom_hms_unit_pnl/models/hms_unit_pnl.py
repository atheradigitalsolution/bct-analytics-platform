# -*- coding: utf-8 -*-
"""Unit profit and loss, assembled from the records that produced it."""
from odoo import _, api, fields, models

SECTION_LABELS = {
    "administration": "Administrasi",
    "consultation": "Konsultasi & Visite",
    "procedure": "Tindakan",
    "nursing": "Keperawatan",
    "room": "Kamar",
    "medicine": "Obat & BHP",
    "lab": "Laboratorium",
    "radiology": "Radiologi",
    "other": "Lain-lain",
}


class HmsUnitPnl(models.AbstractModel):
    _name = "hms.unit.pnl"
    _description = "Laporan Laba Rugi per Unit"

    @api.model
    def compute(self, period, unit_ids=None):
        """Build the P&L for one month.

        Reads the operational records rather than the general ledger: the
        hospital wants this before the month is closed, and the numbers must
        reconcile to what was actually delivered.
        """
        year, month = (int(p) for p in period.split("-"))
        start = f"{period}-01"
        if month == 12:
            end = f"{year}-12-31"
        else:
            nxt = fields.Date.to_date(f"{year}-{month + 1:02d}-01")
            end = fields.Date.to_string(fields.Date.subtract(nxt, days=1))

        units = self.env["hms.unit"].browse(unit_ids) if unit_ids else \
            self.env["hms.unit"].search([("is_revenue_unit", "=", True)])
        rows = []
        for unit in units:
            lines = self.env["hms.bill.line"].search([
                ("unit_id", "=", unit.id), ("state", "=", "confirmed"),
                ("service_date", ">=", start), ("service_date", "<=", end),
            ])
            revenue_by_section = {}
            for line in lines:
                key = line.report_section or "other"
                revenue_by_section.setdefault(key, 0.0)
                revenue_by_section[key] += line.price_subtotal
            gross = sum(revenue_by_section.values())
            discount = sum(lines.mapped("discount_amount"))
            fees = self.env["hms.medical.fee"].search([
                ("unit_id", "=", unit.id), ("state", "!=", "cancelled"),
                ("date", ">=", start), ("date", "<=", end),
            ])
            medical_fee = sum(fees.mapped("amount"))
            consumable = sum(lines.mapped("amount_consumable"))
            allocation = sum(self.env["account.analytic.line"].search([
                ("account_id", "=", unit.analytic_account_id.id),
                ("hms_allocation_run_id", "!=", False),
                ("date", ">=", start), ("date", "<=", end),
            ]).mapped("amount"))
            visits = self.env["hms.encounter"].search_count([
                ("unit_id", "=", unit.id),
                ("arrival_at", ">=", f"{start} 00:00:00"),
                ("arrival_at", "<=", f"{end} 23:59:59"),
            ])
            net = gross - discount
            contribution = net - consumable - medical_fee
            result = contribution + allocation  # allocation is negative
            rows.append({
                "unit_id": unit.id,
                "unit": unit.name,
                "revenue_gross": gross,
                "revenue_by_section": {
                    SECTION_LABELS.get(k, k): v for k, v in sorted(revenue_by_section.items())
                },
                "discount": discount,
                "revenue_net": net,
                "cogs_consumable": consumable,
                "medical_fee": medical_fee,
                "contribution_margin": contribution,
                "overhead_allocated": allocation,
                "result": result,
                "visits": visits,
                "revenue_per_visit": (net / visits) if visits else 0.0,
                "medical_fee_ratio": (medical_fee / net * 100.0) if net else 0.0,
                "margin_percent": (result / net * 100.0) if net else 0.0,
            })
        rows.sort(key=lambda r: r["result"], reverse=True)
        return {"period": period, "units": rows,
                "total": {
                    "revenue_net": sum(r["revenue_net"] for r in rows),
                    "result": sum(r["result"] for r in rows),
                }}
