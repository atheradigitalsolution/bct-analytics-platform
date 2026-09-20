# -*- coding: utf-8 -*-
"""Nurse station endpoints."""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


class HmsNursingController(http.Controller):

    @http.route(f"{API_ROOT}/nursing/stations", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/stations")
    def stations(self, body=None, **kw):
        records = request.env["hms.nursing.station"].search([])
        return {"items": [{
            "id": s.id, "code": s.code, "name": s.name, "type": s.type,
            "ward_id": s.ward_id.id, "patients": s.patient_count,
            "overdue_tasks": s.overdue_task_count, "high_ews": s.high_ews_count,
        } for s in records]}

    @http.route(f"{API_ROOT}/nursing/stations/<int:station_id>/board", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/stations/<id>/board")
    def board(self, station_id, body=None, **kw):
        station = request.env["hms.nursing.station"].browse(station_id)
        station.check_access("read")
        return {"station": {"id": station.id, "name": station.name},
                "patients": station.patient_board()}

    @http.route(f"{API_ROOT}/nursing/tasks", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/tasks")
    def tasks(self, body=None, **kw):
        domain = [("state", "in", ("due", "overdue"))]
        if kw.get("station_id"):
            domain.append(("station_id", "=", int(kw["station_id"])))
        if kw.get("admission_id"):
            domain.append(("admission_id", "=", int(kw["admission_id"])))
        records = request.env["hms.nursing.task"].search(domain, order="due_at", limit=200)
        return {"items": [{
            "id": t.id, "due_at": t.due_at, "type": t.type, "title": t.title,
            "detail": t.detail, "state": t.state, "priority": t.priority,
            "patient": {"id": t.patient_id.id, "name": t.patient_id.name,
                        "mrn": t.patient_id.mrn},
            "bed": t.admission_id.bed_id.code,
        } for t in records]}

    @http.route(f"{API_ROOT}/nursing/tasks/<int:task_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/tasks/<id>/<action>", methods=("POST",))
    def task_action(self, task_id, action, body=None, **kw):
        task = request.env["hms.nursing.task"].browse(task_id)
        body = body or {}
        if action == "done":
            task.action_done()
        elif action == "skip":
            task.action_skip(body.get("reason"))
        else:
            return error_response("validation_error", _("Aksi tugas tidak dikenal."), 422)
        return {"task": {"id": task.id, "state": task.state}}

    @http.route(f"{API_ROOT}/nursing/emar", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/emar")
    def emar(self, body=None, **kw):
        domain = [("state", "=", "due")]
        if kw.get("station_id"):
            domain.append(("station_id", "=", int(kw["station_id"])))
        if kw.get("admission_id"):
            domain.append(("admission_id", "=", int(kw["admission_id"])))
        records = request.env["hms.emar.schedule"].search(domain, order="scheduled_at", limit=300)
        return {"items": [{
            "id": s.id,
            "scheduled_at": s.scheduled_at,
            "patient": {"id": s.patient_id.id, "name": s.patient_id.name},
            "bed": s.admission_id.bed_id.code,
            "medicine": s.medicine_id.display_name,
            "dose": s.dose, "dose_unit": s.dose_unit, "route": s.route_id.name,
            "high_alert": s.is_high_alert, "prn": s.is_prn, "state": s.state,
        } for s in records]}

    @http.route(f"{API_ROOT}/nursing/emar/<int:schedule_id>/administer", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/emar/<id>/administer", methods=("POST",), idempotent=True)
    def administer(self, schedule_id, body=None, **kw):
        body = body or {}
        administration = request.env["hms.emar.administration"].create({
            "schedule_id": schedule_id,
            "outcome": body.get("outcome", "given"),
            "witness_id": int(body["witness_id"]) if body.get("witness_id") else False,
            "dose_given": body.get("dose_given"),
            "site": body.get("site"),
            "patient_scanned": body.get("patient_scanned", False),
            "medication_scanned": body.get("medication_scanned", False),
            "reason": body.get("reason"),
            "note": body.get("note"),
        })
        return {"administration": {"id": administration.id,
                                   "schedule_state": administration.schedule_id.state}}

    @http.route(f"{API_ROOT}/nursing/handovers", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/handovers", methods=("POST",))
    def handover(self, body=None, **kw):
        body = body or {}
        admission = request.env["hms.admission"].browse(int(body["admission_id"]))
        handover = request.env["hms.handover"].draft_for(admission)
        return {"handover": {
            "id": handover.id,
            "situation": handover.situation,
            "background": handover.background,
            "assessment": handover.assessment,
            "open_tasks": handover.open_task_summary,
        }}

    @http.route(f"{API_ROOT}/nursing/handovers/<int:handover_id>/sign", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/handovers/<id>/sign", methods=("POST",))
    def sign_handover(self, handover_id, body=None, **kw):
        handover = request.env["hms.handover"].browse(handover_id)
        body = body or {}
        handover.write({
            "recommendation": body.get("recommendation") or handover.recommendation,
            "given_by_id": int(body["given_by_id"]),
            "received_by_id": int(body["received_by_id"]),
        })
        handover.action_sign()
        return {"handover": {"id": handover.id, "signed_at": handover.signed_at}}

    @http.route(f"{API_ROOT}/nursing/requests", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/nursing/requests", methods=("POST",))
    def unit_request(self, body=None, **kw):
        body = body or {}
        record = request.env["hms.unit.request"].create({
            "station_id": int(body["station_id"]),
            "admission_id": int(body["admission_id"]) if body.get("admission_id") else False,
            "to_unit": body["to_unit"],
            "type": body.get("type"),
            "detail": body["detail"],
            "priority": body.get("priority", "normal"),
        })
        return {"request": {"id": record.id, "state": record.state}}
