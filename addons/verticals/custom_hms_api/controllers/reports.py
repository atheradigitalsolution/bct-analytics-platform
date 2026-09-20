# -*- coding: utf-8 -*-
"""Aggregates for dashboards."""
from odoo import fields, http
from odoo.http import request

from .base import API_ROOT, hms_route


class HmsReportController(http.Controller):

    @http.route(f"{API_ROOT}/reports/dashboard", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/reports/dashboard")
    def dashboard(self, body=None, **kw):
        today = fields.Date.context_today(request.env["hms.encounter"])
        Encounter = request.env["hms.encounter"]
        visits_today = Encounter.search_count([
            ("arrival_at", ">=", f"{today} 00:00:00"),
            ("arrival_at", "<=", f"{today} 23:59:59"),
        ])
        emergency_today = Encounter.search_count([
            ("arrival_at", ">=", f"{today} 00:00:00"),
            ("type", "=", "emergency"),
        ])
        wards = request.env["hms.ward"].search([])
        beds_total = sum(wards.mapped("bed_count"))
        beds_occupied = sum(wards.mapped("occupied_count"))
        waiting = sum(request.env["hms.qms.service"].search([
            ("active", "=", True)
        ]).mapped("waiting_count"))
        month_start = today.replace(day=1)
        bill_lines = request.env["hms.bill.line"].search([
            ("state", "=", "confirmed"), ("service_date", ">=", month_start),
        ])
        return {
            "date": today,
            "visits_today": visits_today,
            "emergency_today": emergency_today,
            "beds": {
                "total": beds_total,
                "occupied": beds_occupied,
                "available": sum(wards.mapped("available_count")),
                "bor": round(beds_occupied / beds_total * 100.0, 1) if beds_total else 0.0,
            },
            "queue_waiting": waiting,
            "revenue_mtd": sum(bill_lines.mapped("price_subtotal")),
            "open_bills": request.env["hms.bill"].search_count([("state", "=", "open")]),
            "pending_jobs": request.env["hms.job"].search_count([
                ("state", "in", ("pending", "failed")),
            ]),
            "dead_jobs": request.env["hms.job"].search_count([("state", "=", "dead")]),
        }

    @http.route(f"{API_ROOT}/reports/visits", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/reports/visits")
    def visits(self, body=None, **kw):
        domain = []
        if kw.get("date_from"):
            domain.append(("arrival_at", ">=", f"{kw['date_from']} 00:00:00"))
        if kw.get("date_to"):
            domain.append(("arrival_at", "<=", f"{kw['date_to']} 23:59:59"))
        groups = request.env["hms.encounter"].read_group(
            domain, ["id:count"], ["unit_id", "payer_id"], lazy=False,
        ) if hasattr(request.env["hms.encounter"], "read_group") else []
        return {"items": [{
            "unit": g.get("unit_id") and g["unit_id"][1],
            "payer": g.get("payer_id") and g["payer_id"][1],
            "count": g.get("__count") or g.get("id_count") or 0,
        } for g in groups]}

    @http.route(f"{API_ROOT}/reports/unit-pnl", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/reports/unit-pnl")
    def unit_pnl(self, body=None, **kw):
        period = kw.get("period") or fields.Date.context_today(
            request.env["hms.unit"]
        ).strftime("%Y-%m")
        unit_ids = [int(i) for i in kw["unit_ids"].split(",")] if kw.get("unit_ids") else None
        return request.env["hms.unit.pnl"].compute(period, unit_ids)

    @http.route(f"{API_ROOT}/reports/qms-kpi", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/reports/qms-kpi")
    def qms_kpi(self, body=None, **kw):
        date = kw.get("date") or fields.Date.context_today(request.env["hms.qms.ticket"])
        tickets = request.env["hms.qms.ticket"].search([("date", "=", date)])
        by_service = {}
        for ticket in tickets:
            key = ticket.service_id.code
            row = by_service.setdefault(key, {
                "service": ticket.service_id.name,
                "issued": 0, "served": 0, "no_show": 0,
                "wait_seconds": [], "service_seconds": [],
                "sla_minutes": ticket.service_id.sla_minutes,
            })
            row["issued"] += 1
            if ticket.state == "finished":
                row["served"] += 1
            if ticket.state == "no_show":
                row["no_show"] += 1
            if ticket.wait_seconds:
                row["wait_seconds"].append(ticket.wait_seconds)
            if ticket.service_seconds:
                row["service_seconds"].append(ticket.service_seconds)
        out = []
        for code, row in by_service.items():
            waits = sorted(row.pop("wait_seconds"))
            services = row.pop("service_seconds")
            row.update({
                "code": code,
                "avg_wait_minutes": round(sum(waits) / len(waits) / 60, 1) if waits else 0,
                # p90 rather than max: one patient who wandered off should not
                # define the whole clinic's reported waiting time.
                "p90_wait_minutes": round(
                    waits[int(len(waits) * 0.9) - 1] / 60, 1
                ) if waits else 0,
                "avg_service_minutes": round(
                    sum(services) / len(services) / 60, 1
                ) if services else 0,
                "no_show_rate": round(row["no_show"] / row["issued"] * 100, 1)
                if row["issued"] else 0,
            })
            out.append(row)
        return {"date": date, "items": out}
