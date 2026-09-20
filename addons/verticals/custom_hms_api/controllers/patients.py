# -*- coding: utf-8 -*-
"""Patient search, creation and timeline."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate


def patient_brief(patient):
    return {
        "id": patient.id,
        "mrn": patient.mrn,
        "name": patient.name,
        "nik": patient.nik,
        "birth_date": patient.birth_date,
        "age": patient.age_display,
        "gender": patient.gender,
        "phone": patient.phone,
        "bpjs_no": patient.bpjs_no,
        "has_allergy": patient.has_allergy,
        "payer_id": patient.default_payer_id.id,
        "is_vip": patient.is_vip,
    }


class HmsPatientController(http.Controller):

    @http.route(f"{API_ROOT}/patients", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/patients")
    def search(self, body=None, **kw):
        domain = []
        if kw.get("mrn"):
            domain.append(("mrn", "=", kw["mrn"]))
        if kw.get("nik"):
            domain.append(("nik", "=", kw["nik"]))
        if kw.get("bpjs_no"):
            domain.append(("bpjs_no", "=", kw["bpjs_no"]))
        if kw.get("q"):
            domain += ["|", "|", "|",
                       ("name", "ilike", kw["q"]), ("mrn", "ilike", kw["q"]),
                       ("nik", "ilike", kw["q"]), ("phone", "ilike", kw["q"])]
        if kw.get("birth_date"):
            domain.append(("birth_date", "=", kw["birth_date"]))
        if not domain:
            return error_response(
                "validation_error",
                _("Sebutkan minimal satu kriteria pencarian: no. RM, NIK, nama, "
                  "telepon, atau no. kartu JKN."),
                422,
            )
        records = request.env["hms.patient"].search(domain, limit=200)
        return paginate(
            [patient_brief(p) for p in records],
            page=kw.get("page", 1), page_size=kw.get("page_size", 25),
        )

    @http.route(f"{API_ROOT}/patients", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/patients", methods=("POST",), idempotent=True)
    def create(self, body=None, **kw):
        allowed = {
            "name", "nik", "birth_date", "birth_place", "gender", "phone", "email",
            "address_street", "rt", "rw", "postal_code", "bpjs_no", "identity_type",
            "marital_status", "religion", "occupation", "mother_name", "is_newborn",
            "is_anonymous", "emergency_contact_name", "emergency_contact_relation",
            "emergency_contact_phone", "default_payer_id", "blood_type",
        }
        vals = {k: v for k, v in (body or {}).items() if k in allowed}
        patient = request.env["hms.patient"].create(vals)
        return request.env and {"patient": patient_brief(patient)}

    @http.route(f"{API_ROOT}/patients/<int:patient_id>", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/patients/<id>")
    def read(self, patient_id, body=None, **kw):
        patient = request.env["hms.patient"].browse(patient_id)
        patient.check_access("read")
        data = patient_brief(patient)
        data.update({
            "address": patient.address_street,
            "allergies": [{
                "substance": a.substance, "severity": a.severity, "reaction": a.reaction,
                "type": a.substance_type,
            } for a in patient.allergy_ids],
            "chronic": [{"icd10": c.icd10_id.code, "name": c.icd10_id.display_name}
                        for c in patient.chronic_condition_ids],
            "visit_count": patient.visit_count,
            "last_visit": patient.last_visit_date,
            "deposit_balance": sum(request.env["hms.deposit"].search([
                ("patient_id", "=", patient.id), ("state", "=", "open"),
            ]).mapped("balance")),
        })
        return {"patient": data}

    @http.route(f"{API_ROOT}/patients/<int:patient_id>/timeline", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/patients/<id>/timeline")
    def timeline(self, patient_id, body=None, **kw):
        patient = request.env["hms.patient"].browse(patient_id)
        patient.check_access("read")
        encounters = request.env["hms.encounter"].search(
            [("patient_id", "=", patient_id)], order="arrival_at desc", limit=50
        )
        return {
            "patient": patient_brief(patient),
            "encounters": [{
                "id": e.id, "name": e.name, "type": e.type, "state": e.state,
                "arrival_at": e.arrival_at, "closed_at": e.closed_at,
                "unit": e.unit_id.name, "practitioner": e.practitioner_id.display_name,
                "payer": e.payer_id.name,
                "diagnosis": e.primary_diagnosis_id.display_name or "",
                "notes": len(e.note_ids),
                "orders": len(e.order_line_ids),
            } for e in encounters],
        }
