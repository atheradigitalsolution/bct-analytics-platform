# -*- coding: utf-8 -*-
"""Registration flow: numbering, duplicate guards, triage, SEP queueing."""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestRegistration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-PD", "name": "Poli Penyakit Dalam", "type": "outpatient_clinic",
        })
        cls.er = cls.env["hms.unit"].create({
            "code": "ZT-IGD", "name": "Instalasi Gawat Darurat", "type": "emergency",
        })
        cls.payer_self = cls.env.ref("custom_hms_base.payer_self")
        cls.payer_bpjs = cls.env["hms.payer"].create({
            "code": "ZT-BPJS", "name": "BPJS Kesehatan", "type": "bpjs", "requires_sep": True,
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Andi Wijaya", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101800001", "unit_ids": [(4, cls.unit.id)],
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Budi Santoso", "nik": "3201010101900001",
            "birth_date": "1990-01-01", "gender": "male",
        })
        cls.Encounter = cls.env["hms.encounter"]

    def _encounter_vals(self, **kw):
        vals = {
            "patient_id": self.patient.id,
            "unit_id": self.unit.id,
            "payer_id": self.payer_self.id,
            "practitioner_id": self.doctor.id,
        }
        vals.update(kw)
        return vals

    def test_encounter_number_follows_the_daily_pattern(self):
        enc = self.Encounter.create(self._encounter_vals())
        stamp = fields.Datetime.context_timestamp(enc, enc.arrival_at).strftime("%Y%m%d")
        self.assertTrue(enc.name.startswith(f"KJ-{stamp}-"), enc.name)

    def test_registration_updates_patient_visit_counters(self):
        self.assertEqual(self.patient.visit_count, 0)
        self.Encounter.create(self._encounter_vals())
        self.assertEqual(self.patient.visit_count, 1)
        self.assertEqual(self.patient.first_visit_date, fields.Date.context_today(self.patient))

    def test_second_open_encounter_same_unit_same_day_is_refused(self):
        self.Encounter.create(self._encounter_vals())
        with self.assertRaises(ValidationError):
            self.Encounter.create(self._encounter_vals())

    def test_second_encounter_allowed_in_a_different_unit(self):
        other = self.env["hms.unit"].create({
            "code": "ZT-POLI-ANAK", "name": "Poli Anak", "type": "outpatient_clinic",
        })
        self.Encounter.create(self._encounter_vals())
        second = self.Encounter.create(self._encounter_vals(unit_id=other.id))
        self.assertTrue(second.id)

    def test_second_encounter_allowed_once_the_first_is_closed(self):
        first = self.Encounter.create(self._encounter_vals())
        first.action_close()
        second = self.Encounter.create(self._encounter_vals())
        self.assertTrue(second.id)

    def test_emergency_requires_triage(self):
        with self.assertRaises(ValidationError):
            self.Encounter.create(self._encounter_vals(unit_id=self.er.id, type="emergency"))

    def test_emergency_with_triage_registers(self):
        enc = self.Encounter.create(self._encounter_vals(
            unit_id=self.er.id, type="emergency", triage_level="yellow",
        ))
        self.assertEqual(enc.triage_level, "yellow")

    def test_bpjs_payer_queues_a_sep_job(self):
        self.patient.bpjs_no = "0001234567890"
        enc = self.Encounter.create(self._encounter_vals(payer_id=self.payer_bpjs.id))
        self.assertEqual(enc.sep_state, "pending")
        job = self.env["hms.job"].search([
            ("name", "=", "bpjs.sep.create"), ("res_id", "=", enc.id),
        ])
        self.assertEqual(len(job), 1)
        self.assertEqual(job.state, "pending")

    def test_bpjs_without_card_number_fails_loudly_but_still_registers(self):
        """The desk must not be blocked; the problem becomes a visible state."""
        enc = self.Encounter.create(self._encounter_vals(payer_id=self.payer_bpjs.id))
        self.assertEqual(enc.sep_state, "failed")
        self.assertTrue(enc.sep_error)
        self.assertEqual(enc.state, "registered")

    def test_self_pay_never_asks_for_a_sep(self):
        enc = self.Encounter.create(self._encounter_vals())
        self.assertEqual(enc.sep_state, "none")

    def test_registration_emits_an_event(self):
        before = self.env["hms.event"].search_count([("topic", "=", "encounter.registered")])
        self.Encounter.create(self._encounter_vals())
        after = self.env["hms.event"].search_count([("topic", "=", "encounter.registered")])
        self.assertEqual(after, before + 1)

    def test_state_machine_rejects_out_of_order_transitions(self):
        enc = self.Encounter.create(self._encounter_vals())
        enc.action_close()
        with self.assertRaises(UserError):
            enc.action_start_service()

    def test_locked_encounter_refuses_writes(self):
        enc = self.Encounter.create(self._encounter_vals())
        enc.sudo().write({"is_locked": True})
        with self.assertRaises(UserError):
            enc.write({"chief_complaint": "berubah"})

    def test_encounter_cannot_be_deleted_unless_cancelled(self):
        enc = self.Encounter.create(self._encounter_vals())
        with self.assertRaises(UserError):
            enc.unlink()
        enc.action_cancel()
        enc.unlink()


@tagged("post_install", "-at_install", "hms")
class TestRegistrationWizard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # A code no seed or demo record uses: tests share the database with
        # whatever the hospital has already configured, so fixtures must not
        # claim names a real installation might want.
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-WIZTEST", "name": "Poli Uji Wizard", "type": "outpatient_clinic",
        })
        cls.payer_self = cls.env.ref("custom_hms_base.payer_self")

    def test_wizard_creates_patient_and_encounter_together(self):
        wizard = self.env["hms.registration.wizard"].create({
            "mode": "new",
            "new_name": "Siti Aminah",
            "new_nik": "3201014507950002",
            "new_birth_date": "1995-07-05",
            "new_gender": "female",
            "unit_id": self.unit.id,
            "payer_id": self.payer_self.id,
        })
        action = wizard.action_register()
        encounter = self.env["hms.encounter"].browse(action["res_id"])
        self.assertEqual(encounter.patient_id.name, "Siti Aminah")
        self.assertTrue(encounter.patient_id.mrn)
        self.assertTrue(encounter.patient_id.partner_id)

    def test_anonymous_emergency_patient_can_be_registered(self):
        er = self.env["hms.unit"].create({
            "code": "ZT-IGD2", "name": "IGD", "type": "emergency",
        })
        wizard = self.env["hms.registration.wizard"].create({
            "mode": "new", "new_is_anonymous": True, "encounter_type": "emergency",
            "unit_id": er.id, "payer_id": self.payer_self.id, "triage_level": "red",
        })
        action = wizard.action_register()
        encounter = self.env["hms.encounter"].browse(action["res_id"])
        self.assertTrue(encounter.identity_pending)
        self.assertEqual(encounter.triage_level, "red")

    def test_emergency_without_triage_is_refused_by_the_wizard(self):
        er = self.env["hms.unit"].create({
            "code": "ZT-IGD3", "name": "IGD", "type": "emergency",
        })
        wizard = self.env["hms.registration.wizard"].create({
            "mode": "new", "new_is_anonymous": True, "encounter_type": "emergency",
            "unit_id": er.id, "payer_id": self.payer_self.id,
        })
        with self.assertRaises(UserError):
            wizard.action_register()


@tagged("post_install", "-at_install", "hms")
class TestEncounterProgramFields(TransactionCase):
    """Field program nasional pada kunjungan.

    Belum ada bridging SITB; nomor register diisi manual petugas program TB.
    Yang diuji adalah bahwa kolomnya benar-benar ada dan menyimpan, karena
    field yang hanya hidup di file Python tanpa kolom tidak akan terlihat gagal.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-TB", "name": "Poli TB DOTS", "type": "outpatient_clinic",
        })
        cls.payer_self = cls.env.ref("custom_hms_base.payer_self")
        cls.patient = cls.env["hms.patient"].create({
            "name": "Rahmat Hidayat", "nik": "3201010101910007",
            "birth_date": "1991-01-01", "gender": "male",
        })

    def _encounter(self, **kw):
        vals = {
            "patient_id": self.patient.id,
            "unit_id": self.unit.id,
            "payer_id": self.payer_self.id,
        }
        vals.update(kw)
        return self.env["hms.encounter"].create(vals)

    def test_sitb_register_no_is_empty_by_default(self):
        self.assertFalse(self._encounter().sitb_register_no)

    def test_sitb_register_no_is_stored_and_read_back(self):
        encounter = self._encounter(sitb_register_no="TB.03/2026/000123")
        encounter.invalidate_recordset()
        self.assertEqual(encounter.sitb_register_no, "TB.03/2026/000123")

    def test_sitb_register_no_is_declared_not_copyable(self):
        """Nomor register SITB milik satu episode; salinan tidak boleh membawanya.

        Diuji pada definisi field, bukan lewat copy(): duplikat kunjungan rawat
        jalan pada hari yang sama memang ditolak `_check_single_open_outpatient`,
        sehingga copy() tidak pernah sampai ke pertanyaan yang ingin diuji.
        """
        field = self.env["hms.encounter"]._fields["sitb_register_no"]
        self.assertFalse(field.copy)
        self.assertEqual(field.type, "char")
