# -*- coding: utf-8 -*-
"""Request/response trail for every outbound integration call."""
import json
import re

from odoo import api, fields, models

# Keys whose values must never be written to the log. Matched case-insensitively
# against JSON keys and against `key=value` pairs in headers.
SECRET_KEYS = (
    "password", "secret", "secret_key", "client_secret", "user_key", "cons_id",
    "authorization", "x-signature", "x-cons-id", "token", "access_token",
    "refresh_token", "api_key",
)
_MASK = "***"


class HmsBridgingLog(models.Model):
    _name = "hms.bridging.log"
    _description = "Log Panggilan Bridging"
    _order = "id desc"
    _log_access = False

    job_id = fields.Many2one("hms.job", "Job", ondelete="cascade", index=True)
    service = fields.Selection(
        [("bpjs_vclaim", "BPJS VClaim"), ("bpjs_antrol", "BPJS Antrean"),
         ("satusehat", "SATUSEHAT"), ("other", "Lainnya")],
        required=True, default="other", index=True,
    )
    endpoint = fields.Char(required=True)
    method = fields.Char(default="POST")
    request_body = fields.Text("Permintaan")
    request_headers = fields.Text("Header Permintaan")
    response_code = fields.Integer("Kode HTTP")
    response_body = fields.Text("Balasan")
    duration_ms = fields.Integer("Durasi (ms)")
    called_at = fields.Datetime(default=fields.Datetime.now, index=True)
    is_mock = fields.Boolean("Mode Mock", help="True berarti balasan berasal dari server tiruan demo.")
    error = fields.Char("Galat")

    @api.model
    def mask(self, data):
        """Strip credentials before anything is persisted.

        Applied at the logging boundary rather than at each call site: one
        forgotten call site is one leaked consumer secret, and these rows are
        readable by support staff.
        """
        if data is None:
            return None
        if isinstance(data, dict):
            return {
                k: (_MASK if k.lower() in SECRET_KEYS else self.mask(v))
                for k, v in data.items()
            }
        if isinstance(data, (list, tuple)):
            return [self.mask(v) for v in data]
        if isinstance(data, str):
            text = data
            for key in SECRET_KEYS:
                text = re.sub(
                    r'("%s"\s*:\s*)"[^"]*"' % re.escape(key), r'\1"%s"' % _MASK,
                    text, flags=re.IGNORECASE,
                )
                text = re.sub(
                    r'(%s\s*[:=]\s*)\S+' % re.escape(key), r'\1%s' % _MASK,
                    text, flags=re.IGNORECASE,
                )
            return text
        return data

    @api.model
    def record(self, service, endpoint, method="POST", request_body=None, request_headers=None,
               response_code=None, response_body=None, duration_ms=0, job=None,
               is_mock=False, error=None):
        def dump(value):
            if value is None:
                return False
            masked = self.mask(value)
            return masked if isinstance(masked, str) else json.dumps(masked, default=str)

        return self.sudo().create({
            "job_id": job.id if job else False,
            "service": service,
            "endpoint": endpoint,
            "method": method,
            "request_body": dump(request_body),
            "request_headers": dump(request_headers),
            "response_code": response_code or 0,
            "response_body": dump(response_body),
            "duration_ms": duration_ms,
            "is_mock": is_mock,
            "error": (error or "")[:200] or False,
        })

    @api.model
    def _gc(self, keep_days=180):
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=keep_days)
        old = self.sudo().search([("called_at", "<", cutoff)])
        count = len(old)
        old.unlink()
        return count
