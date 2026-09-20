# -*- coding: utf-8 -*-
"""Job queue behaviour: backoff, death, handler dispatch, unsticking."""
from unittest.mock import patch

from odoo import fields
from odoo.tests import TransactionCase, tagged

from ..models.hms_job import BACKOFF_MINUTES

CALLS = []


def _probe_ok(self, job, payload):
    CALLS.append(payload)
    return {"echo": payload.get("value")}


def _probe_boom(self, job, payload):
    raise ValueError("gagal disengaja")


@tagged("post_install", "-at_install", "hms")
class TestJobQueue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Job = cls.env["hms.job"]

    def setUp(self):
        super().setUp()
        CALLS.clear()
        JobCls = type(self.env["hms.job"])
        SettingsCls = type(self.env["hms.settings"])
        # Handlers are hung off an arbitrary existing model; what matters is
        # that dispatch goes through the same (model, method) resolution the
        # bridging modules rely on.
        for name, func in (("_probe_ok", _probe_ok), ("_probe_boom", _probe_boom)):
            patcher = patch.object(SettingsCls, name, func, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        mapping = {
            "test.ok": ("hms.settings", "_probe_ok"),
            "test.boom": ("hms.settings", "_probe_boom"),
        }
        patcher = patch.object(JobCls, "_registry_map", lambda self: mapping)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enqueue_defaults_to_pending_now(self):
        job = self.Job.enqueue("test.ok", {"value": 1})
        self.assertEqual(job.state, "pending")
        self.assertLessEqual(job.next_run, fields.Datetime.now())

    def test_delay_pushes_next_run_into_the_future(self):
        job = self.Job.enqueue("test.ok", {}, delay_minutes=10)
        self.assertGreater(job.next_run, fields.Datetime.now())

    def test_claim_marks_running_and_skips_future_jobs(self):
        due = self.Job.enqueue("test.ok", {"value": "due"})
        later = self.Job.enqueue("test.ok", {"value": "later"}, delay_minutes=60)
        claimed = self.Job._claim(limit=10)
        self.assertIn(due, claimed)
        self.assertNotIn(later, claimed)
        self.assertEqual(due.state, "running")

    def test_unknown_handler_dies_immediately(self):
        job = self.Job.enqueue("no.such.handler", {})
        job._run_one()
        self.assertEqual(job.state, "dead")
        self.assertIn("no.such.handler", job.last_error)

    def test_failure_backs_off_on_the_ladder(self):
        job = self.Job.enqueue("test.boom", {})
        job._run_one()
        self.assertEqual(job.state, "failed")
        self.assertEqual(job.attempts, 1)
        gap = (job.next_run - fields.Datetime.now()).total_seconds() / 60.0
        self.assertAlmostEqual(gap, BACKOFF_MINUTES[0], delta=1.0)

    def test_repeated_failure_eventually_dies(self):
        job = self.Job.enqueue("test.boom", {}, max_attempts=3)
        for _ in range(3):
            job.write({"state": "pending", "next_run": fields.Datetime.now()})
            job._run_one()
        self.assertEqual(job.state, "dead")
        self.assertEqual(job.attempts, 3)

    def test_successful_run_stores_result(self):
        job = self.Job.enqueue("test.ok", {"value": 42})
        job._run_one()
        self.assertEqual(job.state, "done")
        self.assertIn("42", job.result)
        self.assertTrue(job.finished_at)

    def test_retry_resets_a_dead_job(self):
        job = self.Job.enqueue("test.boom", {}, max_attempts=1)
        job._run_one()
        self.assertEqual(job.state, "dead")
        job.action_retry()
        self.assertEqual(job.state, "pending")

    def test_unstick_returns_crashed_workers_jobs(self):
        job = self.Job.enqueue("test.ok", {})
        job.write({
            "state": "running",
            "started_at": fields.Datetime.subtract(fields.Datetime.now(), hours=2),
        })
        moved = self.Job._cron_unstick(minutes=30)
        self.assertEqual(moved, 1)
        self.assertIn(job.state, ("failed", "dead"))


@tagged("post_install", "-at_install", "hms")
class TestBridgingLogMasking(TransactionCase):
    def test_masks_secrets_in_dicts(self):
        Log = self.env["hms.bridging.log"]
        masked = Log.mask({"cons_id": "12345", "x-signature": "abc", "noKartu": "0001"})
        self.assertEqual(masked["cons_id"], "***")
        self.assertEqual(masked["x-signature"], "***")
        self.assertEqual(masked["noKartu"], "0001")

    def test_masks_secrets_nested_in_lists(self):
        Log = self.env["hms.bridging.log"]
        masked = Log.mask({"items": [{"password": "p", "keep": "k"}]})
        self.assertEqual(masked["items"][0]["password"], "***")
        self.assertEqual(masked["items"][0]["keep"], "k")

    def test_masks_secrets_in_raw_json_strings(self):
        Log = self.env["hms.bridging.log"]
        masked = Log.mask('{"user_key": "abcdef", "noSep": "0001"}')
        self.assertNotIn("abcdef", masked)
        self.assertIn("0001", masked)

    def test_record_persists_masked_payload_only(self):
        log = self.env["hms.bridging.log"].record(
            service="bpjs_vclaim", endpoint="/SEP/insert",
            request_body={"cons_id": "SECRET-CONS", "noKartu": "000123"},
            request_headers={"X-Signature": "SECRET-SIG"},
            response_code=200, response_body={"metaData": {"code": "200"}},
            is_mock=True,
        )
        self.assertNotIn("SECRET-CONS", log.request_body)
        self.assertNotIn("SECRET-SIG", log.request_headers)
        self.assertIn("000123", log.request_body)
