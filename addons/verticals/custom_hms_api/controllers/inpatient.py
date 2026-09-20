# -*- coding: utf-8 -*-
"""Bed board, admission, transfer, discharge."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


def admission_payload(admission):
    return {
        "id": admission.id,
        "name": admission.name,
        "state": admission.state,
        "admitted_at": admission.admitted_at,
        "discharged_at": admission.discharged_at,
        "length_of_stay": admission.length_of_stay,
        "ward": {"id": admission.ward_id.id, "name": admission.ward_id.name},
        "room": admission.room_id.name,
        "bed": {"id": admission.bed_id.id, "code": admission.bed_id.code},
        "class": admission.class_id.name,
        "entitled_class": admission.entitled_class_id.name,
        "dpjp": admission.dpjp_id.display_name,
        "diet": admission.diet,
        "is_isolation": admission.is_isolation,
        "patient": {
            "id": admission.patient_id.id,
            "mrn": admission.patient_id.mrn,
            "name": admission.patient_id.name,
            "age": admission.patient_id.age_display,
            "gender": admission.patient_id.gender,
            "has_allergy": admission.patient_id.has_allergy,
        },
        "encounter_id": admission.encounter_id.id,
    }


class HmsInpatientController(http.Controller):

    @http.route(f"{API_ROOT}/inpatient/bedboard", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/bedboard")
    def bedboard(self, body=None, **kw):
        domain = []
        if kw.get("ward_id"):
            domain.append(("id", "=", int(kw["ward_id"])))
        wards = request.env["hms.ward"].search(domain)
        out = []
        for ward in wards:
            beds = []
            for bed in ward.bed_ids.filtered("active").sorted("code"):
                admission = request.env["hms.admission"].search([
                    ("bed_id", "=", bed.id), ("state", "in", ("admitted", "discharge_planned")),
                ], limit=1)
                beds.append({
                    "id": bed.id,
                    "code": bed.code,
                    "room": bed.room_id.name,
                    "class": bed.class_id.name,
                    "state": bed.state,
                    "bed_type": bed.bed_type,
                    "admission": admission_payload(admission) if admission else None,
                })
            out.append({
                "ward_id": ward.id,
                "ward": ward.name,
                "type": ward.type,
                "beds": beds,
                "stats": {
                    "total": ward.bed_count,
                    "occupied": ward.occupied_count,
                    "available": ward.available_count,
                    "occupancy_rate": ward.occupancy_rate,
                },
            })
        return {"wards": out}

    @http.route(f"{API_ROOT}/inpatient/admissions", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/admissions", methods=("POST",), idempotent=True)
    def admit(self, body=None, **kw):
        body = body or {}
        encounter = request.env["hms.encounter"].browse(int(body["encounter_id"]))
        bed = request.env["hms.bed"].browse(int(body["bed_id"]))
        dpjp = request.env["hms.practitioner"].browse(int(body["dpjp_id"]))
        entitled = request.env["hms.care.class"].browse(int(body["entitled_class_id"])) \
            if body.get("entitled_class_id") else None
        admission = request.env["hms.admission"].admit(
            encounter, bed, dpjp, entitled_class=entitled, source=body.get("source", "emergency"),
        )
        if body.get("deposit"):
            request.env["hms.deposit"].create({
                "patient_id": encounter.patient_id.id,
                "admission_id": admission.id,
                "amount": float(body["deposit"]),
                "method": body.get("deposit_method", "cash"),
            })
        return {"admission": admission_payload(admission)}

    @http.route(f"{API_ROOT}/inpatient/<int:admission_id>/transfer", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/<id>/transfer", methods=("POST",))
    def transfer(self, admission_id, body=None, **kw):
        admission = request.env["hms.admission"].browse(admission_id)
        body = body or {}
        bed = request.env["hms.bed"].browse(int(body["bed_id"]))
        admission.action_transfer(bed, reason=body.get("reason", "transfer_medical"))
        return {"admission": admission_payload(admission)}

    @http.route(f"{API_ROOT}/inpatient/<int:admission_id>/discharge-check", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/<id>/discharge-check")
    def discharge_check(self, admission_id, body=None, **kw):
        admission = request.env["hms.admission"].browse(admission_id)
        blockers = admission.discharge_check()
        return {"can_discharge": not blockers, "blockers": blockers}

    @http.route(f"{API_ROOT}/inpatient/<int:admission_id>/discharge", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/<id>/discharge", methods=("POST",))
    def discharge(self, admission_id, body=None, **kw):
        admission = request.env["hms.admission"].browse(admission_id)
        body = body or {}
        if body.get("disposition"):
            admission.write({"discharge_disposition": body["disposition"]})
        blockers = admission.discharge_check()
        if blockers and not body.get("force"):
            return error_response(
                "discharge_blocked", _("Pasien belum dapat dipulangkan."), 409,
                fields_={"blockers": blockers},
            )
        admission.action_discharge(force=bool(body.get("force")))
        return {"admission": admission_payload(admission)}

    @http.route(f"{API_ROOT}/beds/<int:bed_id>/status", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/beds/<id>/status", methods=("POST",))
    def bed_status(self, bed_id, body=None, **kw):
        bed = request.env["hms.bed"].browse(bed_id)
        state = (body or {}).get("state")
        actions = {
            "cleaning": bed.action_start_cleaning,
            "vacant": bed.action_set_vacant,
            "maintenance": bed.action_set_maintenance,
        }
        if state not in actions:
            return error_response("validation_error", _("Status bed tidak dikenal."), 422)
        actions[state]()
        return {"bed": {"id": bed.id, "code": bed.code, "state": bed.state}}

    @http.route(f"{API_ROOT}/inpatient/census", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/inpatient/census")
    def census(self, body=None, **kw):
        return request.env["hms.admission"].census(kw.get("date"))
