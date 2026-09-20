# -*- coding: utf-8 -*-
"""Penguncian kunjungan saat klaim difinalisasi — dan pintu keluarnya.

Semuanya dijalankan dari **akun peran**, bukan dari superuser. Penguncian
yang hanya terbukti sebagai admin belum terbukti: admin melewati ``ir.rule``,
dan sebagian besar kegagalan penguncian yang nyata berbentuk "ternyata
penulisnya memang tidak pernah bisa menulis ke sana sejak awal", bukan
"kuncinya bekerja".
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CasemixCase


@tagged("post_install", "-at_install", "hms")
class TestEncounterLock(CasemixCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doctor_user = cls._role_user_cls(
            "zt-lock-dokter", "dr. Pengunci Uji",
            ["custom_hms_base.group_hms_emr_clinician"],
        )
        cls.medrec_manager = cls._role_user_cls(
            "zt-lock-pmik", "Kepala Rekam Medis Uji",
            ["custom_hms_medrec.group_hms_medrec_manager"],
        )
        cls.coder_user = cls._role_user_cls(
            "zt-lock-koder", "Koder Uji Kunci",
            ["custom_hms_casemix.group_hms_coder"],
        )
        # `ir.rule` CPPT membatasi klinisi pada pasien yang memang dirawatnya.
        # Tanpa tautan ini, dokter uji akan ditolak AccessError sebelum kunci
        # sempat berbicara — dan tesnya akan hijau karena alasan yang salah.
        cls.doctor.write({"user_id": cls.doctor_user.id})

    @classmethod
    @classmethod
    def _role_user_cls(cls, login, name, group_xmlids):
        return cls.env["res.users"].create({
            "name": name, "login": login,
            "group_ids": [(4, cls.env.ref(x).id) for x in group_xmlids],
        })

    # ------------------------------------------------------------------
    # Perkakas
    # ------------------------------------------------------------------
    def _encounter_with_open_note(self):
        """Kunjungan siap klaim, ditambah satu CPPT yang BELUM ditandatangani.

        Catatan yang belum ditandatangani sengaja dipakai sebagai alat ukur:
        catatan yang sudah ditandatangani memang sudah beku oleh jaminan
        append-only ``hms.clinical.note``, jadi penolakan atasnya tidak
        membuktikan apa pun tentang penguncian ini.
        """
        encounter, diagnosis = self._claimable_encounter()
        note = self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "progress",
            "subjective": "Catatan perkembangan sebelum klaim final.",
            "plan": "Observasi.",
        })
        return encounter, diagnosis, note

    def _finalize_claim_for(self, encounter):
        claim = self._claim(encounter)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id, "kind": "icd10",
            "icd10_id": self.icd_a.id, "role": "principal",
            "change_reason": "Kode uji tanpa sumber diagnosis.",
        })
        claim.action_code_done()
        claim.action_verify_internal()
        claim.action_finalize()
        return claim

    def _approved_correction(self, encounter, model_name, res_id, label="CPPT uji"):
        """Izin koreksi yang sudah disetujui PMIK, lewat alurnya sendiri."""
        request = self.env["hms.correction.request"].with_user(self.doctor_user).create({
            "encounter_id": encounter.id,
            "target_model": model_name,
            "target_res_id": res_id,
            "target_label": label,
            "field_label": "Isi catatan",
            # Jauh di luar masa tenggang; kalau tidak, action_submit menolak
            # dan menyuruh penulisnya mengoreksi sendiri.
            "entry_created_at": fields.Datetime.now() - timedelta(days=30),
            "old_value": "Catatan perkembangan sebelum klaim final.",
            "new_value": "Catatan perkembangan yang sudah dikoreksi.",
            "reason": "Salah sisi tubuh pada catatan asli.",
        })
        request.action_submit()
        request.with_user(self.medrec_manager).action_approve()
        return request

    # ------------------------------------------------------------------
    # Sebelum finalisasi: benar-benar bisa
    # ------------------------------------------------------------------
    def test_a_doctor_may_still_document_before_the_claim_is_final(self):
        encounter, diagnosis, note = self._encounter_with_open_note()
        self.assertFalse(encounter.is_locked)
        note.with_user(self.doctor_user).write({"plan": "Rencana diperbarui."})
        diagnosis.with_user(self.doctor_user).write({"note": "Keterangan tambahan."})
        self.env["hms.clinical.note"].with_user(self.doctor_user).create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "progress",
            "subjective": "Entri kedua.",
        })
        self.assertEqual(note.plan, "Rencana diperbarui.")

    # ------------------------------------------------------------------
    # Finalisasi mengunci
    # ------------------------------------------------------------------
    def test_finalizing_a_claim_locks_its_encounter(self):
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        claim = self._finalize_claim_for(encounter)
        self.assertTrue(encounter.is_locked)
        self.assertTrue(encounter.locked_at)
        self.assertEqual(encounter.locked_by_id, self.env.user)
        self.assertEqual(encounter.locking_claim_id, claim)
        self.assertIn(claim.name, encounter.lock_reason or "")

    def test_a_doctor_cannot_change_a_clinical_note_after_finalization(self):
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError):
            note.with_user(self.doctor_user).write({"plan": "Diubah diam-diam."})
        note.invalidate_recordset()
        self.assertEqual(note.plan, "Observasi.")

    def test_a_doctor_cannot_change_a_diagnosis_after_finalization(self):
        encounter, diagnosis, _note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError):
            diagnosis.with_user(self.doctor_user).write({"note": "Diubah diam-diam."})
        with self.assertRaises(UserError):
            diagnosis.with_user(self.doctor_user).write({"rank": "secondary"})

    def test_a_doctor_cannot_append_documentation_to_a_locked_encounter(self):
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError):
            self.env["hms.clinical.note"].with_user(self.doctor_user).create({
                "encounter_id": encounter.id,
                "author_id": self.doctor.id,
                "note_type": "progress",
                "subjective": "Entri susulan tanpa izin.",
            })
        with self.assertRaises(UserError):
            self.env["hms.diagnosis"].with_user(self.doctor_user).create({
                "encounter_id": encounter.id,
                "icd10_id": self.icd_b.id,
                "rank": "secondary",
            })

    def test_procedures_and_the_discharge_summary_are_locked_too(self):
        """Keduanya ikut menjadi isi klaim, jadi keduanya ikut beku."""
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        procedure = self.env["hms.procedure"].create({
            "encounter_id": encounter.id,
            "icd9_id": self.icd9_a.id,
            "name": "Tindakan uji kunci",
            "practitioner_id": self.doctor.id,
        })
        summary = self.env["hms.summary"].search(
            [("encounter_id", "=", encounter.id)], limit=1)
        self.assertTrue(summary)
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError):
            procedure.with_user(self.doctor_user).write({"complication": "Tidak ada."})
        with self.assertRaises(UserError):
            summary.with_user(self.doctor_user).write({"treatment": "Diubah."})

    def test_the_refusal_says_how_to_get_the_correction_through(self):
        """Penolakan yang tidak menyebutkan jalan keluarnya akan dimatikan orang."""
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError) as caught:
            note.with_user(self.doctor_user).write({"plan": "Diubah."})
        message = str(caught.exception)
        self.assertIn("terkunci", message.lower())
        self.assertIn("koreksi", message.lower())

    # ------------------------------------------------------------------
    # Pintu keluar
    # ------------------------------------------------------------------
    def test_an_approved_correction_request_opens_the_door(self):
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        with self.assertRaises(UserError):
            note.with_user(self.doctor_user).write({"plan": "Diubah."})

        self._approved_correction(encounter, "hms.clinical.note", note.id)
        note.with_user(self.doctor_user).write({"plan": "Rencana yang dikoreksi."})
        note.invalidate_recordset()
        self.assertEqual(note.plan, "Rencana yang dikoreksi.")

    def test_an_approved_correction_also_allows_the_addendum_entry(self):
        """Koreksi RME ditulis sebagai entri baru, bukan menimpa yang lama."""
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        self._approved_correction(encounter, "hms.clinical.note", note.id)
        addendum = self.env["hms.clinical.note"].with_user(self.doctor_user).create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "progress",
            "subjective": "Adendum atas catatan sebelumnya.",
        })
        self.assertTrue(addendum.id)

    def test_a_correction_that_is_only_submitted_does_not_open_anything(self):
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        request = self.env["hms.correction.request"].with_user(self.doctor_user).create({
            "encounter_id": encounter.id,
            "target_model": "hms.clinical.note",
            "target_res_id": note.id,
            "target_label": "CPPT uji",
            "field_label": "Isi catatan",
            "entry_created_at": fields.Datetime.now() - timedelta(days=30),
            "old_value": "Observasi.",
            "new_value": "Observasi ketat.",
            "reason": "Belum disetujui siapa pun.",
        })
        request.action_submit()
        self.assertEqual(request.state, "submitted")
        with self.assertRaises(UserError):
            note.with_user(self.doctor_user).write({"plan": "Diubah."})

    def test_the_door_only_opens_for_the_record_the_permission_names(self):
        encounter, diagnosis, note = self._encounter_with_open_note()
        other_note = self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "progress",
            "subjective": "Catatan lain.",
        })
        self._finalize_claim_for(encounter)
        self._approved_correction(encounter, "hms.clinical.note", note.id)

        note.with_user(self.doctor_user).write({"plan": "Boleh."})
        with self.assertRaises(UserError):
            other_note.with_user(self.doctor_user).write({"plan": "Tidak boleh."})
        with self.assertRaises(UserError):
            diagnosis.with_user(self.doctor_user).write({"note": "Tidak boleh."})

    def test_marking_the_correction_applied_closes_the_door_again(self):
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        request = self._approved_correction(encounter, "hms.clinical.note", note.id)
        note.with_user(self.doctor_user).write({"plan": "Perbaikan pertama."})

        request.write({"addendum_reference": "CPPT adendum 1"})
        request.action_mark_applied()
        self.assertEqual(request.state, "applied")
        with self.assertRaises(UserError):
            note.with_user(self.doctor_user).write({"plan": "Perbaikan kedua."})

    def test_the_permission_is_read_beyond_the_callers_own_slice(self):
        """Gerbang yang membaca dengan hak akses pemanggil salah diam-diam.

        ``ir.rule`` membatasi staf pada permintaan koreksi yang ia ajukan
        sendiri. Kalau keberadaan izin dibaca dengan hak pemanggil, koreksi
        yang diminta dokter tidak akan pernah bisa diterapkan oleh siapa pun
        selain dokter itu — dan pintunya tampak rusak tanpa sebab.
        """
        encounter, _diagnosis, note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        request = self._approved_correction(encounter, "hms.clinical.note", note.id)
        self.assertEqual(request.requested_by_id, self.doctor_user)

        # Akses rekam medis penuh: yang diuji adalah keberadaan izin, bukan
        # `ir.rule` CPPT yang membatasi klinisi pada pasiennya sendiri.
        other_doctor = self._role_user_cls(
            "zt-lock-dokter-2", "dr. Pelaksana Koreksi",
            ["custom_hms_base.group_hms_emr_full"],
        )
        self.assertFalse(
            self.env["hms.correction.request"].with_user(other_doctor).search_count(
                [("id", "=", request.id)]
            )
        )
        note.with_user(other_doctor).write({"plan": "Diterapkan rekan sejawat."})

    # ------------------------------------------------------------------
    # Pagar: yang TIDAK boleh ikut terkunci
    # ------------------------------------------------------------------
    def test_the_lock_does_not_block_casemix_work(self):
        """Pekerjaan yang mengunci tidak boleh ikut terkunci.

        Diuji lewat klaim KEDUA atas kunjungan yang sama (INA-CBG dan Non
        INA-CBG diajukan terpisah, Permenkes 3/2023 Ps. 36): kunjungannya
        sudah terkunci oleh klaim pertama, dan koding klaim kedua tetap harus
        berjalan penuh dari akun koder sungguhan.
        """
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        first = self._finalize_claim_for(encounter)
        self.assertTrue(encounter.is_locked)

        second = self._claim(encounter, kind="bpjs_non_inacbg")
        second.with_user(self.coder_user).action_start_coding()
        code = self.Code.with_user(self.coder_user).create({
            "claim_id": second.id, "kind": "icd10",
            "icd10_id": self.icd_b.id, "role": "principal",
            "change_reason": "Kode klaim non INA-CBG.",
        })
        code.with_user(self.coder_user).write({"seq": 20})
        self.env["hms.coding.query"].with_user(self.coder_user).create({
            "claim_id": second.id,
            "topic": "definitive",
            "question": "Komorbid ini definitif?",
            "addressed_to_id": self.doctor.id,
        })
        self.assertEqual(second.state, "coding")

        batch = self._batch_for(first)
        first.write({"batch_id": batch.id})
        first.action_submit()
        self.assertEqual(first.state, "submitted")

    def test_the_lock_does_not_block_adjustments(self):
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        claim = self._finalize_claim_for(encounter)
        claim.write({"batch_id": self._batch_for(claim).id})
        claim.action_submit()
        adjustment = claim.action_issue_adjustment({
            "type": "verification_gap",
            "amount": 100_000.0,
            "reason": "Selisih verifikasi penjamin.",
        })
        self.assertEqual(adjustment.claim_id, claim)
        self.assertEqual(adjustment.encounter_id, encounter)

    def test_the_lock_does_not_block_klpcm_from_closing_findings(self):
        """KLPCM mengaudit berkas; ia tidak mengubah isinya."""
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        self._finalize_claim_for(encounter)
        finding = self.env["hms.klpcm"].create({
            "encounter_id": encounter.id,
            "component": "summary",
            "kind": "qualitative",
            "detail": "Resume tidak konsisten dengan CPPT.",
            "auto_detected": False,
        })
        finding.write({"state": "completed", "closed_at": fields.Datetime.now()})
        self.assertEqual(finding.state, "completed")
        # Analisis ulang atas kunjungan terkunci juga harus tetap jalan.
        encounter.action_reanalyze_klpcm()

    def test_locking_twice_is_harmless_and_keeps_the_first_reason(self):
        """Kunjungan bisa punya dua klaim (INA-CBG dan Non INA-CBG)."""
        encounter, _diagnosis, _note = self._encounter_with_open_note()
        first = self._finalize_claim_for(encounter)
        reason = encounter.lock_reason
        second = self._claim(encounter, kind="bpjs_non_inacbg")
        second.action_start_coding()
        self.Code.create({
            "claim_id": second.id, "kind": "icd10",
            "icd10_id": self.icd_a.id, "role": "principal",
            "change_reason": "Kode uji.",
        })
        second.action_code_done()
        second.action_verify_internal()
        second.action_finalize()
        self.assertEqual(encounter.lock_reason, reason)
        self.assertEqual(encounter.locking_claim_id, first)
