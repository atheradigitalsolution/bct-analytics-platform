# -*- coding: utf-8 -*-
"""Pharmacy queue and dispensing."""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


def prescription_payload(rx, detail=False):
    data = {
        "id": rx.id,
        "name": rx.name,
        "state": rx.state,
        "type": rx.type,
        "is_cito": rx.is_cito,
        "has_high_alert": rx.has_high_alert,
        "has_narcotic": rx.has_narcotic,
        "waiting_minutes": rx.waiting_minutes,
        "depot": {"id": rx.depot_id.id, "name": rx.depot_id.name},
        "prescriber": rx.practitioner_id.display_name,
        "patient": {"id": rx.patient_id.id, "mrn": rx.patient_id.mrn, "name": rx.patient_id.name},
        "encounter_id": rx.encounter_id.id,
    }
    if detail:
        data.update({
            "allergy_warning": rx.allergy_warning,
            "lines": [{
                "id": l.id,
                "medicine": l.medicine_id.display_name,
                "medicine_id": l.medicine_id.id,
                "high_alert": l.medicine_id.is_high_alert,
                "dose": l.dose, "dose_unit": l.dose_unit,
                "frequency": l.frequency_id.name, "route": l.route_id.name,
                "duration_days": l.duration_days,
                "qty_prescribed": l.qty_prescribed, "qty_dispense": l.qty_dispense,
                "sig": l.sig, "state": l.state,
            } for l in rx.line_ids],
            "verified_by": rx.verified_by_id.display_name,
            "dispensed_by": rx.dispensed_by_id.display_name,
        })
    return data


class HmsPharmacyController(http.Controller):

    @http.route(f"{API_ROOT}/pharmacy/queue", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/pharmacy/queue")
    def queue(self, body=None, **kw):
        domain = [("state", "in", ("submitted", "verified", "preparing", "ready"))]
        if kw.get("depot_id"):
            domain.append(("depot_id", "=", int(kw["depot_id"])))
        records = request.env["hms.prescription"].search(
            domain, order="is_cito desc, prescribed_at"
        )
        return {"items": [prescription_payload(r) for r in records]}

    @http.route(f"{API_ROOT}/pharmacy/prescriptions/<int:rx_id>", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/pharmacy/prescriptions/<id>")
    def read(self, rx_id, body=None, **kw):
        rx = request.env["hms.prescription"].browse(rx_id)
        rx.check_access("read")
        return {"prescription": prescription_payload(rx, detail=True)}

    @http.route(f"{API_ROOT}/pharmacy/prescriptions/<int:rx_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/pharmacy/prescriptions/<id>/<action>", methods=("POST",),
               idempotent=True)
    def act(self, rx_id, action, body=None, **kw):
        rx = request.env["hms.prescription"].browse(rx_id)
        body = body or {}
        if action == "dispense":
            if body.get("witness_id"):
                rx.write({"witness_id": int(body["witness_id"])})
            if body.get("received_by"):
                rx.write({"received_by": body["received_by"]})
        if action == "reject":
            rx.write({"reject_reason": body.get("reason")})
        actions = {
            "verify": rx.action_verify, "prepare": rx.action_prepare,
            "ready": rx.action_ready, "dispense": rx.action_dispense,
            "reject": rx.action_reject, "cancel": rx.action_cancel,
        }
        if action not in actions:
            return error_response("validation_error", _("Aksi resep tidak dikenal."), 422)
        actions[action]()
        return {"prescription": prescription_payload(rx, detail=True)}

    @http.route(f"{API_ROOT}/pharmacy/stock", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/pharmacy/stock")
    def stock(self, body=None, **kw):
        domain = [("quantity", ">", 0)]
        if kw.get("product_id"):
            domain.append(("product_id", "=", int(kw["product_id"])))
        if kw.get("location_id"):
            domain.append(("location_id", "child_of", int(kw["location_id"])))
        quants = request.env["stock.quant"].search(domain, limit=200)
        return {"items": [{
            "product_id": q.product_id.id,
            "product": q.product_id.display_name,
            "location": q.location_id.display_name,
            "lot": q.lot_id.name,
            "expiration_date": q.expiration_date,
            "quantity": q.quantity,
            "available": q.available_quantity,
        } for q in quants]}
