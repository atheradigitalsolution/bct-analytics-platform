# -*- coding: utf-8 -*-
"""Penyesuaian klaim: wewenang berjenjang, dan baris yang append-only.

Dua hal yang diuji di sini tidak bisa dibuktikan dengan membaca kode:

1. **plafon otorisasinya benar-benar datang dari ``hms.settings``** — nilai
   yang sama ditolak atau diterima semata karena parameternya digeser;
2. **baris yang sudah disahkan benar-benar beku** — koreksinya hanya lewat
   baris baru, dan pembukuan pembayaran tetap cocok sesudahnya.
"""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestClaimAdjustment(CasemixCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.verifier_user = cls.env["res.users"].create({
            "name": "Verifikator Penyesuaian", "login": "zt-adj-verifikator",
            "group_ids": [(4, cls.env.ref(
                "custom_hms_casemix.group_hms_casemix_verifier").id)],
        })
        cls.coder_user = cls.env["res.users"].create({
            "name": "Koder Penyesuaian", "login": "zt-adj-koder",
            "group_ids": [(4, cls.env.ref("custom_hms_casemix.group_hms_coder").id)],
        })
        cls.manager_user = cls.env["res.users"].create({
            "name": "Manajer Penyesuaian", "login": "zt-adj-manajer",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_manager").id)],
        })

    def _set_limit(self, value):
        self.env["hms.settings"].get_settings().claim_adjustment_authorization_limit = value

    def _submitted_claim(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        return claim

    def _approved_claim(self, approved=1_000_000.0):
        claim = self._submitted_claim()
        claim.action_start_verification()
        claim.action_approve(amount=approved)
        return claim

    # ------------------------------------------------------------------
    # Penerbitan
    # ------------------------------------------------------------------
    def test_an_adjustment_cannot_be_issued_before_the_claim_ever_left(self):
        """Selisih atas angka yang belum pernah diajukan bukan selisih."""
        claim = self._coded_claim()
        with self.assertRaises(UserError):
            claim.action_issue_adjustment({
                "type": "verification_gap", "amount": 50_000.0,
                "reason": "Belum diajukan ke siapa pun.",
            })

    def test_an_adjustment_is_issued_against_a_submitted_claim(self):
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 75_000.0,
            "reason": "Selisih verifikasi penjamin.",
        })
        self.assertEqual(adjustment.state, "draft")
        self.assertEqual(adjustment.proposed_by_id, self.coder_user)
        self.assertEqual(adjustment.encounter_id, claim.encounter_id)

    # ------------------------------------------------------------------
    # Plafon dari hms.settings — angka yang sama, keputusan yang bergeser
    # ------------------------------------------------------------------
    def test_below_the_limit_a_casemix_verifier_may_authorize(self):
        self._set_limit(1_000_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 400_000.0,
            "reason": "Selisih kecil, rutin.",
        })
        self.assertFalse(adjustment.requires_management)
        adjustment.with_user(self.verifier_user).action_authorize()
        self.assertEqual(adjustment.state, "authorized")
        self.assertEqual(adjustment.authorized_by_id, self.verifier_user)

    def test_moving_the_parameter_moves_the_decision(self):
        """Inti pengujian ini: nilai yang sama, jawaban yang berbeda."""
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "dispute_loss", "amount": 400_000.0,
            "reason": "Dispute tidak dimenangkan.",
        })

        # Plafon di bawah nilai penyesuaian: verifikator ditolak.
        self._set_limit(100_000.0)
        adjustment.invalidate_recordset()
        self.assertTrue(adjustment.requires_management)
        with self.assertRaises(UserError):
            adjustment.with_user(self.verifier_user).action_authorize()
        self.assertEqual(adjustment.state, "draft")

        # Plafon dinaikkan di atas nilainya: verifikator yang sama lolos.
        self._set_limit(1_000_000.0)
        adjustment.invalidate_recordset()
        self.assertFalse(adjustment.requires_management)
        adjustment.with_user(self.verifier_user).action_authorize()
        self.assertEqual(adjustment.state, "authorized")

    def test_a_limit_of_zero_sends_everything_to_management(self):
        """Parameter yang belum diisi bukan berarti plafon tak terbatas."""
        self._set_limit(0.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "penalty", "amount": 1_000.0, "reason": "Denda kecil.",
        })
        self.assertTrue(adjustment.requires_management)
        with self.assertRaises(UserError):
            adjustment.with_user(self.verifier_user).action_authorize()
        adjustment.with_user(self.manager_user).action_authorize()
        self.assertEqual(adjustment.state, "authorized")

    def test_a_coder_can_never_authorize_even_a_tiny_adjustment(self):
        self._set_limit(1_000_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 1_000.0, "reason": "Pembulatan.",
        })
        with self.assertRaises(UserError):
            adjustment.with_user(self.coder_user).action_authorize()

    def test_the_limit_in_force_is_recorded_on_the_record(self):
        self._set_limit(750_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "expired", "amount": 500_000.0, "reason": "Klaim kedaluwarsa.",
        })
        adjustment.with_user(self.verifier_user).action_authorize()
        self.assertEqual(adjustment.authorization_limit_applied, 750_000.0)

    def test_management_cannot_authorize_its_own_large_proposal(self):
        self._set_limit(100_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.manager_user).action_issue_adjustment({
            "type": "dispute_loss", "amount": 900_000.0,
            "reason": "Dispute kalah di tingkat pusat.",
        })
        with self.assertRaises(UserError):
            adjustment.with_user(self.manager_user).action_authorize()

    # ------------------------------------------------------------------
    # Append-only
    # ------------------------------------------------------------------
    def test_an_authorized_adjustment_cannot_be_edited(self):
        self._set_limit(1_000_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 300_000.0,
            "reason": "Selisih verifikasi.",
        })
        adjustment.with_user(self.verifier_user).action_authorize()
        for vals in ({"amount": 100_000.0},
                     {"type": "penalty"},
                     {"reason": "Alasan lain."},
                     {"claim_id": claim.id}):
            with self.assertRaises(UserError):
                adjustment.write(vals)
        adjustment.invalidate_recordset()
        self.assertEqual(adjustment.amount, 300_000.0)
        self.assertEqual(adjustment.type, "verification_gap")

    def test_an_authorized_adjustment_cannot_be_deleted(self):
        self._set_limit(1_000_000.0)
        claim = self._submitted_claim()
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 300_000.0, "reason": "Selisih.",
        })
        adjustment.with_user(self.verifier_user).action_authorize()
        with self.assertRaises(UserError):
            adjustment.unlink()

    def test_a_wrong_amount_is_corrected_by_a_new_line_not_by_editing(self):
        """Dua baris yang keduanya terbaca, bukan satu baris yang disunting."""
        self._set_limit(1_000_000.0)
        claim = self._approved_claim(approved=1_000_000.0)
        wrong = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 300_000.0,
            "reason": "Angka pertama, keliru.",
        })
        wrong.with_user(self.verifier_user).action_authorize()

        with self.assertRaises(UserError):
            wrong.write({"amount": 200_000.0})

        wrong.with_user(self.manager_user).action_cancel()
        right = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 200_000.0,
            "reason": "Koreksi atas %s." % wrong.name,
        })
        right.with_user(self.verifier_user).action_authorize()

        claim.invalidate_recordset()
        self.assertEqual(claim.adjustment_total, 200_000.0)
        self.assertEqual(len(claim.adjustment_ids), 2)
        claim.action_mark_paid(amount=800_000.0)
        self.assertEqual(claim.state, "paid")

    def test_payment_short_of_the_approved_amount_needs_an_authorized_line(self):
        self._set_limit(1_000_000.0)
        claim = self._approved_claim(approved=1_000_000.0)
        with self.assertRaises(UserError):
            claim.action_mark_paid(amount=900_000.0)

        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 100_000.0,
            "reason": "Selisih verifikasi penjamin.",
        })
        # Masih usulan: belum menutup apa pun.
        claim.invalidate_recordset()
        with self.assertRaises(UserError):
            claim.action_mark_paid(amount=900_000.0)

        adjustment.with_user(self.verifier_user).action_authorize()
        claim.invalidate_recordset()
        claim.action_mark_paid(amount=900_000.0)
        self.assertEqual(claim.state, "paid")

    def test_an_adjustment_used_to_close_a_paid_claim_cannot_be_cancelled(self):
        self._set_limit(1_000_000.0)
        claim = self._approved_claim(approved=1_000_000.0)
        adjustment = claim.with_user(self.coder_user).action_issue_adjustment({
            "type": "verification_gap", "amount": 100_000.0, "reason": "Selisih.",
        })
        adjustment.with_user(self.verifier_user).action_authorize()
        claim.invalidate_recordset()
        claim.action_mark_paid(amount=900_000.0)
        with self.assertRaises(UserError):
            adjustment.with_user(self.manager_user).action_cancel()
