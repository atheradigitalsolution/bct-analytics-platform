# -*- coding: utf-8 -*-
"""Penyusunan isi batch: yang boleh masuk, dan yang ditolak dengan sebabnya.

``TestClaimBatch`` di ``test_claim_lifecycle.py`` sudah menguji pengajuan dan
rekonsiliasi. Yang diuji di sini adalah lapisan sebelum itu — bagaimana klaim
sampai ke dalam batch — karena justru di situ layar batch bisa menawarkan
sesuatu yang kemudian ditolak.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestClaimBatchCompose(CasemixCase):
    def _finalized(self, **kw):
        encounter, diagnosis = self._claimable_encounter(**kw)
        claim = self._coded_claim(encounter, diagnosis)
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        return claim

    def test_collecting_pulls_every_matching_final_claim(self):
        claim = self._finalized()
        batch = self._batch_for(claim)
        self.assertIn(claim, batch.candidate_claims())
        batch.action_collect_claims()
        self.assertIn(claim, batch.claim_ids)
        self.assertEqual(claim.batch_id, batch)

    def test_collecting_an_empty_period_is_refused_with_a_reason(self):
        """Batch kosong yang 'berhasil disusun' adalah kebohongan kecil."""
        claim = self._finalized()
        batch = self._batch_for(claim)
        batch.action_collect_claims()
        second = self._batch_for(claim, batch_type="supplementary")
        with self.assertRaises(UserError):
            second.action_collect_claims()

    def test_a_claim_that_is_not_final_cannot_be_added(self):
        claim = self._coded_claim()
        batch = self._batch_for(claim)
        self.assertNotIn(claim, batch.candidate_claims())
        with self.assertRaises(UserError) as caught:
            batch.action_add_claims([claim.id])
        self.assertIn("Final", str(caught.exception))
        self.assertFalse(claim.batch_id)

    def test_a_claim_of_the_wrong_care_type_cannot_be_added(self):
        claim = self._finalized()
        batch = self._batch_for(claim, care_type="inpatient")
        with self.assertRaises(UserError):
            batch.action_add_claims([claim.id])

    def test_a_claim_already_in_another_batch_cannot_be_taken(self):
        claim = self._finalized()
        first = self._batch_for(claim)
        first.action_add_claims([claim.id])
        second = self._batch_for(claim, batch_type="supplementary")
        with self.assertRaises(UserError):
            second.action_add_claims([claim.id])
        self.assertEqual(claim.batch_id, first)

    def test_a_claim_may_be_taken_out_again_while_the_batch_is_draft(self):
        claim = self._finalized()
        batch = self._batch_for(claim)
        batch.action_add_claims([claim.id])
        batch.action_remove_claims([claim.id])
        self.assertFalse(claim.batch_id)

    def test_a_submitted_batch_refuses_further_composition(self):
        claim = self._finalized()
        batch = self._batch_for(claim)
        batch.action_add_claims([claim.id])
        batch.action_submit()
        other = self._finalized()
        for call in (lambda: batch.action_add_claims([other.id]),
                     lambda: batch.action_remove_claims([claim.id]),
                     batch.action_collect_claims):
            with self.assertRaises(UserError):
                call()

    def test_collecting_never_takes_a_claim_from_another_payer(self):
        claim = self._finalized()
        other_payer = self.env["hms.payer"].create({
            "code": "ZT-CM-PAYER", "name": "Penjamin Uji Batch", "type": "insurance",
        })
        batch = self._batch_for(claim, payer_id=other_payer.id)
        self.assertNotIn(claim, batch.candidate_claims())
        with self.assertRaises(UserError):
            batch.action_collect_claims()

    def test_a_duplicate_batch_key_is_refused_with_a_sentence(self):
        """Constraint Postgres tetap penjaganya; ini soal pesannya.

        ``IntegrityError`` yang lolos ke batas API keluar sebagai 500 tanpa
        keterangan, dan petugas yang menyusun batch yang sudah pernah dibuat
        adalah kejadian sehari-hari — bukan kejadian langka yang pantas
        dijawab "hubungi administrator".
        """
        claim = self._finalized()
        first = self._batch_for(claim)
        with self.assertRaises(ValidationError) as caught:
            self._batch_for(claim)
        message = str(caught.exception)
        self.assertIn(first.name, message)
        self.assertIn("susulan", message.lower())

    def test_the_same_key_is_free_again_for_a_supplementary_file(self):
        claim = self._finalized()
        self._batch_for(claim)
        supplementary = self._batch_for(claim, batch_type="supplementary")
        self.assertTrue(supplementary.id)
