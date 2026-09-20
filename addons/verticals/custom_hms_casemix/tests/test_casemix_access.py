# -*- coding: utf-8 -*-
"""Batas akses casemix dari akun peran nyata.

Pusat perhatiannya satu: **koder tidak boleh punya hak tulis ke
``hms.diagnosis``**. Itulah yang membuat pemisahan koding dari diagnosis
klinis menjadi jaminan sistem, bukan sekadar konvensi penulisan kode.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestCasemixAccess(CasemixCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coder = cls.env["res.users"].create({
            "name": "Koder Akses", "login": "zt-acl-koder",
            "group_ids": [(4, cls.env.ref("custom_hms_casemix.group_hms_coder").id)],
        })
        cls.verifier = cls.env["res.users"].create({
            "name": "Verifikator Akses", "login": "zt-acl-verifikator",
            "group_ids": [(4, cls.env.ref(
                "custom_hms_casemix.group_hms_casemix_verifier").id)],
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Manajer Akses Casemix", "login": "zt-acl-manajer-cm",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_manager").id)],
        })
        cls.nurse_user = cls.env["res.users"].create({
            "name": "Perawat Akses Casemix", "login": "zt-acl-perawat-cm",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_nurse").id)],
        })

    def test_a_coder_cannot_write_to_the_doctors_diagnosis(self):
        """Pagar terpentingnya bukan di kode modul ini, melainkan di hak akses."""
        _encounter, diagnosis = self._claimable_encounter()
        self.assertFalse(
            self.coder.has_group("custom_hms_base.group_hms_emr_clinician")
        )
        with self.assertRaises(AccessError):
            diagnosis.with_user(self.coder).write({"icd10_id": self.icd_b.id})
        with self.assertRaises(AccessError):
            self.env["hms.diagnosis"].with_user(self.coder).create({
                "encounter_id": _encounter.id,
                "icd10_id": self.icd_b.id,
                "rank": "secondary",
            })

    def test_a_coder_can_read_the_diagnosis_they_code_from(self):
        _encounter, diagnosis = self._claimable_encounter()
        self.assertTrue(diagnosis.with_user(self.coder).icd10_id)

    def test_a_coder_may_write_claim_codes(self):
        encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter)
        claim.with_user(self.coder).action_start_coding()
        code = self.Code.with_user(self.coder).create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id, "role": "principal",
            "source_diagnosis_id": diagnosis.id,
        })
        self.assertEqual(code.create_uid, self.coder)

    def test_the_klpcm_gate_also_fires_for_a_real_coder_account(self):
        """Gerbang yang diuji sebagai admin belum tentu gerbang.

        Kalau koder tidak berhak membaca ``hms.klpcm``, ``search`` miliknya
        mengembalikan kosong dan gerbangnya LOLOS tanpa satu pun pesan galat —
        kegagalan senyap yang paling mahal di modul ini. Karena itu hak baca
        KLPCM diberikan selebar mungkin, dan dibuktikan di sini dari akun
        koder sungguhan, bukan dari superuser.
        """
        encounter = self._encounter()
        encounter.action_close()
        self.assertGreater(encounter.klpcm_open_count, 0)
        self.assertTrue(
            self.env["hms.klpcm"].with_user(self.coder).search_count(
                [("encounter_id", "=", encounter.id), ("state", "=", "open")]
            ),
            "Koder tidak bisa membaca KLPCM — gerbang koding akan lolos senyap.",
        )
        claim = self._claim(encounter)
        with self.assertRaises(UserError):
            claim.with_user(self.coder).action_start_coding()
        self.assertEqual(claim.state, "to_code")

    def test_a_nurse_cannot_create_a_claim(self):
        encounter, _diagnosis = self._claimable_encounter()
        with self.assertRaises(AccessError):
            self.Claim.with_user(self.nurse_user).create({
                "encounter_id": encounter.id,
                "payer_id": encounter.payer_id.id,
            })

    def test_a_nurse_cannot_read_claim_codes(self):
        claim = self._coded_claim()
        with self.assertRaises(AccessError):
            claim.code_ids.with_user(self.nurse_user).icd10_id

    def test_a_doctor_sees_only_the_codes_of_their_own_encounters(self):
        claim = self._coded_claim()
        doctor_user = self._role_user(
            "zt-acl-dpjp-cm", "DPJP Casemix",
            ["custom_hms_base.group_hms_emr_clinician"],
        )
        visible = self.Code.with_user(doctor_user).search([])
        self.assertNotIn(claim.code_ids[0], visible)

        self.doctor.write({"user_id": doctor_user.id})
        visible = self.Code.with_user(doctor_user).search([])
        self.assertIn(claim.code_ids[0], visible)

    def test_a_coder_cannot_authorise_an_adjustment(self):
        claim = self._coded_claim()
        adjustment = self.env["hms.claim.adjustment"].with_user(self.coder).create({
            "claim_id": claim.id, "type": "penalty", "amount": 50_000.0,
            "reason": "Denda keterlambatan.",
        })
        with self.assertRaises(UserError):
            adjustment.with_user(self.coder).action_authorize()
        adjustment.with_user(self.manager).action_authorize()
        self.assertEqual(adjustment.state, "authorized")

    def test_a_dpjp_may_only_answer_queries_addressed_to_them(self):
        claim = self._coded_claim()
        other_doctor = self.env["hms.practitioner"].create({
            "name": "Dokter Lain", "type": "doctor", "nik": "3201014501860099",
        })
        other_user = self._role_user(
            "zt-acl-dpjp-lain", "DPJP Lain",
            ["custom_hms_base.group_hms_emr_clinician"],
        )
        other_doctor.write({"user_id": other_user.id})
        query = self.env["hms.coding.query"].create({
            "claim_id": claim.id, "topic": "specificity",
            "question": "Kode mana yang dimaksud?",
            "addressed_to_id": self.doctor.id,
        })
        with self.assertRaises(AccessError):
            query.with_user(other_user).write({"answer": "Jawaban dari dokter lain."})

        self.doctor.write({"user_id": other_user.id})
        query.with_user(other_user).write({"answer": "Jawaban yang sah."})
        self.assertTrue(query.answer)

    def test_medical_records_may_audit_codes_but_not_change_them(self):
        claim = self._coded_claim()
        pmik = self._role_user(
            "zt-acl-pmik-cm", "PMIK Casemix",
            ["custom_hms_medrec.group_hms_medrec"],
        )
        self.assertTrue(claim.code_ids.with_user(pmik).code_display)
        with self.assertRaises(AccessError):
            claim.code_ids.with_user(pmik).write({"seq": 99})
