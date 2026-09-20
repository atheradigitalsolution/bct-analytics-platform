# -*- coding: utf-8 -*-
"""Tenggat enam bulan: datang dari parameter, dan benar-benar menolak."""
from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestClaimDeadline(CasemixCase):
    def _age_encounter(self, claim, days):
        """Geser tanggal selesai pelayanan ke masa lalu.

        Di dunia nyata yang bergerak adalah kalender, bukan ``closed_at``.
        Tes memundurkan jam dengan menulis ke kunjungan, dan sejak klaim yang
        difinalisasi mengunci kunjungannya (lihat
        ``models/hms_encounter_lock.py``) penulisan itu ditolak. Kuncinya
        dibuka sebentar khusus untuk perkakas tes ini; yang diuji tetap
        tenggat klaimnya, bukan penguncian.
        """
        encounter = claim.encounter_id
        was_locked = encounter.is_locked
        if was_locked:
            encounter.write({"is_locked": False})
        encounter.write({
            "closed_at": fields.Datetime.subtract(fields.Datetime.now(), days=days),
        })
        if was_locked:
            encounter.write({"is_locked": True})
        claim.invalidate_recordset()
        return claim

    def test_deadline_is_discharge_plus_the_parameter(self):
        settings = self.env["hms.settings"].get_settings()
        settings.claim_expiry_months = 6
        claim = self._claim()
        self.assertEqual(claim.expiry_months_applied, 6)
        self.assertEqual(
            claim.deadline_at,
            claim.discharge_at + relativedelta(months=6),
        )

    def test_changing_the_parameter_moves_the_deadline(self):
        """Ubah kebijakannya, tenggat klaim yang belum diajukan ikut bergeser."""
        settings = self.env["hms.settings"].get_settings()
        settings.claim_expiry_months = 6
        claim = self._claim()
        six_months = claim.deadline_at

        settings.claim_expiry_months = 3
        claim.invalidate_recordset()
        self.assertEqual(claim.expiry_months_applied, 3)
        self.assertEqual(
            claim.deadline_at, claim.discharge_at + relativedelta(months=3)
        )
        self.assertLess(claim.deadline_at, six_months)

    def test_a_submitted_claim_keeps_its_deadline_frozen(self):
        """Yang sudah keluar dari rumah sakit tidak ikut bergeser."""
        settings = self.env["hms.settings"].get_settings()
        settings.claim_expiry_months = 6
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        frozen = claim.deadline_at

        settings.claim_expiry_months = 3
        claim.invalidate_recordset()
        self.assertEqual(claim.expiry_months_applied, 6)
        self.assertEqual(claim.deadline_at, frozen)

    def test_zero_parameter_falls_back_to_the_statutory_six_months(self):
        settings = self.env["hms.settings"].get_settings()
        settings.claim_expiry_months = 0
        claim = self._claim()
        self.assertEqual(claim.expiry_months_applied, 6)

    def test_an_expired_claim_is_refused_at_submission(self):
        """Perpres 82/2018 Ps. 77 diwujudkan sebagai penolakan, bukan peringatan."""
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        claim.write({"batch_id": self._batch_for(claim).id})

        # Dorong tanggal pulangnya ke masa lalu sebagaimana waktu akan
        # melakukannya. Yang digeser adalah kunjungannya, bukan kolom turunan
        # di klaim: menulis langsung ke kolom computed hanya menguji ORM.
        self._age_encounter(claim, days=400)
        self.assertTrue(claim.is_expired)

        with self.assertRaises(UserError):
            claim.action_submit()
        self.assertEqual(claim.submission_count, 0)
        # Penolakan TIDAK memindahkan state-nya, dan itu disengaja: penulisan
        # yang menyertai UserError selalu ikut di-rollback. Yang memindahkannya
        # adalah cron harian — satu-satunya tempat penandaan itu bisa bertahan.
        self.assertEqual(claim.state, "finalized")
        self.env["hms.claim"]._cron_expire_claims()
        self.assertEqual(claim.state, "expired")

    def test_an_expired_claim_is_refused_at_coding_too(self):
        claim = self._claim()
        self._age_encounter(claim, days=400)
        with self.assertRaises(UserError):
            claim.action_start_coding()
        self.assertEqual(claim.state, "to_code")
        self.assertFalse(claim.coder_id)

    def test_action_expire_refuses_a_claim_that_is_still_in_time(self):
        claim = self._claim()
        with self.assertRaises(UserError):
            claim.action_expire()
        self.assertEqual(claim.state, "to_code")

    def test_resubmission_after_the_deadline_is_refused(self):
        claim = self._coded_claim()
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        claim.action_start_verification()
        claim.write({"pending_reason": "Resume tanpa tanda tangan DPJP.",
                     "pending_category": "signature"})
        claim.action_set_pending()
        claim.write({"correction_note": "Resume sudah ditandatangani."})

        self._age_encounter(claim, days=400)
        with self.assertRaises(UserError):
            claim.action_resubmit()

    def test_the_cron_sweeps_forgotten_claims(self):
        claim = self._claim()
        self._age_encounter(claim, days=400)
        self.env["hms.claim"]._cron_expire_claims()
        self.assertEqual(claim.state, "expired")
