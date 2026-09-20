# -*- coding: utf-8 -*-
"""Laboratory and radiology worklists."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


class HmsDiagnosticController(http.Controller):

    @http.route(f"{API_ROOT}/lab/worklist", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/lab/worklist")
    def lab_worklist(self, body=None, **kw):
        domain = [("state", "in", ("pending", "entered", "validated"))]
        if kw.get("order_id"):
            domain.append(("order_id", "=", int(kw["order_id"])))
        results = request.env["hms.lab.result"].search(domain, order="order_id, parameter_id")
        grouped = {}
        for result in results:
            key = result.order_line_id.id
            grouped.setdefault(key, {
                "order_line_id": key,
                "order": result.order_id.name,
                "exam": result.order_line_id.name,
                "patient": {
                    "id": result.patient_id.id, "mrn": result.patient_id.mrn,
                    "name": result.patient_id.name, "gender": result.patient_id.gender,
                    "age": result.patient_id.age_display,
                },
                "priority": result.order_id.priority,
                "results": [],
            })
            grouped[key]["results"].append({
                "id": result.id,
                "parameter": result.parameter_id.name,
                "code": result.parameter_id.code,
                "value_numeric": result.value_numeric,
                "value_text": result.value_text,
                "uom": result.uom_name,
                "reference": result.ref_display,
                "flag": result.flag,
                "critical": result.is_critical,
                "state": result.state,
            })
        return {"items": list(grouped.values())}

    @http.route(f"{API_ROOT}/lab/results", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/lab/results", methods=("POST",))
    def lab_results(self, body=None, **kw):
        body = body or {}
        Result = request.env["hms.lab.result"]
        updated = Result
        for row in body.get("results", []):
            result = Result.browse(int(row["id"]))
            result.write({
                "value_numeric": row.get("value_numeric"),
                "value_text": row.get("value_text"),
                "note": row.get("note"),
            })
            result.action_enter()
            updated |= result
        return {"items": [{"id": r.id, "flag": r.flag, "critical": r.is_critical,
                           "state": r.state} for r in updated]}

    @http.route(f"{API_ROOT}/lab/results/<string:action>", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/lab/results/<action>", methods=("POST",))
    def lab_transition(self, action, body=None, **kw):
        body = body or {}
        results = request.env["hms.lab.result"].browse(
            [int(i) for i in body.get("ids", [])]
        )
        actions = {"validate": results.action_validate, "verify": results.action_verify,
                   "reject": results.action_reject}
        if action not in actions:
            return error_response("validation_error", _("Aksi hasil lab tidak dikenal."), 422)
        actions[action]()
        return {"items": [{"id": r.id, "state": r.state} for r in results]}

    @http.route(f"{API_ROOT}/radiology/worklist", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/radiology/worklist")
    def rad_worklist(self, body=None, **kw):
        domain = [("state", "in", ("scheduled", "performed", "reported"))]
        records = request.env["hms.rad.report"].search(domain, order="id")
        return {"items": [{
            "id": r.id,
            "exam": r.exam_name,
            "modality": r.modality,
            "body_part": r.body_part,
            "state": r.state,
            "clinical_info": r.clinical_info,
            "is_critical": r.is_critical,
            "patient": {"id": r.patient_id.id, "mrn": r.patient_id.mrn,
                        "name": r.patient_id.name},
        } for r in records]}

    @http.route(f"{API_ROOT}/radiology/<int:report_id>/report", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/radiology/<id>/report", methods=("POST",))
    def rad_report(self, report_id, body=None, **kw):
        report = request.env["hms.rad.report"].browse(report_id)
        body = body or {}
        report.write({
            "technique": body.get("technique"),
            "findings": body.get("findings"),
            "impression": body.get("impression"),
            "suggestion": body.get("suggestion"),
            "is_critical": body.get("is_critical", False),
        })
        if report.state == "scheduled":
            report.action_perform()
        report.action_report()
        if body.get("verify"):
            report.action_verify()
        return {"report": {"id": report.id, "state": report.state}}
