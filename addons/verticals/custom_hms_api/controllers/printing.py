# -*- coding: utf-8 -*-
"""PDF endpoint — every printed document is a QWeb report in Odoo."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route

# Report key → (report xmlid, model). Kept explicit so the endpoint cannot be
# used to render arbitrary reports for arbitrary records.
REPORTS = {
    "patient_card": ("custom_hms_registration.report_hms_patient_card", "hms.patient"),
    "wristband": ("custom_hms_registration.report_hms_wristband", "hms.encounter"),
    "registration_sheet": ("custom_hms_registration.report_hms_registration_sheet",
                           "hms.encounter"),
    "prescription": ("custom_hms_pharmacy.report_hms_prescription", "hms.prescription"),
    "medicine_label": ("custom_hms_pharmacy.report_hms_medicine_label", "hms.prescription"),
    "lab_result": ("custom_hms_lab.report_hms_lab_result", "hms.order"),
    "rad_report": ("custom_hms_radiology.report_hms_rad_report", "hms.rad.report"),
    "bill_detail": ("custom_hms_billing.report_hms_bill_detail", "hms.bill"),
    "receipt": ("custom_hms_billing.report_hms_receipt", "hms.payment"),
    "summary": ("custom_hms_emr.report_hms_summary", "hms.summary"),
    "consent": ("custom_hms_emr.report_hms_consent", "hms.consent"),
    "queue_ticket": ("custom_hms_qms.report_hms_qms_ticket", "hms.qms.ticket"),
    "cashier_closing": ("custom_hms_cashier.report_hms_cashier_closing", "hms.cashier.session"),
}


class HmsPrintController(http.Controller):

    @http.route(f"{API_ROOT}/print/<string:report_key>/<int:res_id>", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    def print_report(self, report_key, res_id, **kw):
        entry = REPORTS.get(report_key)
        if not entry:
            return request.make_response(
                '{"error": {"code": "not_found", "message": "Laporan tidak dikenal."}}',
                status=404, headers=[("Content-Type", "application/json")],
            )
        from .base import _decode_bearer
        try:
            claims = _decode_bearer()
        except Exception:  # noqa: BLE001 — answered as 401 below
            claims = None
        if not claims:
            return request.make_response(
                '{"error": {"code": "unauthenticated", "message": "Token akses tidak ditemukan."}}',
                status=401, headers=[("Content-Type", "application/json")],
            )
        request.update_env(user=int(claims["sub"]))
        xmlid, model_name = entry
        record = request.env[model_name].browse(res_id)
        if not record.exists():
            return request.make_response(
                '{"error": {"code": "not_found", "message": "Data tidak ditemukan."}}',
                status=404, headers=[("Content-Type", "application/json")],
            )
        # check_access enforces the same record rules the UI does, so the PDF
        # route cannot become a way around EMR access control.
        record.check_access("read")
        if model_name != "hms.patient" and "hms.access.log" in request.env:
            log_target = record if hasattr(record, "_hms_log_access") else None
            if log_target is not None:
                log_target._hms_log_access("print")
        pdf, _content_type = request.env["ir.actions.report"]._render_qweb_pdf(xmlid, [res_id])
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Disposition", f'inline; filename="{report_key}-{res_id}.pdf"'),
            ("Content-Length", str(len(pdf))),
        ])
