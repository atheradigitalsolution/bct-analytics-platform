# -*- coding: utf-8 -*-
"""Rekam medis — worklist KLPCM dan pelepasan informasi (ROI).

KLPCM sengaja hanya BACA di sini. Modelnya tidak menyediakan "tandai lengkap"
dan alasannya ditulis panjang di `custom_hms_medrec/models/hms_klpcm.py`:
baris tertutup oleh analisis ulang setelah dokumennya benar-benar dilengkapi.
Sebuah endpoint `POST /klpcm/<id>/close` karena itu bukan fitur yang belum
dibuat — ia fitur yang sudah diputuskan tidak boleh ada.
"""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate

ROI_ACTIONS = ("submit", "approve", "reject", "deliver", "cancel")

ROI_WRITABLE = (
    "patient_id", "requester_type", "requester_name", "requester_identity_no",
    "requester_organization", "requester_contact", "purpose", "legal_basis",
    "consent_id", "anonymized", "delivery_channel", "decision_note",
    "receipt_name", "receipt_identity_no", "receipt_note",
)


def _label(record, field_name):
    value = record[field_name]
    if not value:
        return None
    return dict(record._fields[field_name].selection).get(value)


def _m2o(record):
    return {"id": record.id, "name": record.display_name} if record else None


def klpcm_row(row, now):
    overdue_hours = None
    if row.due_at:
        overdue_hours = round((now - row.due_at).total_seconds() / 3600.0, 1)
    return {
        "id": row.id,
        "component": row.component,
        "component_label": _label(row, "component"),
        "kind": row.kind,
        "kind_label": _label(row, "kind"),
        "detail": row.detail,
        "state": row.state,
        "state_label": _label(row, "state"),
        "encounter": {
            "id": row.encounter_id.id,
            "name": row.encounter_id.name,
            "type": row.encounter_id.type,
            "state": row.encounter_id.state,
        },
        "patient": {
            "id": row.patient_id.id,
            "mrn": row.patient_id.mrn,
            "name": row.patient_id.name,
        },
        "unit": _m2o(row.unit_id),
        "responsible": _m2o(row.responsible_id),
        "analyzed_at": row.analyzed_at,
        "due_at": row.due_at,
        "due_hours_applied": row.due_hours_applied,
        "is_overdue": row.is_overdue,
        # Positif = sudah lewat sekian jam; negatif = masih punya sisa waktu.
        "overdue_hours": overdue_hours,
        "auto_detected": row.auto_detected,
        "closed_at": row.closed_at,
    }


def roi_row(req):
    return {
        "id": req.id,
        "name": req.name,
        "state": req.state,
        "state_label": _label(req, "state"),
        "patient": {
            "id": req.patient_id.id,
            "mrn": req.patient_id.mrn,
            "name": req.patient_id.name,
        },
        "requester_type": req.requester_type,
        "requester_type_label": _label(req, "requester_type"),
        "requester_name": req.requester_name,
        "requester_organization": req.requester_organization,
        "requester_contact": req.requester_contact,
        "purpose": req.purpose,
        "legal_basis": req.legal_basis,
        "legal_basis_label": _label(req, "legal_basis"),
        "consent": _m2o(req.consent_id),
        "anonymized": req.anonymized,
        "requested_at": req.requested_at,
        "due_at": req.due_at,
        "approved_at": req.approved_at,
        "approved_by": _m2o(req.approved_by_id),
        "decision_note": req.decision_note,
        "delivery_channel": req.delivery_channel,
        "delivered_at": req.delivered_at,
        "receipt_name": req.receipt_name,
        "document_count": len(req.document_ids),
    }


class HmsMedrecController(http.Controller):

    @http.route(f"{API_ROOT}/medrec/klpcm", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/medrec/klpcm")
    def klpcm(self, body=None, **kw):
        domain = []
        state = kw.get("state") or "open"
        if state != "all":
            domain.append(("state", "=", state))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("component"):
            domain.append(("component", "=", kw["component"]))
        if kw.get("overdue") in ("1", "true", "yes"):
            domain.append(("is_overdue", "=", True))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("encounter_id.name", "ilike", term),
                       ("patient_id.name", "ilike", term),
                       ("patient_id.mrn", "ilike", term)]
        now = fields.Datetime.now()
        rows = request.env["hms.klpcm"].search(domain)
        page = paginate([klpcm_row(r, now) for r in rows],
                        kw.get("page"), kw.get("page_size"))
        page["overdue"] = sum(1 for row in page["items"] if row["is_overdue"])
        return page

    @http.route(f"{API_ROOT}/medrec/roi", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/medrec/roi")
    def roi_list(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("patient_id"):
            domain.append(("patient_id", "=", int(kw["patient_id"])))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("name", "ilike", term),
                       ("requester_name", "ilike", term),
                       ("patient_id.name", "ilike", term)]
        requests = request.env["hms.roi.request"].search(domain)
        return paginate([roi_row(r) for r in requests],
                        kw.get("page"), kw.get("page_size"))

    @http.route(f"{API_ROOT}/medrec/roi", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/medrec/roi", methods=("POST",), idempotent=True)
    def roi_create(self, body=None, **kw):
        body = body or {}
        values = {k: body[k] for k in ROI_WRITABLE if k in body}
        if not values.get("patient_id"):
            return error_response("validation_error", _("Pasien wajib dipilih."), 422)
        values["patient_id"] = int(values["patient_id"])
        if values.get("consent_id"):
            values["consent_id"] = int(values["consent_id"])
        if body.get("encounter_ids"):
            values["encounter_ids"] = [(6, 0, [int(i) for i in body["encounter_ids"]])]
        req = request.env["hms.roi.request"].create(values)
        for doc in body.get("documents") or []:
            request.env["hms.roi.document"].create({
                "request_id": req.id,
                "doc_type": doc.get("doc_type") or "other",
                "description": doc.get("description"),
                "page_count": int(doc.get("page_count") or 0),
            })
        if body.get("submit"):
            req.action_submit()
        return {"request": roi_row(req)}

    @http.route(f"{API_ROOT}/medrec/roi/<int:request_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/medrec/roi/<id>/<action>", methods=("POST",))
    def roi_transition(self, request_id, action, body=None, **kw):
        body = body or {}
        if action not in ROI_ACTIONS:
            return error_response("validation_error",
                                  _("Aksi pelepasan informasi tidak dikenal."), 422)
        req = request.env["hms.roi.request"].browse(request_id)
        if not req.exists():
            return error_response("not_found", _("Permintaan tidak ditemukan."), 404)
        values = {k: v for k, v in (body.get("values") or {}).items() if k in ROI_WRITABLE}
        if values:
            req.write(values)
        getattr(req, f"action_{action}")()
        return {"request": roi_row(req)}
