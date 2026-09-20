# -*- coding: utf-8 -*-
"""Batas akses rekam medis, dibuktikan dari akun peran nyata.

``TransactionCase`` menjalankan ``self.env`` sebagai superuser, dan superuser
melewati seluruh ``ir.model.access`` maupun ``ir.rule``. Semua pemeriksaan di
berkas ini karena itu memakai ``.with_user(...)``: menguji batas akses sebagai
administrator tidak membuktikan apa pun.
"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestMedrecAccess(MedrecCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pmik = cls.env["res.users"].create({
            "name": "PMIK Akses", "login": "zt-acl-pmik",
            "group_ids": [(4, cls.env.ref("custom_hms_medrec.group_hms_medrec").id)],
        })
        cls.head = cls.env["res.users"].create({
            "name": "Kepala RM Akses", "login": "zt-acl-kepala",
            "group_ids": [(4, cls.env.ref(
                "custom_hms_medrec.group_hms_medrec_manager").id)],
        })
        cls.manager = cls.env["res.users"].create({
            "name": "Pimpinan Akses", "login": "zt-acl-pimpinan",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_manager").id)],
        })
        cls.nurse_user = cls.env["res.users"].create({
            "name": "Perawat Akses", "login": "zt-acl-perawat",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_nurse").id)],
        })
        cls.cashier = cls.env["res.users"].create({
            "name": "Kasir Akses", "login": "zt-acl-kasir",
            "group_ids": [(4, cls.env.ref("custom_hms_base.group_hms_cashier").id)],
        })

    # --- KLPCM ------------------------------------------------------------
    def test_a_nurse_can_read_klpcm_but_not_create_it(self):
        """Baca lebar (gerbang tidak boleh gagal senyap), tulis sempit."""
        encounter = self._encounter()
        encounter.action_close()
        finding = encounter.klpcm_ids[0]
        self.assertTrue(finding.with_user(self.nurse_user).component)
        with self.assertRaises(AccessError):
            self.env["hms.klpcm"].with_user(self.nurse_user).create({
                "encounter_id": encounter.id, "component": "cppt",
            })

    def test_a_cashier_cannot_create_klpcm_either(self):
        encounter = self._encounter()
        encounter.action_close()
        with self.assertRaises(AccessError):
            self.env["hms.klpcm"].with_user(self.cashier).create({
                "encounter_id": encounter.id, "component": "summary",
            })

    def test_medical_records_staff_may_add_a_qualitative_finding(self):
        encounter = self._encounter()
        encounter.action_close()
        finding = self.env["hms.klpcm"].with_user(self.pmik).create({
            "encounter_id": encounter.id,
            "component": "initial_medical",
            "kind": "qualitative",
            "detail": "Diagnosis resume tidak konsisten dengan CPPT.",
            "auto_detected": False,
        })
        self.assertEqual(finding.kind, "qualitative")

    def test_nobody_may_delete_a_klpcm_finding(self):
        encounter = self._encounter()
        encounter.action_close()
        finding = encounter.klpcm_ids[0]
        for user in (self.pmik, self.head, self.manager):
            with self.assertRaises(UserError):
                finding.with_user(user).unlink()

    # --- ROI --------------------------------------------------------------
    def test_a_cashier_cannot_read_disclosure_requests(self):
        request = self.env["hms.roi.request"].create({
            "patient_id": self.patient.id,
            "requester_type": "law_enforcement",
            "requester_name": "Penyidik Uji",
            "purpose": "Penyidikan.",
            "legal_basis": "art35",
        })
        with self.assertRaises(AccessError):
            request.with_user(self.cashier).purpose

    def test_medical_records_staff_cannot_approve_a_disclosure(self):
        """Ps. 34 ayat (2): yang menyetujui adalah pimpinan, bukan unit RM."""
        request = self.env["hms.roi.request"].create({
            "patient_id": self.patient.id,
            "requester_type": "law_enforcement",
            "requester_name": "Penyidik Uji",
            "purpose": "Penyidikan.",
            "legal_basis": "art35",
        })
        request.action_submit()
        with self.assertRaises(UserError):
            request.with_user(self.pmik).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.head).action_approve()
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, "approved")

    # --- koreksi ----------------------------------------------------------
    def test_a_nurse_sees_only_their_own_correction_requests(self):
        """Isi permintaan memuat kutipan catatan klinis pasien secara utuh."""
        encounter = self._encounter()
        mine = self.env["hms.correction.request"].with_user(self.nurse_user).create({
            "encounter_id": encounter.id,
            "target_model": "hms.clinical.note", "target_res_id": 1,
            "target_label": "CPPT", "field_label": "A",
            "entry_created_at": "2026-01-01 00:00:00",
            "old_value": "a", "new_value": "b", "reason": "salah ketik",
        })
        theirs = self.env["hms.correction.request"].with_user(self.pmik).create({
            "encounter_id": encounter.id,
            "target_model": "hms.clinical.note", "target_res_id": 2,
            "target_label": "CPPT lain", "field_label": "A",
            "entry_created_at": "2026-01-01 00:00:00",
            "old_value": "c", "new_value": "d", "reason": "salah ketik",
        })
        visible = self.env["hms.correction.request"].with_user(self.nurse_user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    # --- retensi ----------------------------------------------------------
    def test_a_plain_clerk_cannot_change_the_retention_rule(self):
        rule = self.env["hms.retention.rule"].create({
            "name": "Retensi ACL", "scope": "outpatient",
        })
        with self.assertRaises(AccessError):
            rule.with_user(self.pmik).write({"retention_years": 40})
        rule.with_user(self.head).write({"retention_years": 40})
        self.assertEqual(rule.retention_years, 40)

    # --- surat ------------------------------------------------------------
    def test_a_cashier_cannot_create_a_medical_letter(self):
        with self.assertRaises(AccessError):
            self.env["hms.medical.letter"].with_user(self.cashier).create({
                "type": "fit", "patient_id": self.patient.id,
                "practitioner_id": self.doctor.id, "body": "Sehat.",
            })
