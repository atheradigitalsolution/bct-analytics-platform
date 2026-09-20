# -*- coding: utf-8 -*-
"""HTTP client and job handlers for VClaim and Antrean."""
import json
import logging
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import vclaim_crypto

_logger = logging.getLogger(__name__)

TIMEOUT = 20


class HmsBpjsClient(models.AbstractModel):
    _name = "hms.bpjs.client"
    _description = "Klien BPJS"

    # Job names this model answers to. hms.job resolves handlers through this
    # map, so registration is data rather than an import side effect.
    _hms_job_handlers = {
        "bpjs.peserta.check": "_job_check_peserta",
        "bpjs.sep.create": "_job_create_sep",
        "bpjs.sep.delete": "_job_delete_sep",
        "bpjs.antrol.add": "_job_antrol_add",
        "bpjs.antrol.update_waktu": "_job_antrol_update_waktu",
    }

    # --- transport --------------------------------------------------------
    @api.model
    def _call(self, service, method, path, payload=None, job=None):
        """One request, always logged, never allowed to raise a bare traceback."""
        creds = self.env["hms.bpjs.config"].credentials(service)
        ts = vclaim_crypto.timestamp()
        headers = {
            "X-cons-id": creds["cons_id"],
            "X-timestamp": ts,
            "X-signature": vclaim_crypto.signature(creds["cons_id"], creds["secret_key"], ts),
            "user_key": creds["user_key"],
            "Content-Type": "application/json; charset=utf-8",
        }
        url = f"{creds['base_url'].rstrip('/')}/{path.lstrip('/')}"
        started = time.time()
        error = None
        status = 0
        body = None
        try:
            response = requests.request(
                method, url, headers=headers,
                data=json.dumps(payload) if payload is not None else None,
                timeout=TIMEOUT,
            )
            status = response.status_code
            body = response.text
        except requests.RequestException as exc:
            error = str(exc)
        duration = int((time.time() - started) * 1000)
        self.env["hms.bridging.log"].record(
            service="bpjs_antrol" if service == "antrol" else "bpjs_vclaim",
            endpoint=path, method=method, request_body=payload, request_headers=headers,
            response_code=status, response_body=body, duration_ms=duration,
            job=job, is_mock=creds["mode"] == "mock", error=error,
        )
        if error:
            raise UserError(_("Gagal menghubungi BPJS: %s") % error)
        return self._parse(body, creds, ts)

    @api.model
    def _parse(self, body, creds, ts):
        """Unwrap metaData/response, decrypting when BPJS encrypted it."""
        try:
            parsed = json.loads(body or "{}")
        except ValueError:
            raise UserError(_("Balasan BPJS bukan JSON yang sah.")) from None
        meta = parsed.get("metaData") or parsed.get("metadata") or {}
        code = str(meta.get("code", ""))
        message = meta.get("message", "")
        if code not in ("200", "1"):
            raise UserError(
                _("BPJS menolak permintaan (%(code)s): %(msg)s")
                % {"code": code or "?", "msg": message or _("tanpa keterangan")}
            )
        response = parsed.get("response")
        if isinstance(response, str) and response:
            # Production VClaim encrypts; the mock server returns plain JSON.
            try:
                decoded = vclaim_crypto.decode_response(
                    response, creds["cons_id"], creds["secret_key"], ts
                )
                response = json.loads(decoded) if decoded else {}
            except Exception as exc:  # noqa: BLE001 — falls back to plain text
                _logger.warning("Balasan BPJS tidak dapat didekripsi: %s", exc)
                try:
                    response = json.loads(response)
                except ValueError:
                    response = {"raw": response}
        return response or {}

    # --- job handlers -----------------------------------------------------
    @api.model
    def _job_check_peserta(self, job, payload):
        patient = self.env["hms.patient"].browse(payload["patient_id"])
        card = patient.bpjs_no
        if not card:
            raise UserError(_("Pasien %s belum memiliki nomor kartu JKN.") % patient.name)
        data = self._call(
            "vclaim", "GET", f"Peserta/nokartu/{card}/tglSEP/{payload.get('date')}", job=job
        )
        peserta = data.get("peserta", {})
        patient.sudo().write({
            "bpjs_status": (peserta.get("statusPeserta") or {}).get("keterangan"),
            "bpjs_class": (peserta.get("hakKelas") or {}).get("kode"),
            "bpjs_checked_at": fields.Datetime.now(),
        })
        return peserta

    @api.model
    def _job_create_sep(self, job, payload):
        encounter = self.env["hms.encounter"].browse(payload["encounter_id"])
        if not encounter.exists():
            raise UserError(_("Kunjungan sudah tidak ada."))
        creds = self.env["hms.bpjs.config"].credentials("vclaim")
        body = {
            "request": {
                "t_sep": {
                    "noKartu": encounter.patient_id.bpjs_no,
                    "tglSep": str(encounter.arrival_at.date()),
                    "ppkPelayanan": creds["ppk_code"],
                    "jnsPelayanan": "1" if encounter.type == "inpatient" else "2",
                    "klsRawat": {
                        "klsRawatHak": encounter.patient_id.bpjs_class or "3",
                        "klsRawatNaik": "",
                        "pembiayaan": "",
                        "penanggungJawab": "",
                    },
                    "noMR": encounter.patient_id.mrn,
                    "rujukan": {
                        "asalRujukan": "1",
                        "tglRujukan": str(encounter.referral_id.referral_date or ""),
                        "noRujukan": encounter.referral_id.name or "",
                        "ppkRujukan": encounter.referral_id.source_code or "",
                    },
                    "catatan": encounter.chief_complaint or "",
                    "diagAwal": (encounter.primary_diagnosis_id.code
                                 if "primary_diagnosis_id" in encounter._fields else ""),
                    "poli": {"tujuan": encounter.unit_id.bpjs_poli_code or "", "eksekutif": "0"},
                    "cob": {"cob": "0"},
                    "katarak": {"katarak": "0"},
                    "jaminan": {
                        "lakaLantas": "0",
                        "penjamin": {"tglKejadian": "", "keterangan": "", "suplesi": {}},
                    },
                    "tujuanKunj": {"tujuan": "0"},
                    "flagProcedure": {"flagProcedure": ""},
                    "kdPenunjang": {"kdPenunjang": ""},
                    "assesmentPel": {"assesmentPel": ""},
                    "skdp": {"noSurat": "", "kodeDPJP": ""},
                    "dpjpLayan": encounter.practitioner_id.bpjs_doctor_code or "",
                    "noTelp": encounter.patient_id.phone or "",
                    "user": self.env.user.name,
                }
            }
        }
        data = self._call("vclaim", "POST", "SEP/2.0/insert", payload=body, job=job)
        sep = data.get("sep", {})
        sep_no = sep.get("noSep") or data.get("noSep")
        if not sep_no:
            raise UserError(_("BPJS tidak mengembalikan nomor SEP."))
        encounter.sudo().write({
            "sep_no": sep_no, "sep_state": "issued", "sep_error": False,
        })
        self.env["hms.sep"].sudo().record_from_response(encounter, sep_no, data)
        encounter.env["hms.event"].emit("bridging.updated", {
            "encounter_id": encounter.id, "sep_no": sep_no, "state": "issued",
        })
        return {"noSep": sep_no}

    @api.model
    def _job_delete_sep(self, job, payload):
        encounter = self.env["hms.encounter"].browse(payload["encounter_id"])
        body = {"request": {"t_sep": {
            "noSep": encounter.sep_no, "user": self.env.user.name,
        }}}
        self._call("vclaim", "DELETE", "SEP/2.0/delete", payload=body, job=job)
        encounter.sudo().write({"sep_state": "cancelled", "sep_no": False})
        return {"deleted": True}

    @api.model
    def _job_antrol_add(self, job, payload):
        data = self._call("antrol", "POST", "antrean/add", payload=payload.get("body"), job=job)
        return data

    @api.model
    def _job_antrol_update_waktu(self, job, payload):
        data = self._call(
            "antrol", "POST", "antrean/updatewaktu", payload=payload.get("body"), job=job
        )
        return data


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    def action_retry_sep(self):
        """Re-queue the SEP request after a failure."""
        for enc in self:
            if enc.sep_no:
                raise UserError(_("SEP %s sudah terbit.") % enc.sep_no)
            enc.write({"sep_state": "pending", "sep_error": False})
            self.env["hms.job"].enqueue(
                "bpjs.sep.create", payload={"encounter_id": enc.id},
                model_name=enc._name, res_id=enc.id, priority=5,
            )
        return True

    def action_check_peserta(self):
        for enc in self:
            self.env["hms.job"].enqueue(
                "bpjs.peserta.check",
                payload={"patient_id": enc.patient_id.id,
                         "date": str(enc.arrival_at.date())},
                model_name=enc.patient_id._name, res_id=enc.patient_id.id,
            )
        return True
