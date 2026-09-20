# -*- coding: utf-8 -*-
"""Clinical work on one visit."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route
from .registrations import encounter_brief


class HmsEncounterController(http.Controller):

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>")
    def read(self, encounter_id, body=None, **kw):
        encounter = request.env["hms.encounter"].browse(encounter_id)
        encounter.check_access("read")
        data = encounter_brief(encounter)
        data.update({
            "observations": [{
                "id": o.id, "taken_at": o.taken_at, "systolic": o.systolic,
                "diastolic": o.diastolic, "pulse": o.pulse, "rr": o.respiratory_rate,
                "temperature": o.temperature, "spo2": o.spo2, "pain": o.pain_score,
                "weight": o.weight_kg, "height": o.height_cm, "bmi": o.bmi,
                "ews": o.ews_score_id.score if "ews_score_id" in o._fields and o.ews_score_id else None,
                "ews_level": o.ews_score_id.level if "ews_score_id" in o._fields and o.ews_score_id else None,
            } for o in encounter.observation_ids],
            "notes": [{
                "id": n.id, "noted_at": n.noted_at, "type": n.note_type,
                "author": n.author_id.display_name, "role": n.author_role,
                "subjective": n.subjective, "objective": n.objective,
                "assessment": n.assessment, "plan": n.plan, "instruction": n.instruction,
                "signed": n.signed,
            } for n in encounter.note_ids],
            "diagnoses": [{
                "id": d.id, "code": d.icd10_id.code, "name": d.icd10_id.display_name,
                "rank": d.rank, "stage": d.stage,
            } for d in encounter.diagnosis_ids],
            "orders": [{
                "id": o.id, "name": o.name, "type": o.order_type, "state": o.state,
                "priority": o.priority,
                "lines": [{"id": l.id, "name": l.name, "qty": l.qty, "state": l.state}
                          for l in o.line_ids],
            } for o in encounter.order_ids],
            "prescriptions": [{
                "id": r.id, "name": r.name, "state": r.state, "depot": r.depot_id.name,
                "has_high_alert": r.has_high_alert,
            } for r in encounter.prescription_ids],
            "blockers": encounter._closing_blockers(),
        })
        return {"encounter": data}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/observations", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/observations", methods=("POST",), idempotent=True)
    def add_observation(self, encounter_id, body=None, **kw):
        allowed = {
            "taken_at", "context", "systolic", "diastolic", "pulse", "respiratory_rate",
            "temperature", "spo2", "consciousness", "gcs_eye", "gcs_verbal", "gcs_motor",
            "oxygen_support", "weight_kg", "height_cm", "pain_score", "fall_risk_score", "note",
        }
        vals = {k: v for k, v in (body or {}).items() if k in allowed}
        vals["encounter_id"] = encounter_id
        observation = request.env["hms.observation"].create(vals)
        return {"observation": {
            "id": observation.id,
            "bmi": observation.bmi,
            "ews": observation.ews_score_id.score if observation.ews_score_id else None,
            "ews_level": observation.ews_score_id.level if observation.ews_score_id else None,
        }}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/notes", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/notes", methods=("POST",), idempotent=True)
    def add_note(self, encounter_id, body=None, **kw):
        body = body or {}
        note = request.env["hms.clinical.note"].create({
            "encounter_id": encounter_id,
            "note_type": body.get("note_type", "soap"),
            "author_role": body.get("author_role", "doctor"),
            "subjective": body.get("subjective"),
            "objective": body.get("objective"),
            "assessment": body.get("assessment"),
            "plan": body.get("plan"),
            "instruction": body.get("instruction"),
            "requires_cosign": body.get("requires_cosign", False),
        })
        if body.get("sign"):
            note.action_sign()
        return {"note": {"id": note.id, "signed": note.signed,
                         "signature_hash": note.signature_hash}}

    @http.route(f"{API_ROOT}/notes/<int:note_id>/sign", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/notes/<id>/sign", methods=("POST",))
    def sign_note(self, note_id, body=None, **kw):
        note = request.env["hms.clinical.note"].browse(note_id)
        note.action_sign()
        return {"note": {"id": note.id, "signed": True,
                         "signature_hash": note.signature_hash}}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/diagnoses", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/diagnoses", methods=("POST",))
    def add_diagnosis(self, encounter_id, body=None, **kw):
        body = body or {}
        diagnosis = request.env["hms.diagnosis"].create({
            "encounter_id": encounter_id,
            "icd10_id": int(body["icd10_id"]),
            "rank": body.get("rank", "primary"),
            "stage": body.get("stage", "working"),
            "note": body.get("note"),
        })
        return {"diagnosis": {"id": diagnosis.id, "code": diagnosis.icd10_id.code}}

    @http.route(f"{API_ROOT}/diagnoses/<int:diagnosis_id>", type="http", auth="public",
                methods=["DELETE"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/diagnoses/<id>", methods=("DELETE",))
    def remove_diagnosis(self, diagnosis_id, body=None, **kw):
        request.env["hms.diagnosis"].browse(diagnosis_id).unlink()
        return {"ok": True}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/orders", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/orders", methods=("POST",), idempotent=True)
    def add_order(self, encounter_id, body=None, **kw):
        body = body or {}
        order = request.env["hms.order"].create({
            "encounter_id": encounter_id,
            "order_type": body.get("order_type", "lab"),
            "target_unit_id": int(body["unit_id"]) if body.get("unit_id") else False,
            "priority": body.get("priority", "routine"),
            "clinical_note": body.get("clinical_note"),
            "line_ids": [(0, 0, {
                "tariff_id": int(line["tariff_id"]),
                "qty": line.get("qty", 1),
                "note": line.get("note"),
            }) for line in body.get("lines", [])],
        })
        if body.get("submit", True):
            order.action_submit()
        return {"order": {"id": order.id, "name": order.name, "state": order.state}}

    @http.route(f"{API_ROOT}/orders/<int:line_id>/state", type="http", auth="public",
                methods=["PATCH"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/orders/<id>/state", methods=("PATCH",))
    def order_state(self, line_id, body=None, **kw):
        line = request.env["hms.order.line"].browse(line_id)
        action = (body or {}).get("state")
        mapping = {
            "ordered": line.action_order, "in_progress": line.action_start,
            "done": line.action_done, "cancelled": line.action_cancel,
        }
        if action not in mapping:
            return error_response("validation_error", _("Status order tidak dikenal."), 422)
        mapping[action]()
        return {"line": {"id": line.id, "state": line.state}}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/prescriptions", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/prescriptions", methods=("POST",), idempotent=True)
    def add_prescription(self, encounter_id, body=None, **kw):
        body = body or {}
        prescription = request.env["hms.prescription"].create({
            "encounter_id": encounter_id,
            "practitioner_id": int(body["practitioner_id"]),
            "depot_id": int(body["depot_id"]),
            "type": body.get("type", "outpatient"),
            "is_cito": body.get("is_cito", False),
            "line_ids": [(0, 0, {
                "medicine_id": int(line["medicine_id"]),
                "dose": line.get("dose"),
                "dose_unit": line.get("dose_unit"),
                "frequency_id": int(line["frequency_id"]) if line.get("frequency_id") else False,
                "route_id": int(line["route_id"]) if line.get("route_id") else False,
                "duration_days": line.get("duration_days", 1),
                "qty_prescribed": line.get("qty", 1),
                "sig": line.get("sig"),
                "is_prn": line.get("is_prn", False),
            }) for line in body.get("lines", [])],
        })
        warning = prescription.allergy_warning
        if body.get("submit", True):
            prescription.action_submit()
        return {"prescription": {
            "id": prescription.id, "name": prescription.name, "state": prescription.state,
            "allergy_warning": warning,
        }}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/close", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/close", methods=("POST",))
    def close(self, encounter_id, body=None, **kw):
        encounter = request.env["hms.encounter"].browse(encounter_id)
        blockers = encounter._closing_blockers()
        if blockers:
            return error_response(
                "encounter_blocked", _("Kunjungan belum dapat ditutup."), 409,
                fields_={"blockers": blockers},
            )
        encounter.action_close()
        return {"encounter": encounter_brief(encounter)}

    @http.route(f"{API_ROOT}/encounters/<int:encounter_id>/summary", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/encounters/<id>/summary", methods=("POST",))
    def summary(self, encounter_id, body=None, **kw):
        encounter = request.env["hms.encounter"].browse(encounter_id)
        summary_type = "discharge" if encounter.type == "inpatient" else "outpatient"
        summary = request.env["hms.summary"].generate_for(encounter, summary_type)
        return {"summary": {
            "id": summary.id, "type": summary.type, "state": summary.state,
            "diagnosis": summary.diagnosis_primary_id.display_name,
            "history": summary.history, "treatment": summary.treatment,
        }}
