# -*- coding: utf-8 -*-
"""Keselamatan pasien — laporan insiden (IKP) dan komplain.

=============================================================================
BATAS AKSES TIDAK DITULIS ULANG DI SINI
=============================================================================

Seorang perawat hanya boleh melihat laporannya sendiri; tim KP melihat
semuanya. Godaannya menulis `domain.append(("create_uid", "=", uid))` di
controller ketika pengguna bukan anggota tim KP. Itu salah dua kali: ia
menduplikasi `custom_hms_safety/security/hms_safety_rules.xml`, dan ia
membuat batas kerahasiaan bergantung pada controller yang kebetulan ingat
memasangnya — sebuah endpoint baru yang lupa akan membocorkan seluruh
laporan tanpa satu pun tes yang gagal.

Jadi di sini tidak ada filter pemilik sama sekali. `search()` berjalan
sebagai pengguna sungguhan dan record rule Odoo yang memutuskan; kalau
aturannya keliru, ia keliru di satu tempat. `scope` di respons hanya
memberi tahu layar apa yang sedang ia lihat, bukan menentukannya.

Laporan anonim tidak pernah membawa identitas pelapor ke luar: model menolak
menyimpan `reporter_id` bila `is_anonymous`, dan serialisasi di bawah memakai
`reporter_display` yang sudah memperhitungkannya.
"""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, paginate

INCIDENT_ACTIONS = ("report", "start_investigation", "grade", "close")
COMPLAINT_ACTIONS = ("receive", "start", "respond", "close")

INCIDENT_WRITABLE = (
    "is_anonymous", "reporter_id", "reporter_unit_id", "unit_id", "location_detail",
    "occurred_at", "incident_type", "category", "chronology", "immediate_action",
    "patient_id", "encounter_id", "patient_harmed", "witness_names",
    "grade", "root_cause", "recommendation", "closure_note",
)

COMPLAINT_WRITABLE = (
    "patient_id", "encounter_id", "complainant_name", "complainant_relation",
    "contact", "channel", "category", "unit_id", "subject", "detail", "grade",
    "received_at", "response", "corrective_action", "outcome",
)

_INT_FIELDS = ("reporter_id", "reporter_unit_id", "unit_id", "patient_id", "encounter_id")


def _label(record, field_name):
    value = record[field_name]
    if not value:
        return None
    return dict(record._fields[field_name].selection).get(value)


def _m2o(record):
    return {"id": record.id, "name": record.display_name} if record else None


def _coerce(values):
    for key in _INT_FIELDS:
        if key in values:
            values[key] = int(values[key]) if values[key] else False
    return values


def incident_row(rec):
    return {
        "id": rec.id,
        "name": rec.name,
        "state": rec.state,
        "state_label": _label(rec, "state"),
        "is_anonymous": rec.is_anonymous,
        # Kolom compute milik model; controller tidak pernah menyentuh
        # reporter_id sendiri supaya anonimitas tidak bocor lewat jalur ini.
        "reporter_display": rec.reporter_display,
        "reporter_unit": _m2o(rec.reporter_unit_id),
        "unit": _m2o(rec.unit_id),
        "location_detail": rec.location_detail,
        "occurred_at": rec.occurred_at,
        "reported_at": rec.reported_at,
        "due_at": rec.due_at,
        "is_late": rec.is_late,
        "late_hours": rec.late_hours,
        "incident_type": rec.incident_type,
        "incident_type_label": _label(rec, "incident_type"),
        "category": rec.category,
        "category_label": _label(rec, "category"),
        "chronology": rec.chronology,
        "immediate_action": rec.immediate_action,
        "patient_harmed": rec.patient_harmed,
        "patient": {
            "id": rec.patient_id.id, "mrn": rec.patient_id.mrn, "name": rec.patient_id.name,
        } if rec.patient_id else None,
        "grade": rec.grade,
        "grade_label": _label(rec, "grade"),
        "investigation_method": rec.investigation_method,
        "investigation_method_label": _label(rec, "investigation_method"),
        "root_cause": rec.root_cause,
        "recommendation": rec.recommendation,
        "investigator": _m2o(rec.investigator_id),
        "closed_at": rec.closed_at,
    }


def complaint_row(rec):
    return {
        "id": rec.id,
        "name": rec.name,
        "state": rec.state,
        "state_label": _label(rec, "state"),
        "complainant_name": rec.complainant_name,
        "complainant_relation": rec.complainant_relation,
        "complainant_relation_label": _label(rec, "complainant_relation"),
        "contact": rec.contact,
        "channel": rec.channel,
        "channel_label": _label(rec, "channel"),
        "category": rec.category,
        "category_label": _label(rec, "category"),
        "unit": _m2o(rec.unit_id),
        "subject": rec.subject,
        "detail": rec.detail,
        "grade": rec.grade,
        "grade_label": _label(rec, "grade"),
        "patient": {
            "id": rec.patient_id.id, "mrn": rec.patient_id.mrn, "name": rec.patient_id.name,
        } if rec.patient_id else None,
        "received_at": rec.received_at,
        "target_hours": rec.target_hours,
        "due_at": rec.due_at,
        "responded_at": rec.responded_at,
        "response_hours": rec.response_hours,
        "is_on_time": rec.is_on_time,
        "response": rec.response,
        "corrective_action": rec.corrective_action,
        "outcome": rec.outcome,
        "outcome_label": _label(rec, "outcome"),
        "handler": _m2o(rec.handler_id),
        "closed_at": rec.closed_at,
    }


def _scope():
    """Apa yang pengguna ini sedang lihat — untuk kalimat di layar, bukan filter."""
    return "team" if request.env.user.has_group(
        "custom_hms_safety.group_hms_patient_safety"
    ) else "own"


class HmsSafetyController(http.Controller):

    # ------------------------------------------------------------------
    # IKP
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/safety/incidents", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/incidents")
    def incidents(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("incident_type"):
            domain.append(("incident_type", "=", kw["incident_type"]))
        if kw.get("grade"):
            domain.append(("grade", "=", kw["grade"]))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", ("name", "ilike", term), ("chronology", "ilike", term)]
        records = request.env["hms.incident.report"].search(domain)
        page = paginate([incident_row(r) for r in records],
                        kw.get("page"), kw.get("page_size"))
        page["scope"] = _scope()
        page["late"] = sum(1 for row in page["items"] if row["is_late"])
        return page

    @http.route(f"{API_ROOT}/safety/incidents", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/incidents", methods=("POST",), idempotent=True)
    def incident_create(self, body=None, **kw):
        body = body or {}
        values = _coerce({k: body[k] for k in INCIDENT_WRITABLE if k in body})
        if not values.get("unit_id"):
            return error_response("validation_error",
                                  _("Unit tempat kejadian wajib dipilih."), 422)
        record = request.env["hms.incident.report"].create(values)
        if body.get("report"):
            record.action_report()
        return {"incident": incident_row(record)}

    @http.route(f"{API_ROOT}/safety/incidents/<int:incident_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/incidents/<id>/<action>", methods=("POST",))
    def incident_transition(self, incident_id, action, body=None, **kw):
        body = body or {}
        if action not in INCIDENT_ACTIONS:
            return error_response("validation_error", _("Aksi IKP tidak dikenal."), 422)
        record = request.env["hms.incident.report"].browse(incident_id)
        if not record.exists():
            return error_response("not_found", _("Laporan tidak ditemukan."), 404)
        values = _coerce({k: v for k, v in (body.get("values") or {}).items()
                          if k in INCIDENT_WRITABLE})
        if values:
            record.write(values)
        getattr(record, f"action_{action}")()
        return {"incident": incident_row(record)}

    # ------------------------------------------------------------------
    # Komplain
    # ------------------------------------------------------------------
    @http.route(f"{API_ROOT}/safety/complaints", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/complaints")
    def complaints(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "in", kw["state"].split(",")))
        if kw.get("grade"):
            domain.append(("grade", "=", kw["grade"]))
        if kw.get("category"):
            domain.append(("category", "=", kw["category"]))
        if kw.get("unit_id"):
            domain.append(("unit_id", "=", int(kw["unit_id"])))
        if kw.get("q"):
            term = kw["q"]
            domain += ["|", "|",
                       ("name", "ilike", term),
                       ("subject", "ilike", term),
                       ("complainant_name", "ilike", term)]
        records = request.env["hms.complaint"].search(domain)
        page = paginate([complaint_row(r) for r in records],
                        kw.get("page"), kw.get("page_size"))
        page["scope"] = _scope()
        return page

    @http.route(f"{API_ROOT}/safety/complaints", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/complaints", methods=("POST",), idempotent=True)
    def complaint_create(self, body=None, **kw):
        body = body or {}
        values = _coerce({k: body[k] for k in COMPLAINT_WRITABLE if k in body})
        if not values.get("subject"):
            return error_response("validation_error", _("Pokok komplain wajib diisi."), 422)
        if not values.get("complainant_name"):
            return error_response("validation_error", _("Nama pelapor wajib diisi."), 422)
        record = request.env["hms.complaint"].create(values)
        if body.get("receive"):
            record.action_receive()
        return {"complaint": complaint_row(record)}

    @http.route(f"{API_ROOT}/safety/complaints/<int:complaint_id>/<string:action>",
                type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/safety/complaints/<id>/<action>", methods=("POST",))
    def complaint_transition(self, complaint_id, action, body=None, **kw):
        body = body or {}
        if action not in COMPLAINT_ACTIONS:
            return error_response("validation_error", _("Aksi komplain tidak dikenal."), 422)
        record = request.env["hms.complaint"].browse(complaint_id)
        if not record.exists():
            return error_response("not_found", _("Komplain tidak ditemukan."), 404)
        values = _coerce({k: v for k, v in (body.get("values") or {}).items()
                          if k in COMPLAINT_WRITABLE})
        if values:
            record.write(values)
        getattr(record, f"action_{action}")()
        return {"complaint": complaint_row(record)}
