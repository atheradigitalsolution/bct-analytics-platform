# -*- coding: utf-8 -*-
"""SATUSEHAT OAuth2 client and job handlers."""
import json
import logging
import os
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TIMEOUT = 20
# Refresh a minute early: a token that expires mid-request produces a 401 that
# looks like a credential problem.
TOKEN_SKEW = 60


class HmsSatusehatClient(models.AbstractModel):
    _name = "hms.satusehat.client"
    _description = "Klien SATUSEHAT"

    _hms_job_handlers = {
        "satusehat.patient.push": "_job_push_patient",
        "satusehat.encounter.push": "_job_push_encounter",
        "satusehat.condition.push": "_job_push_condition",
        "satusehat.observation.push": "_job_push_observation",
        "satusehat.medication.push": "_job_push_medication",
    }

    # --- configuration ----------------------------------------------------
    @api.model
    def _settings(self):
        mode = os.environ.get("SATUSEHAT_MODE", "mock")
        base = os.environ.get("SATUSEHAT_BASE_URL", "http://mock-bridging:4010/satusehat")
        client_id = os.environ.get("SATUSEHAT_CLIENT_ID", "")
        secret = os.environ.get("SATUSEHAT_CLIENT_SECRET", "")
        org_id = os.environ.get("SATUSEHAT_ORG_ID", "")
        if mode != "mock" and not all((client_id, secret, org_id)):
            raise UserError(
                _("Kredensial SATUSEHAT belum lengkap. Isi SATUSEHAT_CLIENT_ID, "
                  "SATUSEHAT_CLIENT_SECRET dan SATUSEHAT_ORG_ID, atau jalankan dengan "
                  "SATUSEHAT_MODE=mock untuk demo.")
            )
        return {
            "mode": mode,
            "base_url": base.rstrip("/"),
            "auth_url": os.environ.get(
                "SATUSEHAT_AUTH_URL", f"{base.rstrip('/')}/oauth2/v1/accesstoken"
            ),
            "client_id": client_id or "demo-client",
            "client_secret": secret or "demo-secret",
            "org_id": org_id or "demo-org",
        }

    @api.model
    def _token(self):
        """Return a cached access token, refreshing only when it is nearly due."""
        Param = self.env["ir.config_parameter"].sudo()
        cached = Param.get_param("hms.satusehat.token")
        expires = float(Param.get_param("hms.satusehat.token_expires") or 0)
        if cached and expires - TOKEN_SKEW > time.time():
            return cached
        settings = self._settings()
        started = time.time()
        try:
            response = requests.post(
                settings["auth_url"],
                data={
                    "client_id": settings["client_id"],
                    "client_secret": settings["client_secret"],
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TIMEOUT,
            )
            body = response.text
            status = response.status_code
        except requests.RequestException as exc:
            self.env["hms.bridging.log"].record(
                service="satusehat", endpoint="oauth2/accesstoken", method="POST",
                error=str(exc), is_mock=settings["mode"] == "mock",
            )
            raise UserError(_("Gagal meminta token SATUSEHAT: %s") % exc) from exc
        self.env["hms.bridging.log"].record(
            service="satusehat", endpoint="oauth2/accesstoken", method="POST",
            request_body={"client_id": settings["client_id"], "client_secret": "***"},
            response_code=status, response_body=body,
            duration_ms=int((time.time() - started) * 1000),
            is_mock=settings["mode"] == "mock",
        )
        if status != 200:
            raise UserError(_("SATUSEHAT menolak kredensial (HTTP %s).") % status)
        data = json.loads(body or "{}")
        token = data.get("access_token")
        if not token:
            raise UserError(_("SATUSEHAT tidak mengembalikan access_token."))
        ttl = float(data.get("expires_in", 3600))
        Param.set_param("hms.satusehat.token", token)
        Param.set_param("hms.satusehat.token_expires", str(time.time() + ttl))
        return token

    @api.model
    def _send(self, resource, job=None):
        """POST a new resource or PUT an existing one.

        The choice is made from the presence of `id`: SATUSEHAT has no way to
        undo a duplicate POST from this side, so getting this wrong is
        permanent.
        """
        settings = self._settings()
        token = self._token()
        resource_type = resource["resourceType"]
        resource_id = resource.get("id")
        method = "PUT" if resource_id else "POST"
        path = f"fhir-r4/v1/{resource_type}" + (f"/{resource_id}" if resource_id else "")
        url = f"{settings['base_url']}/{path}"
        started = time.time()
        error, status, body = None, 0, None
        try:
            response = requests.request(
                method, url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(resource),
                timeout=TIMEOUT,
            )
            status, body = response.status_code, response.text
        except requests.RequestException as exc:
            error = str(exc)
        self.env["hms.bridging.log"].record(
            service="satusehat", endpoint=path, method=method,
            request_body=resource,
            request_headers={"Authorization": "***"},
            response_code=status, response_body=body,
            duration_ms=int((time.time() - started) * 1000),
            job=job, is_mock=settings["mode"] == "mock", error=error,
        )
        if error:
            raise UserError(_("Gagal mengirim %(t)s ke SATUSEHAT: %(e)s")
                            % {"t": resource_type, "e": error})
        if status not in (200, 201):
            raise UserError(
                _("SATUSEHAT menolak %(t)s (HTTP %(s)s): %(b)s")
                % {"t": resource_type, "s": status, "b": (body or "")[:200]}
            )
        return json.loads(body or "{}")

    # --- job handlers -----------------------------------------------------
    @api.model
    def _job_push_patient(self, job, payload):
        patient = self.env["hms.patient"].browse(payload["patient_id"])
        resource = self.env["hms.fhir.builder"].patient_resource(patient)
        result = self._send(resource, job=job)
        ihs_id = result.get("id")
        if ihs_id:
            patient.sudo().write({"ihs_patient_id": ihs_id})
        return {"ihs_patient_id": ihs_id}

    @api.model
    def _job_push_encounter(self, job, payload):
        encounter = self.env["hms.encounter"].browse(payload["encounter_id"])
        if not encounter.patient_id.ihs_patient_id:
            # Ordering matters: an Encounter referencing an unknown Patient is
            # rejected, so the dependency is queued rather than assumed.
            self.env["hms.job"].enqueue(
                "satusehat.patient.push", {"patient_id": encounter.patient_id.id},
                model_name="hms.patient", res_id=encounter.patient_id.id, priority=1,
            )
            raise UserError(
                _("Pasien belum punya ID SATUSEHAT; pengiriman Patient dijadwalkan lebih dulu.")
            )
        settings = self._settings()
        resource = self.env["hms.fhir.builder"].encounter_resource(encounter, settings["org_id"])
        result = self._send(resource, job=job)
        ihs_id = result.get("id")
        if ihs_id:
            encounter.sudo().write({"ihs_encounter_id": ihs_id})
            encounter.env["hms.event"].emit("bridging.updated", {
                "encounter_id": encounter.id, "ihs_encounter_id": ihs_id,
            })
        return {"ihs_encounter_id": ihs_id}

    @api.model
    def _job_push_condition(self, job, payload):
        diagnosis = self.env["hms.diagnosis"].browse(payload["diagnosis_id"])
        resource = self.env["hms.fhir.builder"].condition_resource(diagnosis)
        result = self._send(resource, job=job)
        if result.get("id"):
            diagnosis.sudo().write({"ihs_condition_id": result["id"]})
        return {"ihs_condition_id": result.get("id")}

    @api.model
    def _job_push_observation(self, job, payload):
        observation = self.env["hms.observation"].browse(payload["observation_id"])
        resources = self.env["hms.fhir.builder"].observation_resources(observation)
        sent = [self._send(resource, job=job).get("id") for resource in resources]
        return {"observation_ids": sent}

    @api.model
    def _job_push_medication(self, job, payload):
        line = self.env["hms.prescription.line"].browse(payload["line_id"])
        settings = self._settings()
        resource = self.env["hms.fhir.builder"].medication_request_resource(
            line, settings["org_id"]
        )
        result = self._send(resource, job=job)
        return {"medication_request_id": result.get("id")}


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    def action_push_satusehat(self):
        """Queue the whole clinical bundle for this visit, in dependency order."""
        Job = self.env["hms.job"]
        for enc in self:
            if not enc.patient_id.ihs_patient_id:
                Job.enqueue("satusehat.patient.push", {"patient_id": enc.patient_id.id},
                            model_name="hms.patient", res_id=enc.patient_id.id, priority=1)
            Job.enqueue("satusehat.encounter.push", {"encounter_id": enc.id},
                        model_name=enc._name, res_id=enc.id, priority=2)
            for diagnosis in enc.diagnosis_ids:
                Job.enqueue("satusehat.condition.push", {"diagnosis_id": diagnosis.id},
                            model_name=diagnosis._name, res_id=diagnosis.id, priority=3)
            for observation in enc.observation_ids:
                Job.enqueue("satusehat.observation.push", {"observation_id": observation.id},
                            model_name=observation._name, res_id=observation.id, priority=4)
        return True

    def action_close(self):
        """Closing a visit is what makes it worth reporting to Kemenkes."""
        res = super().action_close()
        for enc in self:
            enc.action_push_satusehat()
        return res
