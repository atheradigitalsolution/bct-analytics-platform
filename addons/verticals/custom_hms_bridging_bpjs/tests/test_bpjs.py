# -*- coding: utf-8 -*-
"""Signature construction, LZ-String decoding, and the SEP job path."""
import base64
import hashlib
import hmac
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..models import vclaim_crypto


# --- reference encoder -------------------------------------------------------
# A from-the-spec implementation of LZ-String's compressToEncodedURIComponent,
# used only to feed the decoder under test. Kept in the test file deliberately:
# production never compresses, it only decompresses what BPJS sends.
_KEY_STR_URI = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"


def _lz_compress_encoded_uri(uncompressed):
    if not uncompressed:
        return ""
    bits_per_char = 6
    dictionary = {}
    to_create = {}
    w = ""
    enlarge_in = 2
    dict_size = 3
    num_bits = 2
    out = []
    data_val = 0
    data_position = 0

    def write_bits(value, count):
        nonlocal data_val, data_position
        for _ in range(count):
            data_val = (data_val << 1) | (value & 1)
            if data_position == bits_per_char - 1:
                data_position = 0
                out.append(_KEY_STR_URI[data_val])
                data_val = 0
            else:
                data_position += 1
            value >>= 1

    def emit(token):
        """Write one token, then apply the shared bit-width growth step.

        The growth step runs for BOTH the new-symbol and known-symbol paths —
        a new symbol consumes two units of `enlarge_in`, one inside its own
        branch and one here. Dropping the shared decrement is what makes an
        encoder that round-trips single characters and nothing longer.
        """
        nonlocal enlarge_in, num_bits, dict_size
        if token in to_create:
            code_point = ord(token[0])
            if code_point < 256:
                write_bits(0, num_bits)
                write_bits(code_point, 8)
            else:
                write_bits(1, num_bits)
                write_bits(code_point, 16)
            enlarge_in -= 1
            if enlarge_in == 0:
                enlarge_in = 1 << num_bits
                num_bits += 1
            del to_create[token]
        else:
            write_bits(dictionary[token], num_bits)
        enlarge_in -= 1
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1

    for c in uncompressed:
        if c not in dictionary:
            dictionary[c] = dict_size
            dict_size += 1
            to_create[c] = True
        wc = w + c
        if wc in dictionary:
            w = wc
            continue
        emit(w)
        dictionary[wc] = dict_size
        dict_size += 1
        w = c

    if w != "":
        emit(w)

    write_bits(2, num_bits)
    while True:
        data_val <<= 1
        if data_position == bits_per_char - 1:
            out.append(_KEY_STR_URI[data_val])
            break
        data_position += 1
    return "".join(out)


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


@tagged("post_install", "-at_install", "hms")
class TestVclaimCrypto(TransactionCase):
    def test_signature_matches_an_independent_computation(self):
        cons_id, secret, ts = "12345", "rahasia", "1700000000"
        got = vclaim_crypto.signature(cons_id, secret, ts)
        expected = base64.b64encode(
            hmac.new(secret.encode(), f"{cons_id}&{ts}".encode(), hashlib.sha256).digest()
        ).decode()
        self.assertEqual(got, expected)

    def test_decrypt_key_is_sha256_of_the_concatenation(self):
        key = vclaim_crypto.decrypt_key("12345", "rahasia", "1700000000")
        self.assertEqual(key, hashlib.sha256(b"12345rahasia1700000000").digest())
        self.assertEqual(len(key), 32)

    def test_lz_decompress_round_trips_json(self):
        """Decode what an independent encoder produced.

        The encoder below is written from the LZ-String specification rather
        than reused from the module, so this exercises the decoder against a
        separate implementation. It is NOT proof of interoperability with
        BPJS's own encoder — that needs a captured production payload, which
        requires sandbox credentials the demo does not have.
        """
        payload = json.dumps({"peserta": {"noKartu": "0001112223334", "hakKelas": "3"}})
        encoded = _lz_compress_encoded_uri(payload)
        self.assertEqual(vclaim_crypto.lz_decompress(encoded), payload)

    def test_lz_decompress_round_trips_repetitive_text(self):
        """Repetition is where a dictionary coder earns its keep — and breaks."""
        payload = "SEP" * 200 + "0301R001" * 50
        self.assertEqual(
            vclaim_crypto.lz_decompress(_lz_compress_encoded_uri(payload)), payload
        )

    def test_lz_decompress_round_trips_non_ascii(self):
        payload = "Peserta tidak ditemukan — cek nomor kartu"
        self.assertEqual(
            vclaim_crypto.lz_decompress(_lz_compress_encoded_uri(payload)), payload
        )

    def test_lz_decompress_of_empty_input_is_empty(self):
        self.assertEqual(vclaim_crypto.lz_decompress(""), "")
        self.assertEqual(vclaim_crypto.lz_decompress(None), "")


@tagged("post_install", "-at_install", "hms")
class TestSepJob(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-BPJS", "name": "Poli BPJS", "type": "outpatient_clinic",
            "bpjs_poli_code": "INT",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Ahmad Fauzi", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101780001", "bpjs_doctor_code": "D001",
        })
        cls.payer = cls.env["hms.payer"].create({
            "code": "ZT-BPJS-J", "name": "BPJS Kesehatan", "type": "bpjs", "requires_sep": True,
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Sari Wulandari", "nik": "3201014501890001",
            "birth_date": "1989-01-05", "gender": "female", "bpjs_no": "0001112223334",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "payer_id": cls.payer.id, "practitioner_id": cls.doctor.id,
        })

    def _sep_job(self):
        return self.env["hms.job"].search([
            ("name", "=", "bpjs.sep.create"), ("res_id", "=", self.encounter.id),
        ], limit=1)

    def test_registration_queues_the_sep_job(self):
        self.assertEqual(self.encounter.sep_state, "pending")
        self.assertTrue(self._sep_job())

    def test_successful_response_stores_the_sep_number(self):
        body = json.dumps({
            "metaData": {"code": "200", "message": "OK"},
            "response": {"sep": {"noSep": "0301R0011124V000123"}},
        })
        with patch("requests.request", return_value=FakeResponse(body)):
            job = self._sep_job()
            job._run_one()
        self.assertEqual(job.state, "done")
        self.assertEqual(self.encounter.sep_no, "0301R0011124V000123")
        self.assertEqual(self.encounter.sep_state, "issued")

    def test_successful_response_records_the_sep_document(self):
        body = json.dumps({
            "metaData": {"code": "200", "message": "OK"},
            "response": {"sep": {"noSep": "0301R0011124V000999"}},
        })
        with patch("requests.request", return_value=FakeResponse(body)):
            self._sep_job()._run_one()
        sep = self.env["hms.sep"].search([("name", "=", "0301R0011124V000999")])
        self.assertEqual(len(sep), 1)
        self.assertEqual(sep.encounter_id, self.encounter)
        self.assertEqual(sep.card_no, "0001112223334")

    def test_rejected_response_fails_the_job_and_schedules_a_retry(self):
        body = json.dumps({
            "metaData": {"code": "201", "message": "Peserta tidak ditemukan"},
        })
        with patch("requests.request", return_value=FakeResponse(body)):
            job = self._sep_job()
            job._run_one()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.attempts, 1)
        self.assertIn("Peserta tidak ditemukan", job.last_error)
        self.assertFalse(self.encounter.sep_no)

    def test_every_call_is_logged_with_credentials_masked(self):
        body = json.dumps({
            "metaData": {"code": "200", "message": "OK"},
            "response": {"sep": {"noSep": "0301R0011124V000555"}},
        })
        with patch("requests.request", return_value=FakeResponse(body)):
            job = self._sep_job()
            job._run_one()
        log = self.env["hms.bridging.log"].search([("job_id", "=", job.id)], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.service, "bpjs_vclaim")
        self.assertTrue(log.is_mock)
        self.assertIn("***", log.request_headers or "",
                      "Header bertanda tangan harus tersamarkan di log.")

    def test_network_failure_becomes_a_retryable_job_failure(self):
        import requests as requests_lib
        with patch("requests.request", side_effect=requests_lib.ConnectionError("host mati")):
            job = self._sep_job()
            job._run_one()
        self.assertEqual(job.state, "failed")
        self.assertIn("host mati", job.last_error)

    def test_repeated_failure_ends_as_dead(self):
        body = json.dumps({"metaData": {"code": "500", "message": "Gangguan"}})
        job = self._sep_job()
        job.max_attempts = 2
        with patch("requests.request", return_value=FakeResponse(body)):
            for _ in range(2):
                job.write({"state": "pending"})
                job._run_one()
        self.assertEqual(job.state, "dead")

    def test_retry_action_requeues_a_failed_sep(self):
        self.encounter.sudo().write({"sep_state": "failed", "sep_error": "gagal"})
        self.encounter.action_retry_sep()
        self.assertEqual(self.encounter.sep_state, "pending")
        self.assertFalse(self.encounter.sep_error)

    def test_retry_is_refused_once_a_sep_exists(self):
        self.encounter.sudo().write({"sep_no": "SEP-ADA"})
        with self.assertRaises(UserError):
            self.encounter.action_retry_sep()
