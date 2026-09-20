# -*- coding: utf-8 -*-
"""Retensi: 25 tahun adalah lantai, dan tidak ada tombol yang menghapus."""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestRetention(MedrecCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rule = cls.env["hms.retention.rule"].create({
            "name": "Retensi uji", "scope": "inpatient",
        })

    def _review(self, **kw):
        today = fields.Date.context_today(self.env.user)
        last_visit = today - relativedelta(years=26)
        vals = {
            "rule_id": self.rule.id,
            "patient_id": self.patient.id,
            "last_visit_date": last_visit,
            "due_date": last_visit + relativedelta(years=self.rule.retention_years),
        }
        vals.update(kw)
        return self.env["hms.retention.review"].create(vals)

    def test_default_retention_comes_from_the_hospital_parameter(self):
        settings = self.env["hms.settings"].get_settings()
        settings.emr_retention_years = 30
        rule = self.env["hms.retention.rule"].create({
            "name": "Retensi uji 30", "scope": "outpatient",
        })
        self.assertEqual(rule.retention_years, 30)

    def test_retention_below_the_statutory_floor_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.retention.rule"].create({
                "name": "Retensi terlalu pendek", "scope": "emergency",
                "retention_years": 10,
            })

    def test_a_legal_hold_blocks_the_destruction_proposal(self):
        review = self._review(legal_hold=True, legal_hold_reference="PN-001/2026")
        self.assertTrue(review.is_excepted)
        review.disposition = "destruction_proposed"
        with self.assertRaises(UserError):
            review.action_review()
        self.assertEqual(review.state, "pending")

    def test_a_record_without_exception_may_be_proposed(self):
        review = self._review()
        self.assertFalse(review.is_excepted)
        review.disposition = "destruction_proposed"
        review.action_review()
        self.assertEqual(review.state, "reviewed")
        self.assertTrue(review.reviewed_at)

    def test_a_held_record_may_still_be_decided_to_stay(self):
        review = self._review(legal_hold=True)
        review.disposition = "retain"
        review.action_review()
        self.assertEqual(review.state, "reviewed")

    def test_review_without_a_decision_is_refused(self):
        review = self._review()
        with self.assertRaises(UserError):
            review.action_review()

    def test_decided_review_cannot_be_deleted(self):
        review = self._review()
        review.disposition = "retain"
        review.action_review()
        with self.assertRaises(UserError):
            review.unlink()

    def test_generating_reviews_is_idempotent(self):
        self.patient.write({
            "last_visit_date": fields.Date.context_today(self.env.user)
            - relativedelta(years=26),
        })
        Review = self.env["hms.retention.review"]
        first = Review.generate_reviews(self.rule)
        self.assertIn(self.patient, first.mapped("patient_id"))
        second = Review.generate_reviews(self.rule)
        self.assertFalse(second)

    def test_active_claim_hook_defaults_to_false_without_casemix(self):
        """Modul ini tidak bisa membaca klaim, dan mengatakannya apa adanya."""
        review = self._review()
        self.assertFalse(review._has_active_claim())
