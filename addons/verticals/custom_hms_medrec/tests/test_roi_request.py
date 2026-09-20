# -*- coding: utf-8 -*-
"""Pelepasan informasi: dasar hukumnya menolak, dan jejaknya selalu tertulis."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestRoiLegalBasis(MedrecCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["hms.consent.template"].create({
            "code": "ZT-GC-RM", "name": "Persetujuan Umum Uji", "type": "general",
            "body": "<p>Persetujuan umum</p>",
        })
        cls.Roi = cls.env["hms.roi.request"]

    def _consent(self, signed=True):
        consent = self.env["hms.consent"].create({
            "patient_id": self.patient.id,
            "template_id": self.template.id,
            "signer_name": self.patient.name,
        })
        if signed:
            consent.action_sign()
        return consent

    def _request(self, **kw):
        vals = {
            "patient_id": self.patient.id,
            "requester_type": "insurance",
            "requester_name": "PT Asuransi Uji",
            "purpose": "Verifikasi klaim.",
            "legal_basis": "art34",
        }
        vals.update(kw)
        return self.Roi.create(vals)

    def test_article_34_without_any_consent_is_refused(self):
        request = self._request()
        with self.assertRaises(UserError):
            request.action_submit()
        self.assertEqual(request.state, "draft")

    def test_article_34_with_an_unsigned_consent_is_refused(self):
        """Persetujuan yang belum ditandatangani bukan persetujuan."""
        request = self._request(consent_id=self._consent(signed=False).id)
        with self.assertRaises(UserError):
            request.action_submit()

    def test_article_34_with_a_signed_consent_passes(self):
        request = self._request(consent_id=self._consent().id)
        request.action_submit()
        self.assertEqual(request.state, "submitted")

    def test_article_35_needs_no_consent(self):
        request = self._request(
            requester_type="law_enforcement",
            requester_name="Penyidik Polsek Uji",
            legal_basis="art35",
        )
        request.action_submit()
        self.assertEqual(request.state, "submitted")

    def test_research_under_article_35_must_be_anonymized(self):
        with self.assertRaises(ValidationError):
            self._request(requester_type="research", legal_basis="art35", anonymized=False)

    def test_law_enforcement_under_article_35_may_keep_the_identity(self):
        """Ps. 35 ayat (2) tidak masuk akal untuk permintaan penyidik."""
        request = self._request(
            requester_type="law_enforcement", legal_basis="art35", anonymized=False,
        )
        self.assertFalse(request.anonymized)

    def test_consent_of_another_patient_is_refused(self):
        other = self.env["hms.patient"].create({
            "name": "Pasien Lain", "nik": "3201010101870099",
            "birth_date": "1987-02-02", "gender": "female",
        })
        consent = self._consent()
        with self.assertRaises(ValidationError):
            self._request(patient_id=other.id, consent_id=consent.id)


@tagged("post_install", "-at_install", "hms")
class TestRoiDisclosureTrail(MedrecCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.template = cls.env["hms.consent.template"].create({
            "code": "ZT-GC-RM2", "name": "Persetujuan Umum Uji 2", "type": "general",
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Pimpinan Uji", "login": "zt-rm-pimpinan",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_manager").id),
                          (4, cls.env.ref("custom_hms_medrec.group_hms_medrec").id)],
        })

    def _approved_request(self):
        consent = self.env["hms.consent"].create({
            "patient_id": self.patient.id,
            "template_id": self.template.id,
            "signer_name": self.patient.name,
        })
        consent.action_sign()
        request = self.env["hms.roi.request"].create({
            "patient_id": self.patient.id,
            "requester_type": "insurance",
            "requester_name": "PT Asuransi Uji",
            "purpose": "Verifikasi klaim.",
            "legal_basis": "art34",
            "consent_id": consent.id,
            "receipt_name": "Kurir",
            "document_ids": [(0, 0, {"doc_type": "summary", "page_count": 2})],
        })
        request.action_submit()
        request.with_user(self.manager).action_approve()
        return request

    def test_delivery_writes_a_disclose_row_in_the_access_log(self):
        Log = self.env["hms.access.log"]
        before = Log.search_count([("action", "=", "disclose")])
        request = self._approved_request()
        request.action_deliver()

        self.assertEqual(request.state, "delivered")
        self.assertEqual(Log.search_count([("action", "=", "disclose")]), before + 1)
        entry = request.access_log_id
        self.assertTrue(entry)
        self.assertEqual(entry.action, "disclose")
        self.assertEqual(entry.patient_id, self.patient)
        self.assertEqual(entry.model_name, "hms.roi.request")
        self.assertEqual(entry.res_id, request.id)

    def test_the_existing_access_log_actions_survive(self):
        """selection_add bersifat aditif; nilai lama tidak boleh hilang."""
        actions = dict(self.env["hms.access.log"]._fields["action"].selection)
        for legacy in ("read", "write", "create", "unlink", "print", "export"):
            self.assertIn(legacy, actions)
        self.assertIn("disclose", actions)

    def test_delivering_without_approval_is_refused(self):
        request = self.env["hms.roi.request"].create({
            "patient_id": self.patient.id,
            "requester_type": "law_enforcement",
            "requester_name": "Penyidik Uji",
            "purpose": "Penyidikan.",
            "legal_basis": "art35",
            "receipt_name": "Penyidik Uji",
            "document_ids": [(0, 0, {"doc_type": "summary"})],
        })
        request.action_submit()
        with self.assertRaises(UserError):
            request.action_deliver()
        self.assertFalse(request.access_log_id)

    def test_delivering_without_a_document_list_is_refused(self):
        request = self._approved_request()
        request.document_ids.unlink()
        with self.assertRaises(UserError):
            request.action_deliver()

    def test_delivered_request_cannot_be_cancelled(self):
        request = self._approved_request()
        request.action_deliver()
        with self.assertRaises(UserError):
            request.action_cancel()

    def test_submitted_request_cannot_be_deleted(self):
        request = self._approved_request()
        with self.assertRaises(UserError):
            request.unlink()
