# -*- coding: utf-8 -*-
"""Gerbang KLPCM: berkas tidak lengkap benar-benar menahan koding klaim."""
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestKlpcmGate(CasemixCase):
    def test_an_incomplete_encounter_cannot_enter_coding(self):
        """Inti gelombang ini: KLPCM adalah gerbang, bukan laporan."""
        encounter = self._encounter()
        encounter.action_close()
        self.assertGreater(encounter.klpcm_open_count, 0)

        claim = self._claim(encounter)
        with self.assertRaises(UserError):
            claim.action_start_coding()
        self.assertEqual(claim.state, "to_code")
        self.assertFalse(claim.coder_id)

    def test_the_same_encounter_may_be_coded_once_the_findings_close(self):
        """Dan gerbangnya benar-benar membuka, bukan menolak selamanya."""
        encounter = self._encounter()
        encounter.action_close()
        claim = self._claim(encounter)
        with self.assertRaises(UserError):
            claim.action_start_coding()

        # Lengkapi berkasnya seperti PPA sungguhan: entri baru, lalu analisis
        # ulang menutup temuannya sendiri.
        self._complete_documents(encounter)
        encounter.action_reanalyze_klpcm()
        self.assertEqual(encounter.klpcm_open_count, 0)

        claim.action_start_coding()
        self.assertEqual(claim.state, "coding")
        self.assertEqual(claim.coder_id, self.env.user)

    def test_the_refusal_names_the_missing_components(self):
        """Pesan yang hanya bilang 'berkas belum lengkap' tidak menolong siapa pun."""
        encounter = self._encounter()
        encounter.action_close()
        claim = self._claim(encounter)
        with self.assertRaises(UserError) as caught:
            claim.action_start_coding()
        message = str(caught.exception)
        self.assertIn("KLPCM", message)
        self.assertIn("resume", message.lower())

    def test_an_encounter_still_being_served_cannot_be_claimed(self):
        encounter = self._encounter()
        with self.assertRaises(UserError):
            self.Claim.create_for_encounter(encounter)

    def test_a_qualitative_finding_also_holds_the_gate(self):
        """Temuan analisis kualitatif bukan catatan pinggir; ia ikut menahan."""
        encounter, _diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        self.env["hms.klpcm"].create({
            "encounter_id": encounter.id,
            "component": "summary",
            "kind": "qualitative",
            "detail": "Diagnosis pada resume tidak konsisten dengan CPPT.",
            "auto_detected": False,
        })
        with self.assertRaises(UserError):
            claim.action_start_coding()
