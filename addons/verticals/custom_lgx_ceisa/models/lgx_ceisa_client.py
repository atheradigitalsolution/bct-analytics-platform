# -*- coding: utf-8 -*-
"""Klien HTTP CEISA 4.0 — satu-satunya tempat `requests` dipanggil di modul ini.

Dikumpulkan di satu model supaya dua hal dapat dijamin dengan membaca satu
berkas: bahwa setiap request memeriksa kesegaran token lebih dulu, dan bahwa
setiap request meninggalkan jejak di `lgx.integration.message`.

Payload disimpan MENTAH. Saat Bea Cukai menolak sebuah PIB tiga minggu kemudian,
yang dibutuhkan adalah byte yang benar-benar dikirim — bukan rekonstruksi dari
record yang sejak itu sudah berubah.
"""
import json
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)

# Batas waktu yang pendek, dengan sengaja. Job antrian yang menggantung pada
# socket selama dua menit menahan slot runner, dan runner yang penuh oleh job
# menggantung adalah antrian yang berhenti bergerak untuk semua dokumen lain.
TIMEOUT_TOKEN = 15
TIMEOUT_CALL = 30

# Status yang layak dicoba ulang versus yang tidak. 4xx selain 401/408/429
# adalah kesalahan kita sendiri: mencobanya ulang seribu kali tidak akan
# membuatnya benar, dan hanya mengubur galat yang sesungguhnya.
RETRYABLE_STATUS = {401, 408, 425, 429, 500, 502, 503, 504}


class LgxCeisaClient(models.AbstractModel):
    _name = "lgx.ceisa.client"
    _description = "Klien CEISA 4.0"

    # --- token -------------------------------------------------------------
    @api.model
    def _token_leeway(self):
        return int(self.env["ir.config_parameter"].sudo().get_param("lgx.ceisa_token_leeway", 15))

    @api.model
    def _lgx_ceisa_token(self, company, force_refresh=False):
        """Access token yang DIJAMIN masih segar saat dikembalikan.

        Dipanggil tepat sebelum setiap request, tidak pernah disimpan pemanggil
        untuk dipakai lagi nanti. Dengan masa berlaku sependek yang dipakai
        CEISA, token yang diambil saat job dijadwalkan sudah mati saat job
        benar-benar berjalan — dan gagalnya muncul sebagai 401 yang
        membingungkan, bukan sebagai token basi.
        """
        company = company.sudo()
        now = fields.Datetime.now()
        leeway = self._token_leeway()
        if not force_refresh and company.lgx_ceisa_token and company.lgx_ceisa_token_expiry:
            remaining = (company.lgx_ceisa_token_expiry - now).total_seconds()
            if remaining > leeway:
                return company.lgx_ceisa_token
        return self._request_token(company)

    @api.model
    def _request_token(self, company):
        company = company.sudo()
        if not (company.lgx_ceisa_client_id and company.lgx_ceisa_client_secret):
            raise UserError(_(
                "Kredensial CEISA 4.0 perusahaan %s belum diisi. Atur di "
                "Pengaturan → Logistik → CEISA 4.0.", company.display_name,
            ))
        url = "%s/nle-oauth/oauth/token" % (company.lgx_ceisa_base_url or "").rstrip("/")
        payload = {
            "grant_type": "client_credentials",
            "client_id": company.lgx_ceisa_client_id,
            "client_secret": company.lgx_ceisa_client_secret,
        }
        try:
            response = requests.post(url, json=payload, timeout=TIMEOUT_TOKEN)
        except requests.RequestException as error:
            raise RetryableJobError(
                _("Tidak dapat menghubungi CEISA untuk mengambil token: %s", error),
                seconds=60,
            ) from error
        if response.status_code != 200:
            message = _("Permintaan token CEISA ditolak (HTTP %s): %s",
                        response.status_code, response.text[:400])
            # 401 DI ENDPOINT TOKEN berarti kredensialnya salah, dan itu PERMANEN.
            #
            # Ini berbeda dari 401 di endpoint sumber daya, yang berarti token
            # basi dan sembuh dengan mengambil token baru. Menyamakan keduanya —
            # yang sempat saya lakukan, dan ditangkap tes terhadap mock —
            # membuat client_secret yang salah dicoba ulang delapan kali dengan
            # backoff sampai dua jam, lalu berakhir sebagai job gagal yang
            # penyebabnya terkubur di percobaan pertama.
            if response.status_code == 401:
                raise UserError(message)
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableJobError(message, seconds=120)
            raise UserError(message)
        body = response.json()
        token = body.get("access_token")
        expires_in = int(body.get("expires_in") or 300)
        if not token:
            raise UserError(_("Respons token CEISA tidak memuat access_token: %s",
                              response.text[:400]))
        company.write({
            "lgx_ceisa_token": token,
            "lgx_ceisa_token_expiry": fields.Datetime.add(fields.Datetime.now(),
                                                          seconds=expires_in),
        })
        _logger.info("Token CEISA diperbarui untuk %s, berlaku %ss", company.display_name,
                     expires_in)
        return token

    # --- request berjejak --------------------------------------------------
    @api.model
    def _call(self, company, method, path, payload=None, message=None, retry_on_401=True):
        """Satu request, dengan jejak lengkap dan penanganan token basi.

        401 setelah token dianggap segar berarti token itu dicabut atau server
        menganggapnya mati lebih awal. Satu kali percobaan ulang dengan token
        baru adalah penanganan yang benar; mencoba ulang tanpa batas pada 401
        adalah cara kredensial yang memang salah menghabiskan antrian.
        """
        company = company.sudo()
        base = (company.lgx_ceisa_base_url or "").rstrip("/")
        url = "%s%s" % (base, path)
        token = self._lgx_ceisa_token(company)
        headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
        if message:
            message.write({
                "endpoint": "%s %s" % (method, url),
                "request_payload": json.dumps(payload, indent=2, default=str) if payload else False,
                "attempt_count": message.attempt_count + 1,
            })
        try:
            response = requests.request(method, url, json=payload, headers=headers,
                                        timeout=TIMEOUT_CALL)
        except requests.RequestException as error:
            if message:
                message.write({"state": "failed", "error_message": str(error)})
            raise RetryableJobError(
                _("Gagal menghubungi CEISA: %s", error), seconds=120) from error

        if response.status_code == 401 and retry_on_401:
            self._lgx_ceisa_token(company, force_refresh=True)
            return self._call(company, method, path, payload, message, retry_on_401=False)

        body = self._safe_json(response)
        if message:
            message.write({
                "http_status": response.status_code,
                "response_payload": json.dumps(body, indent=2, default=str),
            })
        if response.status_code >= 400:
            text = _("CEISA menjawab HTTP %s: %s", response.status_code, response.text[:400])
            if message:
                message.write({"state": "failed", "error_message": text})
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableJobError(text, seconds=180)
            # Galat permanen: JANGAN dicoba ulang. Mengulang kesalahan kita
            # sendiri seribu kali hanya mengubur galat yang sesungguhnya.
            raise UserError(text)
        if message:
            message.write({"state": "acked", "error_message": False})
        return body

    @api.model
    def _safe_json(self, response):
        try:
            return response.json()
        except ValueError:
            return {"_raw": response.text[:4000]}

    # --- diagnostik --------------------------------------------------------
    @api.model
    def action_test_connection(self, company=None):
        """Uji kredensial tanpa mengirim dokumen apa pun."""
        company = company or self.env.company
        token = self._lgx_ceisa_token(company, force_refresh=True)
        expiry = company.sudo().lgx_ceisa_token_expiry
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("CEISA 4.0 terhubung"),
                "message": _("Token diperoleh (%s...), berlaku sampai %s.",
                             token[:8], expiry),
                "sticky": False,
            },
        }
