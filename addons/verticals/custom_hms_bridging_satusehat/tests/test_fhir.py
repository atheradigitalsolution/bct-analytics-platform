# -*- coding: utf-8 -*-
"""FHIR mapping and the push ordering rule."""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload
        self.status_code = status_code


@tagged("post_install", "-at_install", "hms")
class TestFhirBuilder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.builder = cls.env["hms.fhir.builder"]
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-SS", "name": "Poli SATUSEHAT", "type": "outpatient_clinic",
            "ihs_location_id": "LOC-1",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Indra Kusuma", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101770001", "ihs_practitioner_id": "PRC-1",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Bambang Sutrisno", "nik": "3201010101820001",
            "birth_date": "1982-01-01", "gender": "male", "phone": "0811222333",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })

    def test_patient_resource_carries_nik_as_official_identifier(self):
        resource = self.builder.patient_resource(self.patient)
        self.assertEqual(resource["resourceType"], "Patient")
        nik = [i for i in resource["identifier"] if i["system"].endswith("/nik")]
        self.assertEqual(len(nik), 1)
        self.assertEqual(nik[0]["value"], "3201010101820001")
        self.assertEqual(nik[0]["use"], "official")

    def test_patient_resource_omits_id_until_one_is_known(self):
        self.assertNotIn("id", self.builder.patient_resource(self.patient))
        self.patient.sudo().write({"ihs_patient_id": "P-123"})
        self.assertEqual(self.builder.patient_resource(self.patient)["id"], "P-123")

    def test_encounter_class_follows_the_visit_type(self):
        outpatient = self.builder.encounter_resource(self.encounter, "ORG-1")
        self.assertEqual(outpatient["class"]["code"], "AMB")
        self.encounter.sudo().write({"type": "emergency", "triage_level": "green"})
        emergency = self.builder.encounter_resource(self.encounter, "ORG-1")
        self.assertEqual(emergency["class"]["code"], "EMER")

    def test_observation_becomes_one_resource_per_measurement(self):
        observation = self.env["hms.observation"].create({
            "encounter_id": self.encounter.id,
            "systolic": 120, "diastolic": 80, "pulse": 88, "temperature": 36.8,
        })
        resources = self.builder.observation_resources(observation)
        codes = {r["code"]["coding"][0]["code"] for r in resources}
        self.assertEqual(codes, {"8480-6", "8462-4", "8867-4", "8310-5"})
        for resource in resources:
            self.assertEqual(resource["category"][0]["coding"][0]["code"], "vital-signs")

    def test_unrecorded_vitals_produce_no_resource(self):
        observation = self.env["hms.observation"].create({
            "encounter_id": self.encounter.id, "pulse": 80,
        })
        self.assertEqual(len(self.builder.observation_resources(observation)), 1)

    def test_condition_uses_the_icd10_system(self):
        icd = self.env["hms.icd10"].create({"code": "ZT-I10", "name_en": "Hypertension"})
        diagnosis = self.env["hms.diagnosis"].create({
            "encounter_id": self.encounter.id, "icd10_id": icd.id, "rank": "primary",
        })
        resource = self.builder.condition_resource(diagnosis)
        coding = resource["code"]["coding"][0]
        self.assertEqual(coding["system"], "http://hl7.org/fhir/sid/icd-10")
        self.assertEqual(coding["code"], icd.code)


@tagged("post_install", "-at_install", "hms")
class TestSatusehatPush(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-SS2", "name": "Poli SS2", "type": "outpatient_clinic",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Rahmat Hidayat", "nik": "3201010101830001",
            "birth_date": "1983-01-01", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
        })
        cls.client = cls.env["hms.satusehat.client"]

    def _token_response(self):
        return FakeResponse({"access_token": "tok-123", "expires_in": 3600})

    def test_patient_push_stores_the_returned_id(self):
        job = self.env["hms.job"].enqueue(
            "satusehat.patient.push", {"patient_id": self.patient.id}
        )
        with patch("requests.post", return_value=self._token_response()), \
             patch("requests.request", return_value=FakeResponse({"id": "P-999"})):
            job._run_one()
        self.assertEqual(job.state, "done")
        self.assertEqual(self.patient.ihs_patient_id, "P-999")

    def test_encounter_push_refuses_until_the_patient_is_known(self):
        job = self.env["hms.job"].enqueue(
            "satusehat.encounter.push", {"encounter_id": self.encounter.id}
        )
        with patch("requests.post", return_value=self._token_response()):
            job._run_one()
        self.assertEqual(job.state, "failed")
        self.assertIn("SATUSEHAT", job.last_error)

    def test_second_push_uses_put_not_post(self):
        """A repeat POST creates a duplicate at Kemenkes that cannot be undone."""
        self.patient.sudo().write({"ihs_patient_id": "P-777"})
        job = self.env["hms.job"].enqueue(
            "satusehat.patient.push", {"patient_id": self.patient.id}
        )
        with patch("requests.post", return_value=self._token_response()), \
             patch("requests.request", return_value=FakeResponse({"id": "P-777"})) as sender:
            job._run_one()
        method, url = sender.call_args[0][0], sender.call_args[0][1]
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("/Patient/P-777"))

    def test_token_is_cached_between_calls(self):
        self.patient.sudo().write({"ihs_patient_id": "P-555"})
        with patch("requests.post", return_value=self._token_response()) as auth, \
             patch("requests.request", return_value=FakeResponse({"id": "P-555"})):
            for _ in range(3):
                job = self.env["hms.job"].enqueue(
                    "satusehat.patient.push", {"patient_id": self.patient.id}
                )
                job._run_one()
        self.assertEqual(auth.call_count, 1, "Token harus dipakai ulang, bukan diminta ulang.")

    def test_client_secret_never_reaches_the_log(self):
        with patch("requests.post", return_value=self._token_response()):
            self.client._token()
        log = self.env["hms.bridging.log"].search(
            [("endpoint", "=", "oauth2/accesstoken")], limit=1
        )
        self.assertTrue(log)
        self.assertNotIn("demo-secret", log.request_body or "")

    def test_closing_an_encounter_queues_the_bundle(self):
        before = self.env["hms.job"].search_count([("name", "like", "satusehat.%")])
        self.encounter.action_close()
        after = self.env["hms.job"].search_count([("name", "like", "satusehat.%")])
        self.assertGreater(after, before)
