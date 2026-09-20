# -*- coding: utf-8 -*-
"""Read-mostly reference data the frontline screens cache."""
from odoo import http
from odoo.http import request

from .base import API_ROOT, hms_route


def _simple(records, extra=None):
    out = []
    for record in records:
        row = {"id": record.id, "name": record.display_name}
        for key, getter in (extra or {}).items():
            row[key] = getter(record)
        out.append(row)
    return out


class HmsMasterController(http.Controller):

    @http.route(f"{API_ROOT}/master/units", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/units")
    def units(self, body=None, **kw):
        units = request.env["hms.unit"].search([("active", "=", True)])
        return {"items": [{
            "id": u.id, "code": u.code, "name": u.name, "type": u.type,
            "queue_mode": u.queue_mode, "color": u.color,
            "bpjs_poli_code": u.bpjs_poli_code,
        } for u in units]}

    @http.route(f"{API_ROOT}/master/practitioners", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/practitioners")
    def practitioners(self, body=None, **kw):
        domain = [("state", "=", "active")]
        if kw.get("unit_id"):
            domain.append(("unit_ids", "in", int(kw["unit_id"])))
        if kw.get("type"):
            domain.append(("type", "=", kw["type"]))
        records = request.env["hms.practitioner"].search(domain)
        return {"items": [{
            "id": p.id, "name": p.display_name, "type": p.type,
            "specialty": p.specialty_id.name, "units": p.unit_ids.ids,
            "license_state": p.license_state, "accepts_bpjs": p.accepts_bpjs,
        } for p in records]}

    @http.route(f"{API_ROOT}/master/classes", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/classes")
    def classes(self, body=None, **kw):
        records = request.env["hms.care.class"].search([])
        return {"items": [{"id": c.id, "code": c.code, "name": c.name, "rank": c.rank}
                          for c in records]}

    @http.route(f"{API_ROOT}/master/wards", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/wards")
    def wards(self, body=None, **kw):
        records = request.env["hms.ward"].search([])
        return {"items": [{
            "id": w.id, "code": w.code, "name": w.name, "type": w.type,
            "beds": w.bed_count, "occupied": w.occupied_count, "available": w.available_count,
            "occupancy_rate": w.occupancy_rate,
        } for w in records]}

    @http.route(f"{API_ROOT}/master/beds", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/beds")
    def beds(self, body=None, **kw):
        domain = []
        if kw.get("ward_id"):
            domain.append(("ward_id", "=", int(kw["ward_id"])))
        if kw.get("state"):
            domain.append(("state", "=", kw["state"]))
        records = request.env["hms.bed"].search(domain)
        return {"items": [{
            "id": b.id, "code": b.code, "room": b.room_id.name, "ward_id": b.ward_id.id,
            "class": b.class_id.name, "state": b.state, "bed_type": b.bed_type,
        } for b in records]}

    @http.route(f"{API_ROOT}/master/payers", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/payers")
    def payers(self, body=None, **kw):
        records = request.env["hms.payer"].search([])
        return {"items": [{
            "id": p.id, "code": p.code, "name": p.name, "type": p.type,
            "requires_sep": p.requires_sep,
            "plans": [{"id": pl.id, "name": pl.name, "coverage": pl.coverage_percent,
                       "class_id": pl.class_id.id} for pl in p.plan_ids],
        } for p in records]}

    @http.route(f"{API_ROOT}/master/tariffs", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/tariffs")
    def tariffs(self, body=None, **kw):
        domain = [("active", "=", True)]
        if kw.get("category"):
            domain.append(("category_id.code", "=", kw["category"]))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("q"):
            domain += ["|", ("code", "ilike", kw["q"]), ("name", "ilike", kw["q"])]
        records = request.env["hms.tariff"].search(domain, limit=200)
        return {"items": [{
            "id": t.id, "code": t.code, "name": t.name,
            "category": t.category_id.name, "section": t.report_section,
            "unit_id": t.unit_id.id, "requires_consent": t.requires_consent,
        } for t in records]}

    @http.route(f"{API_ROOT}/master/icd10", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/icd10")
    def icd10(self, body=None, **kw):
        query = kw.get("q") or ""
        domain = ["|", "|", ("code", "ilike", query), ("name_en", "ilike", query),
                  ("name_id", "ilike", query)] if query else []
        records = request.env["hms.icd10"].search(domain, limit=50)
        return {"items": [{"id": i.id, "code": i.code,
                           "name": i.name_id or i.name_en} for i in records]}

    @http.route(f"{API_ROOT}/master/icd9", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/icd9")
    def icd9(self, body=None, **kw):
        query = kw.get("q") or ""
        domain = ["|", ("code", "ilike", query), ("name", "ilike", query)] if query else []
        records = request.env["hms.icd9"].search(domain, limit=50)
        return {"items": [{"id": i.id, "code": i.code, "name": i.name} for i in records]}

    @http.route(f"{API_ROOT}/master/medicines", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/medicines")
    def medicines(self, body=None, **kw):
        query = kw.get("q") or ""
        domain = [("state", "=", "active")]
        if query:
            domain += ["|", ("generic_name", "ilike", query), ("brand_name", "ilike", query)]
        records = request.env["hms.medicine"].search(domain, limit=50)
        return {"items": [{
            "id": m.id, "name": m.display_name, "generic": m.generic_name,
            "form": m.dosage_form_id.name, "strength": m.strength_display,
            "high_alert": m.is_high_alert, "lasa": m.is_lasa,
            "default_sig": m.default_sig,
            "frequency_id": m.default_frequency_id.id,
            "route_ids": m.route_ids.ids,
        } for m in records]}

    @http.route(f"{API_ROOT}/master/frequencies", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/frequencies")
    def frequencies(self, body=None, **kw):
        records = request.env["hms.frequency"].search([])
        return {"items": [{"id": f.id, "code": f.code, "name": f.name,
                           "per_day": f.per_day} for f in records]}

    @http.route(f"{API_ROOT}/master/routes", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/routes")
    def routes(self, body=None, **kw):
        records = request.env["hms.route"].search([])
        return {"items": [{"id": r.id, "code": r.code, "name": r.name} for r in records]}

    @http.route(f"{API_ROOT}/master/settings", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/master/settings")
    def settings(self, body=None, **kw):
        settings = request.env["hms.settings"].get_settings()
        return {
            "hospital_name": settings.hospital_name,
            "hospital_class": settings.hospital_class,
            "address": settings.hospital_address,
            "phone": settings.hospital_phone,
            "name_masking": settings.name_masking,
            "ews_escalate_score": settings.ews_escalate_score,
            "ews_alarm_score": settings.ews_alarm_score,
        }
