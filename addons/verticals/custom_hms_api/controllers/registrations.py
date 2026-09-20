# -*- coding: utf-8 -*-
"""Registration — the single-transaction use case."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate
from .patients import patient_brief


def encounter_brief(encounter):
    ticket = encounter.current_ticket_id
    return {
        "id": encounter.id,
        "name": encounter.name,
        "type": encounter.type,
        "state": encounter.state,
        "arrival_at": encounter.arrival_at,
        "unit": {"id": encounter.unit_id.id, "name": encounter.unit_id.name},
        "practitioner": {
            "id": encounter.practitioner_id.id,
            "name": encounter.practitioner_id.display_name,
        },
        "payer": {"id": encounter.payer_id.id, "name": encounter.payer_id.name},
        "triage_level": encounter.triage_level,
        "chief_complaint": encounter.chief_complaint,
        "sep": {"no": encounter.sep_no, "state": encounter.sep_state,
                "error": encounter.sep_error},
        "ticket": {
            "id": ticket.id, "number": ticket.name, "state": ticket.state,
            "position": ticket.position,
        } if ticket else None,
        "patient": patient_brief(encounter.patient_id),
    }


class HmsRegistrationController(http.Controller):

    @http.route(f"{API_ROOT}/registrations", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/registrations", methods=("POST",), idempotent=True)
    def register(self, body=None, **kw):
        """Find or create the patient and open the visit, in one commit."""
        body = body or {}
        Patient = request.env["hms.patient"]
        if body.get("patient_id"):
            patient = Patient.browse(int(body["patient_id"]))
            if not patient.exists():
                return error_response("not_found", _("Pasien tidak ditemukan."), 404)
        elif body.get("new_patient"):
            patient = Patient.create(body["new_patient"])
        else:
            return error_response(
                "validation_error",
                _("Sertakan patient_id untuk pasien lama atau new_patient untuk pasien baru."),
                422,
            )

        referral = False
        if body.get("referral"):
            referral = request.env["hms.referral"].create({
                "name": body["referral"].get("no"),
                "patient_id": patient.id,
                "source_name": body["referral"].get("source") or _("Tidak disebutkan"),
                "source_code": body["referral"].get("ppk_code"),
                "to_unit_id": int(body["unit_id"]),
            })

        encounter = request.env["hms.encounter"].create({
            "patient_id": patient.id,
            "type": body.get("type", "outpatient"),
            "unit_id": int(body["unit_id"]),
            "practitioner_id": int(body["practitioner_id"]) if body.get("practitioner_id") else False,
            "payer_id": int(body["payer_id"]),
            "payer_plan_id": int(body["payer_plan_id"]) if body.get("payer_plan_id") else False,
            "visit_type": body.get("visit_type", "new"),
            "arrival_mode": "referral" if referral else body.get("arrival_mode", "walk_in"),
            "chief_complaint": body.get("chief_complaint"),
            "triage_level": body.get("triage_level"),
            "triage_at": body.get("triage_at"),
            "referral_id": referral.id if referral else False,
            "identity_pending": not patient.nik,
        })
        return {"encounter": encounter_brief(encounter)}

    @http.route(f"{API_ROOT}/registrations", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/registrations")
    def listing(self, body=None, **kw):
        domain = []
        if kw.get("date"):
            domain += [("arrival_at", ">=", f"{kw['date']} 00:00:00"),
                       ("arrival_at", "<=", f"{kw['date']} 23:59:59")]
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("state"):
            domain.append(("state", "=", kw["state"]))
        if kw.get("type"):
            domain.append(("type", "=", kw["type"]))
        records = request.env["hms.encounter"].search(domain, order="arrival_at desc", limit=200)
        return paginate([encounter_brief(e) for e in records],
                        page=kw.get("page", 1), page_size=kw.get("page_size", 25))

    @http.route(f"{API_ROOT}/registrations/<int:encounter_id>/cancel", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/registrations/<id>/cancel", methods=("POST",))
    def cancel(self, encounter_id, body=None, **kw):
        encounter = request.env["hms.encounter"].browse(encounter_id)
        encounter.action_cancel()
        return {"encounter": encounter_brief(encounter)}
