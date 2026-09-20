# -*- coding: utf-8 -*-
"""Bills, payments, deposits, cashier shifts."""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


def bill_payload(bill, detail=False):
    data = {
        "id": bill.id,
        "name": bill.name,
        "state": bill.state,
        "encounter_id": bill.encounter_id.id,
        "encounter": bill.encounter_id.name,
        "patient": {"id": bill.patient_id.id, "mrn": bill.patient_id.mrn,
                    "name": bill.patient_id.name},
        "payer": bill.payer_id.name,
        "unit": bill.unit_id.name,
        "amount_gross": bill.amount_gross,
        "amount_discount": bill.amount_discount,
        "amount_total": bill.amount_total,
        "amount_payer": bill.amount_payer,
        "amount_patient": bill.amount_patient,
        "amount_deposit": bill.amount_deposit,
        "amount_paid": bill.amount_paid,
        "amount_due": bill.amount_due,
        "unpriced_lines": bill.unpriced_line_count,
    }
    if detail:
        sections = {}
        for line in bill.line_ids.filtered(lambda l: l.state != "cancelled"):
            key = line.report_section or "other"
            sections.setdefault(key, [])
            sections[key].append({
                "id": line.id,
                "date": line.service_date,
                "name": line.name,
                "qty": line.qty,
                "unit_price": line.unit_price,
                "subtotal": line.price_subtotal,
                "discount": line.discount_amount,
                "payer": line.amount_payer,
                "patient": line.amount_patient,
                "coverage_note": line.coverage_note,
                "price_missing": line.price_missing,
                "unit": line.unit_id.name,
            })
        data["sections"] = sections
        data["payments"] = [{
            "id": p.id, "name": p.name, "method": p.method, "amount": p.amount,
            "paid_at": p.paid_at, "state": p.state, "reference": p.reference,
        } for p in bill.payment_ids]
        data["deposits"] = [{
            "id": d.id, "name": d.name, "amount": d.amount, "used": d.used_amount,
            "balance": d.balance,
        } for d in bill.deposit_ids]
    return data


class HmsBillingController(http.Controller):

    @http.route(f"{API_ROOT}/bills", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills")
    def bills(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "=", kw["state"]))
        if kw.get("patient_id"):
            domain.append(("patient_id", "=", int(kw["patient_id"])))
        if kw.get("due_only"):
            domain.append(("amount_due", ">", 0))
        records = request.env["hms.bill"].search(domain, order="id desc", limit=200)
        return {"items": [bill_payload(b) for b in records]}

    @http.route(f"{API_ROOT}/bills/<int:bill_id>", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills/<id>")
    def read(self, bill_id, body=None, **kw):
        bill = request.env["hms.bill"].browse(bill_id)
        bill.check_access("read")
        return {"bill": bill_payload(bill, detail=True)}

    @http.route(f"{API_ROOT}/bills/<int:bill_id>/open", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills/<id>/open", methods=("POST",))
    def open_bill(self, bill_id, body=None, **kw):
        bill = request.env["hms.bill"].browse(bill_id)
        bill.action_open()
        return {"bill": bill_payload(bill, detail=True)}

    @http.route(f"{API_ROOT}/bills/<int:bill_id>/close", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills/<id>/close", methods=("POST",))
    def close_bill(self, bill_id, body=None, **kw):
        bill = request.env["hms.bill"].browse(bill_id)
        bill.action_close()
        return {"bill": bill_payload(bill, detail=True),
                "moves": bill.move_ids.mapped("name")}

    @http.route(f"{API_ROOT}/bills/<int:bill_id>/payments", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills/<id>/payments", methods=("POST",), idempotent=True)
    def pay(self, bill_id, body=None, **kw):
        bill = request.env["hms.bill"].browse(bill_id)
        body = body or {}
        wizard = request.env["hms.payment.wizard"].create({
            "bill_id": bill.id,
            "use_deposit": body.get("use_deposit", True),
            "line_ids": [(0, 0, {
                "method": line["method"],
                "amount": float(line["amount"]),
                "tendered": float(line.get("tendered") or line["amount"]),
                "reference": line.get("reference"),
                "bank": line.get("bank"),
                "approval_code": line.get("approval_code"),
                "journal_id": int(line["journal_id"]) if line.get("journal_id") else False,
            }) for line in body.get("payments", [])],
        })
        wizard.action_confirm()
        return {"bill": bill_payload(bill, detail=True)}

    @http.route(f"{API_ROOT}/bills/<int:bill_id>/discount", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bills/<id>/discount", methods=("POST",))
    def discount(self, bill_id, body=None, **kw):
        bill = request.env["hms.bill"].browse(bill_id)
        body = body or {}
        percent = float(body.get("percent", 0))
        reason = body.get("reason")
        if body.get("request_authorization"):
            authorization = bill.request_discount_authorization(percent, reason)
            return {"authorization": {"id": authorization.id, "state": authorization.state}}
        bill.apply_discount(percent, reason)
        return {"bill": bill_payload(bill, detail=True)}

    @http.route(f"{API_ROOT}/deposits", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/deposits", methods=("POST",), idempotent=True)
    def deposit(self, body=None, **kw):
        body = body or {}
        deposit = request.env["hms.deposit"].create({
            "patient_id": int(body["patient_id"]),
            "admission_id": int(body["admission_id"]) if body.get("admission_id") else False,
            "amount": float(body["amount"]),
            "method": body.get("method", "cash"),
            "reference": body.get("reference"),
        })
        return {"deposit": {"id": deposit.id, "name": deposit.name,
                            "amount": deposit.amount, "balance": deposit.balance}}

    @http.route(f"{API_ROOT}/cashier/sessions", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/cashier/sessions", methods=("POST",))
    def open_session(self, body=None, **kw):
        body = body or {}
        session = request.env["hms.cashier.session"].create({
            "counter_id": int(body["counter_id"]),
            "opening_cash": float(body.get("opening_cash", 0)),
        })
        return {"session": {"id": session.id, "name": session.name, "state": session.state}}

    @http.route(f"{API_ROOT}/cashier/sessions/<int:session_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/cashier/sessions/<id>/<action>", methods=("POST",))
    def session_action(self, session_id, action, body=None, **kw):
        session = request.env["hms.cashier.session"].browse(session_id)
        body = body or {}
        if action == "closing":
            session.action_start_closing()
        elif action == "count":
            for row in body.get("lines", []):
                line = session.line_ids.filtered(lambda l: l.method == row["method"])
                line.write({"counted_amount": float(row["counted"]), "note": row.get("note")})
        elif action == "close":
            session.action_close()
        else:
            return error_response("validation_error", _("Aksi shift tidak dikenal."), 422)
        return {"session": session.closing_summary()}

    @http.route(f"{API_ROOT}/cashier/estimate", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/cashier/estimate", methods=("POST",))
    def estimate(self, body=None, **kw):
        body = body or {}
        patient = request.env["hms.patient"].browse(int(body["patient_id"]))
        care_class = request.env["hms.care.class"].browse(int(body["class_id"]))
        payer = request.env["hms.payer"].browse(int(body["payer_id"])) \
            if body.get("payer_id") else None
        estimate = request.env["hms.bill.estimate"].estimate(
            patient, care_class, int(body.get("expected_los", 3)), payer=payer,
        )
        return {"estimate": {
            "id": estimate.id, "amount": estimate.estimate_amount,
            "expected_los": estimate.expected_los, "basis": estimate.basis,
        }}
