# -*- coding: utf-8 -*-
"""Koreksi RME: masa tenggang menolak, dan persetujuan tidak bisa diberikan sendiri."""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestCorrectionRequest(MedrecCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.encounter = cls._encounter()
        cls.head = cls.env["res.users"].create({
            "name": "Kepala RM Uji", "login": "zt-rm-kepala",
            "group_ids": [(4, cls.env.ref(
                "custom_hms_medrec.group_hms_medrec_manager").id)],
        })
        cls.clerk = cls.env["res.users"].create({
            "name": "PMIK Uji", "login": "zt-rm-pmik",
            "group_ids": [(4, cls.env.ref("custom_hms_medrec.group_hms_medrec").id)],
        })

    def _request(self, hours_ago=200, **kw):
        vals = {
            "encounter_id": self.encounter.id,
            "target_model": "hms.clinical.note",
            "target_res_id": 1,
            "target_label": "CPPT uji",
            "field_label": "Asesmen (A)",
            "entry_created_at": fields.Datetime.subtract(
                fields.Datetime.now(), hours=hours_ago
            ),
            "old_value": "hari ke-3",
            "new_value": "hari ke-5",
            "reason": "Anamnesis ulang.",
        }
        vals.update(kw)
        return self.env["hms.correction.request"].create(vals)

    def test_grace_deadline_comes_from_the_hospital_parameter(self):
        settings = self.env["hms.settings"].get_settings()
        settings.emr_correction_grace_hours = 72
        request = self._request()
        self.assertEqual(request.grace_hours_applied, 72)
        self.assertEqual(
            request.grace_deadline,
            fields.Datetime.add(request.entry_created_at, hours=72),
        )

    def test_an_entry_still_inside_the_grace_window_is_refused(self):
        """Koreksi yang masih boleh dikerjakan sendiri tidak boleh mengantre."""
        request = self._request(hours_ago=1)
        self.assertTrue(request.within_grace)
        with self.assertRaises(UserError):
            request.action_submit()
        self.assertEqual(request.state, "draft")

    def test_the_request_survives_the_refusal(self):
        """Pemeriksaan ada di action_submit, bukan di create.

        Kalau create yang melempar UserError, recordnya tidak pernah tersimpan
        dan antrian PMIK selamanya kosong — kegagalan yang pernah terjadi di
        repo ini pada hms.billing.
        """
        request = self._request(hours_ago=1)
        with self.assertRaises(UserError):
            request.action_submit()
        self.assertTrue(
            self.env["hms.correction.request"].browse(request.id).exists()
        )

    def test_an_entry_past_the_grace_window_may_be_submitted(self):
        request = self._request(hours_ago=200)
        self.assertFalse(request.within_grace)
        request.action_submit()
        self.assertEqual(request.state, "submitted")

    def test_a_plain_clerk_cannot_approve(self):
        request = self._request()
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.clerk).action_approve()

    def test_the_head_of_medical_records_can_approve(self):
        request = self._request()
        request.action_submit()
        request.with_user(self.head).action_approve()
        self.assertEqual(request.state, "approved")
        self.assertEqual(request.approved_by_id, self.head)

    def test_requester_cannot_approve_their_own_request(self):
        request = self._request(requested_by_id=self.head.id)
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.head).action_approve()

    def test_applying_without_an_addendum_reference_is_refused(self):
        request = self._request()
        request.action_submit()
        request.with_user(self.head).action_approve()
        with self.assertRaises(UserError):
            request.action_mark_applied()
        request.addendum_reference = "CPPT-2026-0099"
        request.action_mark_applied()
        self.assertEqual(request.state, "applied")

    def test_rejecting_without_a_reason_is_refused(self):
        request = self._request()
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.head).action_reject()

    def test_identical_values_are_refused(self):
        with self.assertRaises(ValidationError):
            self._request(old_value="sama", new_value="sama")

    def test_applied_request_cannot_be_cancelled_or_deleted(self):
        request = self._request()
        request.action_submit()
        request.with_user(self.head).action_approve()
        request.addendum_reference = "CPPT-2026-0100"
        request.action_mark_applied()
        with self.assertRaises(UserError):
            request.action_cancel()
        with self.assertRaises(UserError):
            request.unlink()
