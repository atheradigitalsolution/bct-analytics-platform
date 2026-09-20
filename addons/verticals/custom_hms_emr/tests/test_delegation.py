# -*- coding: utf-8 -*-
"""Pelimpahan wewenang: pertanyaan "berwenang atau tidak" harus punya jawaban.

Sebuah pelimpahan yang hanya berupa formulir tersimpan tidak menghentikan
apa pun. Yang diuji di sini adalah pemeriksaannya — terutama di luar masa
berlaku, karena di situlah sistem yang cuma menyimpan formulir akan menjawab
"boleh" dengan yakin.
"""
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.tools import mute_logger
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestDelegation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Ratna Sari", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501860041",
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Budi Santoso", "type": "nurse", "nik": "3201010101860042",
        })
        cls.other_nurse = cls.env["hms.practitioner"].create({
            "name": "Siti Aminah", "type": "nurse", "nik": "3201014501860043",
        })
        cls.infusion = cls.env["hms.icd9"].create({
            "code": "ZT-99.18", "name": "Pemasangan infus intravena",
        })
        cls.suture = cls.env["hms.icd9"].create({
            "code": "ZT-86.59", "name": "Penjahitan luka kulit",
        })
        cls.Delegation = cls.env["hms.delegation"]
        cls.today = fields.Date.context_today(cls.Delegation)

    def _delegation(self, **vals):
        base = {
            "doctor_id": self.doctor.id,
            "nurse_id": self.nurse.id,
            "kind": "delegative",
            "procedure_ids": [(6, 0, [self.infusion.id])],
            "valid_from": self.today - timedelta(days=1),
            "valid_until": self.today + timedelta(days=30),
        }
        base.update(vals)
        return self.Delegation.create(base)

    # --- masa berlaku -----------------------------------------------------
    def test_authorized_inside_the_validity_window(self):
        delegation = self._delegation()
        delegation.action_activate()
        found = self.Delegation.check_authorization(
            self.nurse, self.infusion, self.today
        )
        self.assertEqual(found, delegation)
        self.assertTrue(delegation.is_currently_valid)

    def test_refused_before_the_validity_window(self):
        delegation = self._delegation(
            valid_from=self.today + timedelta(days=5),
            valid_until=self.today + timedelta(days=20),
        )
        delegation.action_activate()
        self.assertFalse(
            self.Delegation.check_authorization(self.nurse, self.infusion, self.today)
        )
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.nurse, self.infusion, self.today)

    def test_refused_after_the_validity_window(self):
        """Inti pemeriksaan: tanggal diuji, bukan hanya state."""
        delegation = self._delegation(
            valid_from=self.today - timedelta(days=40),
            valid_until=self.today - timedelta(days=1),
        )
        delegation.action_activate()
        self.assertEqual(delegation.state, "active")
        self.assertFalse(delegation.is_currently_valid)
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.nurse, self.infusion, self.today)

    def test_authorization_is_asked_for_a_specific_date(self):
        delegation = self._delegation(
            valid_from=self.today - timedelta(days=10),
            valid_until=self.today - timedelta(days=5),
        )
        delegation.action_activate()
        self.assertTrue(self.Delegation.check_authorization(
            self.nurse, self.infusion, self.today - timedelta(days=7)
        ))
        self.assertFalse(self.Delegation.check_authorization(
            self.nurse, self.infusion, self.today
        ))

    # --- lingkup dan orang -------------------------------------------------
    def test_refused_for_a_procedure_outside_the_scope(self):
        delegation = self._delegation()
        delegation.action_activate()
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.nurse, self.suture, self.today)

    def test_refused_for_a_different_nurse(self):
        delegation = self._delegation()
        delegation.action_activate()
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.other_nurse, self.infusion, self.today)

    def test_draft_delegation_authorizes_nothing(self):
        self._delegation()
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.nurse, self.infusion, self.today)

    def test_revoked_delegation_authorizes_nothing(self):
        delegation = self._delegation()
        delegation.action_activate()
        delegation.revoke_reason = "Perawat pindah unit."
        delegation.action_revoke()
        self.assertEqual(delegation.state, "revoked")
        with self.assertRaises(UserError):
            self.Delegation.assert_authorized(self.nurse, self.infusion, self.today)

    def test_revoking_requires_a_reason(self):
        delegation = self._delegation()
        delegation.action_activate()
        with self.assertRaises(UserError):
            delegation.action_revoke()

    # --- bentuk tertulis --------------------------------------------------
    def test_active_delegation_must_state_its_scope(self):
        delegation = self._delegation(procedure_ids=[(5, 0, 0)], scope_note=False)
        with self.assertRaises(ValidationError):
            delegation.action_activate()

    def test_scope_note_alone_is_enough_for_uncoded_nursing_acts(self):
        delegation = self._delegation(
            procedure_ids=[(5, 0, 0)],
            scope_note="Perawatan luka dekubitus derajat II sesuai SPO unit.",
        )
        delegation.action_activate()
        self.assertEqual(delegation.state, "active")
        self.assertTrue(self.Delegation.check_authorization(self.nurse, None, self.today))

    def test_mandate_requires_supervision_by_default(self):
        delegation = self._delegation(kind="mandate")
        self.assertTrue(delegation.supervision_required)
        delegation.kind = "delegative"
        self.assertFalse(delegation.supervision_required)

    def test_end_date_cannot_precede_start_date(self):
        """Dijaga Postgres, bukan hanya Python.

        Odoo 19 mengabaikan atribut constraint SQL gaya lama secara diam-diam;
        `models.Constraint` adalah satu-satunya bentuk yang benar-benar
        membuat constraint di Postgres, dan satu-satunya cara membuktikannya
        adalah melanggarnya.
        """
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self._delegation(
                valid_from=self.today,
                valid_until=self.today - timedelta(days=1),
            )
            self.env.flush_all()

    def test_doctor_and_nurse_must_differ(self):
        with self.assertRaises(ValidationError):
            self._delegation(nurse_id=self.doctor.id)

    # --- penyapuan --------------------------------------------------------
    def test_cron_marks_lapsed_delegations_expired(self):
        delegation = self._delegation(
            valid_from=self.today - timedelta(days=40),
            valid_until=self.today - timedelta(days=2),
        )
        delegation.action_activate()
        self.Delegation._cron_expire()
        self.assertEqual(delegation.state, "expired")

    def test_cron_leaves_current_delegations_alone(self):
        delegation = self._delegation()
        delegation.action_activate()
        self.Delegation._cron_expire()
        self.assertEqual(delegation.state, "active")

    def test_number_is_sequenced(self):
        delegation = self._delegation()
        self.assertTrue(delegation.name.startswith("DLG-"), delegation.name)
