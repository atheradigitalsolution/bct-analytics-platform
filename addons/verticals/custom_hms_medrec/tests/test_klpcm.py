# -*- coding: utf-8 -*-
"""KLPCM: temuan lahir sendiri, tertutup sendiri, dan tidak bisa dihapus."""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import MedrecCase


@tagged("post_install", "-at_install", "hms")
class TestKlpcmAnalysis(MedrecCase):
    def test_closing_an_incomplete_encounter_opens_findings(self):
        encounter = self._encounter()
        encounter.action_close()
        components = set(encounter.klpcm_ids.mapped("component"))
        self.assertIn("cppt", components)
        self.assertIn("summary", components)
        self.assertTrue(all(k.state == "open" for k in encounter.klpcm_ids))
        self.assertTrue(all(k.auto_detected for k in encounter.klpcm_ids))

    def test_a_complete_encounter_opens_nothing(self):
        encounter = self._encounter()
        self._complete_and_close(encounter)
        self.assertEqual(encounter.klpcm_open_count, 0)

    def test_finding_closes_when_the_document_arrives(self):
        """Inti alurnya: yang menutup temuan adalah dokumennya, bukan tombol."""
        encounter = self._encounter()
        encounter.action_close()
        summary_finding = encounter.klpcm_ids.filtered(lambda k: k.component == "summary")
        self.assertEqual(summary_finding.state, "open")

        self._final_summary(encounter)
        encounter.action_reanalyze_klpcm()

        self.assertEqual(summary_finding.state, "completed")
        self.assertTrue(summary_finding.closed_at)

    def test_reanalysis_does_not_duplicate_open_findings(self):
        encounter = self._encounter()
        encounter.action_close()
        before = len(encounter.klpcm_ids)
        encounter.action_reanalyze_klpcm()
        encounter.action_reanalyze_klpcm()
        self.assertEqual(len(encounter.klpcm_ids), before)

    def test_unsigned_notes_are_an_authentication_finding(self):
        """Komponen autentikasi memang mendeteksi catatan tanpa tanda tangan.

        Diuji lewat detektornya langsung, bukan lewat ``action_close``, karena
        jalur itu sudah dijaga lebih dulu oleh ``_closing_blockers`` milik
        ``custom_hms_emr`` — lihat tes berikutnya. Komponen ini tetap perlu ada
        untuk jalur pemulangan rawat inap, yang menulis state encounter
        langsung tanpa melewati ``action_close``.
        """
        encounter = self._encounter()
        self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "soap",
            "assessment": "Belum ditandatangani",
        })
        self._final_summary(encounter)
        missing = self.env["hms.klpcm"]._missing_components(encounter)
        self.assertIn("authentication", missing)
        self.assertNotIn("summary", missing)

    def test_the_close_path_already_refuses_unsigned_notes(self):
        """Dua penjaga yang sepakat, bukan dua penjaga yang bertabrakan.

        Kunjungan rawat jalan tidak pernah sampai ke analisis dengan catatan
        belum bertanda tangan: ``action_close`` sudah menolaknya lebih dulu.
        Ini dicatat sebagai tes supaya perubahan di salah satu sisi terlihat.
        """
        encounter = self._encounter()
        self.env["hms.clinical.note"].create({
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "soap",
            "assessment": "Belum ditandatangani",
        })
        with self.assertRaises(UserError):
            encounter.action_close()

    def test_the_discharge_path_also_triggers_the_analysis(self):
        """Pemulangan rawat inap menulis state langsung, tanpa action_close.

        Pemicunya sengaja dipasang pada transisi state, bukan pada nama
        metode. Kalau ia menempel di ``action_close``, tidak satu pun berkas
        rawat inap pernah dianalisis — justru berkas yang paling mahal bila
        klaimnya dikembalikan.
        """
        encounter = self._encounter(type="inpatient", unit_id=self.ward_unit.id)
        encounter.write({"state": "discharged"})
        self.assertTrue(encounter.klpcm_ids)
        self.assertGreater(encounter.klpcm_open_count, 0)

    def test_inpatient_requires_more_components_than_outpatient(self):
        """Daftar komponen wajib dihitung per jenis kunjungan, bukan disamakan."""
        Klpcm = self.env["hms.klpcm"]
        outpatient = self._encounter()
        inpatient = self._encounter(type="inpatient", unit_id=self.ward_unit.id)
        self.assertLess(
            Klpcm._required_components(outpatient),
            Klpcm._required_components(inpatient),
        )
        self.assertIn("initial_nursing", Klpcm._required_components(inpatient))
        self.assertNotIn("initial_nursing", Klpcm._required_components(outpatient))

    def test_encounter_still_being_served_is_not_analyzed(self):
        encounter = self._encounter()
        self.env["hms.klpcm"].analyze_encounter(encounter)
        self.assertFalse(encounter.klpcm_ids)

    def test_cancelled_encounter_is_not_analyzed(self):
        encounter = self._encounter()
        encounter.action_cancel()
        self.assertFalse(encounter.klpcm_ids)

    def test_findings_cannot_be_deleted(self):
        """Gerbang yang penjaganya bisa dihapus bukan gerbang."""
        encounter = self._encounter()
        encounter.action_close()
        with self.assertRaises(UserError):
            encounter.klpcm_ids.unlink()


@tagged("post_install", "-at_install", "hms")
class TestKlpcmDeadline(MedrecCase):
    def test_due_at_comes_from_the_hospital_parameter(self):
        settings = self.env["hms.settings"].get_settings()
        settings.klpcm_due_hours = 12
        encounter = self._encounter()
        encounter.action_close()
        finding = encounter.klpcm_ids[0]
        self.assertEqual(finding.due_hours_applied, 12)
        self.assertEqual(finding.due_at, encounter.closed_at + timedelta(hours=12))

    def test_changing_the_parameter_does_not_move_frozen_deadlines(self):
        """Tenggat sebuah berkas adalah kebijakan saat berkas itu ditutup."""
        settings = self.env["hms.settings"].get_settings()
        settings.klpcm_due_hours = 24
        encounter = self._encounter()
        encounter.action_close()
        original = encounter.klpcm_ids[0].due_at

        settings.klpcm_due_hours = 96
        encounter.action_reanalyze_klpcm()
        self.assertEqual(encounter.klpcm_ids[0].due_at, original)

    def test_zero_parameter_falls_back_instead_of_issuing_a_past_deadline(self):
        settings = self.env["hms.settings"].get_settings()
        settings.klpcm_due_hours = 0
        encounter = self._encounter()
        encounter.action_close()
        self.assertEqual(encounter.klpcm_ids[0].due_hours_applied, 48)

    def test_overdue_flag_and_its_search(self):
        settings = self.env["hms.settings"].get_settings()
        settings.klpcm_due_hours = 1
        encounter = self._encounter()
        encounter.action_close()
        finding = encounter.klpcm_ids[0]
        finding.sudo().write({
            "due_at": fields.Datetime.subtract(fields.Datetime.now(), hours=2),
        })
        self.assertTrue(finding.is_overdue)
        self.assertIn(finding, self.env["hms.klpcm"].search([("is_overdue", "=", True)]))
        self.assertNotIn(finding, self.env["hms.klpcm"].search([("is_overdue", "=", False)]))
