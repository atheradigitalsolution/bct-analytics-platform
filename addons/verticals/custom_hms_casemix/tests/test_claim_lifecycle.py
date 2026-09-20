# -*- coding: utf-8 -*-
"""State machine klaim: setiap transisi punya penjaga yang bisa menolak."""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestClaimLifecycle(CasemixCase):
    def _finalized(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        return claim

    def test_the_happy_path_reaches_paid(self):
        claim = self._finalized()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        self.assertEqual(claim.submission_count, 1)
        claim.action_start_verification()
        claim.action_approve(amount=1_000_000.0)
        claim.action_mark_paid(amount=1_000_000.0)
        self.assertEqual(claim.state, "paid")
        self.assertEqual(claim.paid_amount, 1_000_000.0)

    def test_transitions_out_of_order_are_refused(self):
        claim = self._claim()
        for action in ("action_code_done", "action_verify_internal",
                       "action_finalize", "action_submit",
                       "action_start_verification", "action_set_pending"):
            with self.assertRaises(UserError):
                getattr(claim, action)()
        self.assertEqual(claim.state, "to_code")

    def test_submission_without_a_batch_is_refused(self):
        claim = self._finalized()
        with self.assertRaises(UserError):
            claim.action_submit()
        self.assertEqual(claim.state, "finalized")

    def test_an_open_coding_query_blocks_finishing_the_coding(self):
        claim = self._coded_claim()
        query = self.env["hms.coding.query"].create({
            "claim_id": claim.id,
            "topic": "definitive",
            "question": "Sepsis dimaksudkan sebagai diagnosis definitif?",
            "addressed_to_id": self.doctor.id,
        })
        with self.assertRaises(UserError):
            claim.action_code_done()

        query.write({"answer": "Ya, definitif; kultur menyusul."})
        query.action_answer()
        query.write({"outcome": "code_kept"})
        query.action_close()
        claim.action_code_done()
        self.assertEqual(claim.state, "internal_review")

    def test_high_variance_cannot_be_verified_by_the_coder_who_wrote_it(self):
        """Empat mata, dan ambangnya datang dari parameter rumah sakit."""
        settings = self.env["hms.settings"].get_settings()
        settings.claim_variance_threshold = 1_000_000.0
        claim = self._coded_claim()
        claim.write({"hospital_bill_amount": 9_000_000.0, "grouped_tariff": 4_000_000.0})
        claim.action_code_done()
        self.assertTrue(claim.is_high_variance)

        with self.assertRaises(UserError):
            claim.action_verify_internal()

        verifier = self._role_user(
            "zt-cm-verifikator", "Verifikator Uji",
            ["custom_hms_casemix.group_hms_casemix_verifier"],
        )
        claim.write({"review_note": "Selisih karena obat kemoterapi di luar paket."})
        claim.with_user(verifier).action_verify_internal()
        self.assertEqual(claim.state, "internal_verified")
        self.assertEqual(claim.verifier_id, verifier)

    def test_low_variance_may_be_verified_by_the_coder(self):
        settings = self.env["hms.settings"].get_settings()
        settings.claim_variance_threshold = 10_000_000.0
        claim = self._coded_claim()
        claim.write({"hospital_bill_amount": 5_000_000.0, "grouped_tariff": 4_800_000.0})
        claim.action_code_done()
        self.assertFalse(claim.is_high_variance)
        claim.action_verify_internal()
        self.assertEqual(claim.state, "internal_verified")

    def test_variance_is_unknown_not_zero_before_grouping(self):
        claim = self._coded_claim()
        claim.write({"hospital_bill_amount": 9_000_000.0})
        self.assertEqual(claim.grouped_tariff, 0.0)
        self.assertFalse(claim.is_high_variance)

    def test_returning_to_the_coder_requires_saying_what_is_wrong(self):
        claim = self._coded_claim()
        claim.action_code_done()
        with self.assertRaises(UserError):
            claim.action_return_to_coding()
        claim.write({"review_note": "Diagnosis utama tidak didukung penunjang."})
        claim.action_return_to_coding()
        self.assertEqual(claim.state, "coding")

    def test_pending_needs_a_reason_and_a_category(self):
        claim = self._finalized()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        claim.action_start_verification()
        with self.assertRaises(UserError):
            claim.action_set_pending()
        claim.write({"pending_reason": "Laporan operasi tidak terbaca.",
                     "pending_category": "document"})
        claim.action_set_pending()
        self.assertEqual(claim.state, "pending")
        self.assertTrue(claim.pending_at)

    def test_resubmission_counts_and_needs_a_correction_note(self):
        claim = self._finalized()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        claim.action_start_verification()
        claim.write({"pending_reason": "Salah koding.", "pending_category": "coding"})
        claim.action_set_pending()

        with self.assertRaises(UserError):
            claim.action_resubmit()
        claim.write({"correction_note": "Diagnosis utama diperbaiki sesuai jawaban DPJP."})
        claim.action_resubmit()
        self.assertEqual(claim.state, "resubmitted")
        self.assertEqual(claim.submission_count, 2)

    def test_payment_that_does_not_match_needs_an_authorised_adjustment(self):
        claim = self._finalized()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        claim.action_start_verification()
        claim.write({"hospital_bill_amount": 5_000_000.0})
        claim.action_approve(amount=5_000_000.0)

        with self.assertRaises(UserError):
            claim.action_mark_paid(amount=4_500_000.0)

        adjustment = self.env["hms.claim.adjustment"].create({
            "claim_id": claim.id,
            "type": "verification_gap",
            "amount": 500_000.0,
            "reason": "Selisih verifikasi atas tindakan yang tidak ditanggung.",
        })
        manager = self._role_user(
            "zt-cm-manajer", "Manajer Uji", ["custom_hms_base.group_hms_manager"]
        )
        adjustment.with_user(manager).action_authorize()
        claim.invalidate_recordset()
        claim.action_mark_paid(amount=4_500_000.0)
        self.assertEqual(claim.state, "paid")

    def test_a_coder_cannot_authorise_their_own_adjustment(self):
        claim = self._finalized()
        coder = self._role_user(
            "zt-cm-koder-adj", "Koder Uji", ["custom_hms_casemix.group_hms_coder"]
        )
        adjustment = self.env["hms.claim.adjustment"].create({
            "claim_id": claim.id, "type": "expired", "amount": 100_000.0,
            "reason": "Kedaluwarsa.",
        })
        with self.assertRaises(UserError):
            adjustment.with_user(coder).action_authorize()

    def test_a_started_claim_cannot_be_deleted(self):
        claim = self._coded_claim()
        with self.assertRaises(UserError):
            claim.unlink()


@tagged("post_install", "-at_install", "hms")
class TestClaimBatch(CasemixCase):
    def test_a_batch_refuses_claims_that_are_not_final(self):
        claim = self._coded_claim()
        batch = self._batch_for(claim)
        claim.write({"batch_id": batch.id})
        with self.assertRaises(UserError):
            batch.action_submit()

    def test_a_batch_refuses_a_mismatched_care_type(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        batch = self._batch_for(claim, care_type="inpatient")
        claim.write({"batch_id": batch.id})
        with self.assertRaises(UserError):
            batch.action_submit()

    def test_a_batch_submits_every_claim_at_once(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        batch = self._batch_for(claim)
        claim.write({"batch_id": batch.id})
        batch.action_submit()
        self.assertEqual(batch.reconciliation_state, "submitted")
        self.assertEqual(claim.state, "submitted")

    def test_the_service_period_must_be_the_first_of_the_month(self):
        from odoo.exceptions import ValidationError
        claim = self._claim()
        batch = self._batch_for(claim)
        with self.assertRaises(ValidationError):
            batch.write({"service_period": "2026-03-15"})

    def test_reconciliation_needs_the_minutes_number(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        batch = self._batch_for(claim)
        claim.write({"batch_id": batch.id})
        batch.action_submit()
        batch.action_mark_verified()
        with self.assertRaises(UserError):
            batch.action_reconcile()
        batch.write({"ba_no": "BA/2026/0001", "ba_date": "2026-04-01"})
        batch.action_reconcile()
        self.assertEqual(batch.reconciliation_state, "reconciled")


@tagged("post_install", "-at_install", "hms")
class TestRetentionUsesClaims(CasemixCase):
    def test_an_unsettled_claim_blocks_the_destruction_proposal(self):
        """Hook ``_has_active_claim`` di custom_hms_medrec kini punya jawaban."""
        from dateutil.relativedelta import relativedelta
        from odoo import fields

        claim = self._claim()
        rule = self.env["hms.retention.rule"].create({
            "name": "Retensi casemix", "scope": "inpatient",
        })
        last_visit = fields.Date.context_today(self.env.user) - relativedelta(years=26)
        review = self.env["hms.retention.review"].create({
            "rule_id": rule.id,
            "patient_id": claim.patient_id.id,
            "last_visit_date": last_visit,
            "due_date": last_visit + relativedelta(years=rule.retention_years),
        })
        self.assertTrue(review.has_active_claim)
        review.disposition = "destruction_proposed"
        with self.assertRaises(UserError):
            review.action_review()

        # Klaim yang sudah tuntas tidak lagi menahan.
        claim.sudo().write({"state": "paid"})
        review.invalidate_recordset()
        review._compute_exception()
        self.assertFalse(review.has_active_claim)
        review.action_review()
        self.assertEqual(review.state, "reviewed")
