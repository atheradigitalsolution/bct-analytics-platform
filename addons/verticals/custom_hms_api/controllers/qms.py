# -*- coding: utf-8 -*-
"""Queue endpoints: kiosk, display, counter."""
from odoo import _, fields, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route, json_response


def _kiosk(token):
    kiosk = request.env["hms.qms.kiosk"].sudo().search([("token", "=", token)], limit=1)
    if not kiosk or not kiosk.active:
        return None
    return kiosk


def _agent(token):
    agent = request.env["hms.qms.print.agent"].sudo().search([("token", "=", token)], limit=1)
    return agent if agent and agent.active else None


def _display(token):
    display = request.env["hms.qms.display"].sudo().search([("token", "=", token)], limit=1)
    if not display or not display.active:
        return None
    return display


class HmsQmsController(http.Controller):

    # --- kiosk (device token, no user login) ------------------------------
    @http.route(f"{API_ROOT}/qms/kiosk/<string:token>/menu", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/kiosk/<token>/menu", auth_required=False)
    def kiosk_menu(self, token, body=None, **kw):
        kiosk = _kiosk(token)
        if not kiosk:
            return error_response("not_found", _("Kiosk tidak dikenal."), 404)
        return kiosk.menu_payload()

    @http.route(f"{API_ROOT}/qms/kiosk/<string:token>/tickets", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/kiosk/<token>/tickets", methods=("POST",), auth_required=False)
    def kiosk_ticket(self, token, body=None, **kw):
        kiosk = _kiosk(token)
        if not kiosk:
            return error_response("not_found", _("Kiosk tidak dikenal."), 404)
        body = body or {}
        result = kiosk.sudo().issue_ticket(
            int(body["service_id"]),
            priority=body.get("priority", "none"),
            booking_code=body.get("booking_code"),
        )
        return result

    @http.route(f"{API_ROOT}/qms/kiosk/<string:token>/tickets/<int:ticket_id>/escpos",
                type="http", auth="public", methods=["GET"], csrf=False, save_session=False)
    def kiosk_receipt(self, token, ticket_id, **kw):
        """Raw ESC/POS bytes for the kiosk's own printer.

        Deliberately outside the JSON envelope: the caller pipes these bytes
        straight to a printer, and wrapping them in JSON would mean base64 on
        a device with very little CPU to spare.
        """
        kiosk = _kiosk(token)
        if not kiosk:
            return request.make_response("", status=404)
        ticket = request.env["hms.qms.ticket"].sudo().browse(ticket_id)
        if not ticket.exists():
            return request.make_response("", status=404)
        payload = kiosk.sudo().receipt_bytes(ticket)
        return request.make_response(payload, headers=[
            ("Content-Type", "application/octet-stream"),
            ("Content-Disposition", f'attachment; filename="ticket-{ticket.name}.bin"'),
        ])

    # --- display (device token) -------------------------------------------
    @http.route(f"{API_ROOT}/qms/display/<string:token>/state", type="http", auth="public",
                methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/display/<token>/state", auth_required=False)
    def display_state(self, token, body=None, **kw):
        display = _display(token)
        if not display:
            return error_response("not_found", _("Layar tidak dikenal."), 404)
        return display.sudo().state_payload()

    # --- counters (user session) ------------------------------------------
    @http.route(f"{API_ROOT}/qms/counters", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/counters")
    def counters(self, body=None, **kw):
        domain = []
        if kw.get("service_id"):
            domain.append(("service_ids", "in", int(kw["service_id"])))
        records = request.env["hms.qms.counter"].search(domain)
        return {"items": [_counter_payload(c) for c in records]}

    @http.route(f"{API_ROOT}/qms/counters/<int:counter_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/counters/<id>/<action>", methods=("POST",))
    def counter_action(self, counter_id, action, body=None, **kw):
        counter = request.env["hms.qms.counter"].browse(counter_id)
        actions = {
            "open": counter.action_open,
            "pause": counter.action_pause,
            "close": counter.action_close,
            "next": counter.action_call_next,
            "recall": counter.action_recall,
            "finish": counter.action_finish,
        }
        if action not in actions:
            return error_response("validation_error", _("Aksi loket tidak dikenal."), 422)
        result = actions[action]()
        payload = _counter_payload(counter)
        if action in ("next", "finish") and hasattr(result, "name"):
            payload["ticket"] = _ticket_payload(result)
        return payload

    @http.route(f"{API_ROOT}/qms/tickets/<int:ticket_id>/<string:action>", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/tickets/<id>/<action>", methods=("POST",))
    def ticket_action(self, ticket_id, action, body=None, **kw):
        ticket = request.env["hms.qms.ticket"].browse(ticket_id)
        body = body or {}
        if action == "transfer":
            service = request.env["hms.qms.service"].browse(int(body["service_id"]))
            new_ticket = ticket.action_transfer(service, keep_number=body.get("keep_number"))
            return {"ticket": _ticket_payload(new_ticket)}
        actions = {
            "call": lambda: ticket.action_call(
                request.env["hms.qms.counter"].browse(int(body["counter_id"]))
                if body.get("counter_id") else None
            ),
            "recall": ticket.action_recall,
            "serve": ticket.action_serve,
            "hold": lambda: ticket.action_hold(body.get("reason")),
            "skip": ticket.action_no_show,
            "restore": ticket.action_restore,
            "finish": ticket.action_finish,
            "cancel": ticket.action_cancel,
        }
        if action not in actions:
            return error_response("validation_error", _("Aksi tiket tidak dikenal."), 422)
        actions[action]()
        return {"ticket": _ticket_payload(ticket)}

    @http.route(f"{API_ROOT}/qms/tickets", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/tickets")
    def tickets(self, body=None, **kw):
        today = fields.Date.context_today(request.env["hms.qms.ticket"])
        domain = [("date", "=", kw.get("date") or today)]
        if kw.get("service_id"):
            domain.append(("service_id", "=", int(kw["service_id"])))
        if kw.get("state"):
            domain.append(("state", "=", kw["state"]))
        records = request.env["hms.qms.ticket"].search(domain, order="sequence")
        return {"items": [_ticket_payload(t) for t in records]}

    @http.route(f"{API_ROOT}/qms/stats", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/stats")
    def stats(self, body=None, **kw):
        services = request.env["hms.qms.service"].search([("active", "=", True)])
        return {"items": [{
            "service_id": s.id,
            "code": s.code,
            "name": s.display_label or s.name,
            "waiting": s.waiting_count,
            "serving": s.serving_ticket_id.name if s.serving_ticket_id else None,
            "avg_service_seconds": s.avg_service_seconds,
            "estimated_minutes": s.estimated_wait_minutes(s.waiting_count),
            "sla_minutes": s.sla_minutes,
        } for s in services]}


    # --- print agent (device token) ---------------------------------------
    # The agent runs on a kiosk PC and authenticates with its own token, not a
    # user session: it is a peripheral driver, and it can only see the jobs
    # addressed to the printers it owns.
    @http.route(f"{API_ROOT}/qms/print-agent/<string:token>/heartbeat", type="http",
                auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/print-agent/<token>/heartbeat", methods=("POST",),
               auth_required=False)
    def agent_heartbeat(self, token, body=None, **kw):
        agent = _agent(token)
        if not agent:
            return error_response("not_found", _("Agen cetak tidak dikenal."), 404)
        agent.sudo().heartbeat((body or {}).get("version"))
        return {"ok": True, "agent": agent.name}

    @http.route(f"{API_ROOT}/qms/print-agent/<string:token>/jobs", type="http",
                auth="public", methods=["GET"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/print-agent/<token>/jobs", auth_required=False)
    def agent_jobs(self, token, body=None, **kw):
        agent = _agent(token)
        if not agent:
            return error_response("not_found", _("Agen cetak tidak dikenal."), 404)
        jobs = request.env["hms.qms.print.job"].sudo().search([
            ("agent_id", "=", agent.id), ("state", "=", "pending"),
        ], order="id", limit=10)
        jobs.write({"state": "sent"})
        return {"items": [{
            "id": job.id,
            "printer": job.printer_id.name,
            "payload": job.payload,
        } for job in jobs]}

    @http.route(f"{API_ROOT}/qms/print-agent/<string:token>/jobs/<int:job_id>/ack",
                type="http", auth="public", methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/qms/print-agent/<token>/jobs/<id>/ack", methods=("POST",),
               auth_required=False)
    def agent_ack(self, token, job_id, body=None, **kw):
        agent = _agent(token)
        if not agent:
            return error_response("not_found", _("Agen cetak tidak dikenal."), 404)
        job = request.env["hms.qms.print.job"].sudo().search([
            ("id", "=", job_id), ("agent_id", "=", agent.id),
        ], limit=1)
        if not job:
            return error_response("not_found", _("Job cetak tidak ditemukan."), 404)
        body = body or {}
        job.write({
            "state": "acked" if body.get("ok") else "failed",
            "acked_at": fields.Datetime.now(),
            "error": (body.get("error") or "")[:200] or False,
        })
        return {"ok": True}


def _counter_payload(counter):
    return {
        "id": counter.id,
        "code": counter.code,
        "name": counter.name,
        "location": counter.location,
        "state": counter.state,
        "services": [{"id": s.id, "code": s.code, "name": s.name,
                      "waiting": s.waiting_count} for s in counter.service_ids],
        "current_ticket": _ticket_payload(counter.current_ticket_id)
        if counter.current_ticket_id else None,
        "served_today": counter.served_today,
        "is_clinical": counter.is_clinical,
    }


def _ticket_payload(ticket):
    return {
        "id": ticket.id,
        "number": ticket.name,
        "state": ticket.state,
        "priority": ticket.priority,
        "service": {"id": ticket.service_id.id, "code": ticket.service_id.code,
                    "name": ticket.service_id.display_label or ticket.service_id.name},
        "counter": ticket.counter_id.name or None,
        "patient": ticket._masked_patient_name(),
        "patient_id": ticket.patient_id.id or None,
        "encounter_id": ticket.encounter_id.id or None,
        "position": ticket.position,
        "call_count": ticket.call_count,
        "created_at": ticket.created_at,
        "called_at": ticket.called_at,
    }
