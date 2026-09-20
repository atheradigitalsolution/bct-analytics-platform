# -*- coding: utf-8 -*-
"""Integration job monitor."""
from odoo import _, http
from odoo.http import request

from .base import API_ROOT, error_response, hms_route


class HmsBridgingController(http.Controller):

    @http.route(f"{API_ROOT}/bridging/jobs", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bridging/jobs")
    def jobs(self, body=None, **kw):
        domain = []
        if kw.get("state"):
            domain.append(("state", "=", kw["state"]))
        if kw.get("name"):
            domain.append(("name", "like", kw["name"]))
        records = request.env["hms.job"].search(domain, order="id desc", limit=200)
        return {"items": [{
            "id": j.id, "name": j.name, "state": j.state, "attempts": j.attempts,
            "max_attempts": j.max_attempts, "next_run": j.next_run,
            "created": j.create_date, "duration_ms": j.duration_ms,
            "last_error": j.last_error, "model": j.model_name, "res_id": j.res_id,
        } for j in records]}

    @http.route(f"{API_ROOT}/bridging/jobs/<int:job_id>/retry", type="http", auth="public",
                methods=["POST"], csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bridging/jobs/<id>/retry", methods=("POST",))
    def retry(self, job_id, body=None, **kw):
        job = request.env["hms.job"].browse(job_id)
        job.action_retry()
        return {"job": {"id": job.id, "state": job.state}}

    @http.route(f"{API_ROOT}/bridging/logs", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/bridging/logs")
    def logs(self, body=None, **kw):
        domain = []
        if kw.get("service"):
            domain.append(("service", "=", kw["service"]))
        if kw.get("job_id"):
            domain.append(("job_id", "=", int(kw["job_id"])))
        records = request.env["hms.bridging.log"].search(domain, order="id desc", limit=100)
        return {"items": [{
            "id": l.id, "called_at": l.called_at, "service": l.service,
            "endpoint": l.endpoint, "method": l.method, "status": l.response_code,
            "duration_ms": l.duration_ms, "is_mock": l.is_mock, "error": l.error,
            "request": l.request_body, "response": l.response_body,
        } for l in records]}

    @http.route(f"{API_ROOT}/healthz", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    def healthz(self, **kw):
        """Liveness plus the two background loops the frontline depends on."""
        Param = request.env["ir.config_parameter"].sudo()
        return request.make_response(
            '{"status": "ok", "outbox_last_run": "%s", "jobs_last_run": "%s"}' % (
                Param.get_param("hms.outbox.last_run", ""),
                Param.get_param("hms.jobs.last_run", ""),
            ),
            headers=[("Content-Type", "application/json")],
        )
