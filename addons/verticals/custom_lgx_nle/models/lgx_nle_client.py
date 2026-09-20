# -*- coding: utf-8 -*-
"""Klien HTTP NLE / INSW — satu-satunya tempat `requests` dipanggil di modul ini."""
import json
import logging

import requests

from odoo import _, api, models
from odoo.exceptions import UserError

from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)

TIMEOUT = 30
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class LgxNleClient(models.AbstractModel):
    _name = "lgx.nle.client"
    _description = "Klien NLE / INSW"

    @api.model
    def _headers(self, company):
        company = company.sudo()
        if not company.lgx_nle_api_key:
            raise UserError(_(
                "API key NLE perusahaan %s belum diisi. Ia diperoleh lewat registrasi "
                "ke NLE, bersama id_platform.", company.display_name,
            ))
        return {
            "beacukai-api-key": company.lgx_nle_api_key,
            "Content-Type": "application/json",
        }

    @api.model
    def _call(self, company, method, path, payload=None, params=None, message=None):
        company = company.sudo()
        url = "%s%s" % ((company.lgx_nle_base_url or "").rstrip("/"), path)
        if message:
            message.write({
                "endpoint": "%s %s" % (method, url),
                "request_payload": json.dumps(payload or params or {}, indent=2, default=str),
                "attempt_count": message.attempt_count + 1,
            })
        try:
            response = requests.request(method, url, json=payload, params=params,
                                        headers=self._headers(company), timeout=TIMEOUT)
        except requests.RequestException as error:
            if message:
                message.write({"state": "failed", "error_message": str(error)})
            raise RetryableJobError(_("Gagal menghubungi NLE: %s", error), seconds=120) from error

        try:
            body = response.json()
        except ValueError:
            body = {"_raw": response.text[:4000]}
        if message:
            message.write({
                "http_status": response.status_code,
                "response_payload": json.dumps(body, indent=2, default=str),
            })
        if response.status_code >= 400:
            text = _("NLE menjawab HTTP %s: %s", response.status_code, response.text[:400])
            if message:
                message.write({"state": "failed", "error_message": text})
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableJobError(text, seconds=180)
            raise UserError(text)
        # NLE menjawab 200 dengan `status: Failed` untuk galat validasi. Memeriksa
        # kode HTTP saja berarti kegagalan yang sesungguhnya dicatat sebagai sukses.
        if isinstance(body, dict) and str(body.get("status", "")).lower() == "failed":
            text = _("NLE menolak permintaan: %s", body.get("message") or body)
            if message:
                message.write({"state": "failed", "error_message": text})
            raise UserError(text)
        if message:
            message.write({"state": "acked", "error_message": False})
        return body
