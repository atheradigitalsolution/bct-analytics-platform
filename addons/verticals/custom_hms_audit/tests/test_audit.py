# -*- coding: utf-8 -*-
"""Audit logging, exercised as a real user.

TransactionCase's default environment is the superuser, and the mixin skips
superuser access on purpose — machinery reading a chart is not a person
reading a chart. Every test here therefore runs `with_user()`, which is the
only way this code path is actually covered.
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestAccessLog(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinician = cls.env["res.users"].create({
            "name": "Dokter Audit", "login": "dokter.audit.test",
            "group_ids": [
                (4, cls.env.ref("custom_hms_base.group_hms_emr_full").id),
                (4, cls.env.ref("custom_hms_base.group_hms_registration_user").id),
            ],
        })
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-AUD", "name": "Poli Audit", "type": "outpatient_clinic",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien Audit", "nik": "3201010101910077",
            "birth_date": "1991-01-01", "gender": "male",
        })
        cls.Log = cls.env["hms.access.log"]

    def _encounter_as_user(self):
        return self.env["hms.encounter"].with_user(self.clinician).create({
            "patient_id": self.patient.id,
            "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
        })

    def test_searching_the_log_does_not_raise(self):
        """Guards against ordering the model by a column it does not have."""
        self.assertEqual(self.Log.search([], limit=1).ids, self.Log.search([], limit=1).ids)

    def test_creating_an_encounter_as_a_user_is_logged(self):
        before = self.Log.search_count([("patient_id", "=", self.patient.id)])
        self._encounter_as_user()
        after = self.Log.search_count([("patient_id", "=", self.patient.id)])
        self.assertGreater(after, before)

    def test_repeated_reads_fold_into_one_row_per_day(self):
        encounter = self._encounter_as_user()
        for _ in range(5):
            # Each pass invalidates first, standing in for separate requests —
            # inside one transaction the ORM would serve the record from cache
            # and read() would never reach the mixin.
            encounter.invalidate_recordset()
            encounter.with_user(self.clinician).read(["name"])
        rows = self.Log.search([
            ("patient_id", "=", self.patient.id), ("action", "=", "read"),
            ("model_name", "=", "hms.encounter"),
        ])
        self.assertEqual(len(rows), 1, "Akses berulang harus digabung, bukan satu baris per baca.")
        self.assertGreater(rows.hit_count, 1)

    def test_superuser_machinery_is_not_logged(self):
        before = self.Log.search_count([])
        self.env["hms.encounter"].create({
            "patient_id": self.patient.id,
            "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
        })
        self.assertEqual(self.Log.search_count([]), before,
                         "Proses sistem tidak boleh mengotori jejak akses manusia.")

    def test_log_cannot_be_modified(self):
        self._encounter_as_user()
        row = self.Log.search([("patient_id", "=", self.patient.id)], limit=1)
        self.assertTrue(row)
        with self.assertRaises(AccessError):
            row.write({"action": "read"})

    def test_log_cannot_be_deleted(self):
        self._encounter_as_user()
        row = self.Log.search([("patient_id", "=", self.patient.id)], limit=1)
        with self.assertRaises(AccessError):
            row.unlink()

    def test_retention_gc_can_delete_expired_rows(self):
        self._encounter_as_user()
        row = self.Log.search([("patient_id", "=", self.patient.id)], limit=1)
        self.env.cr.execute(
            "UPDATE hms_access_log SET access_date = access_date - INTERVAL '10 years' "
            "WHERE id = %s", (row.id,)
        )
        row.invalidate_recordset()
        removed = self.Log._gc_expired(retention_days=1825)
        self.assertGreaterEqual(removed, 1)
