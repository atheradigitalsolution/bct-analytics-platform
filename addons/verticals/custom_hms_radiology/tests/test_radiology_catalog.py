# -*- coding: utf-8 -*-
"""Katalog pemeriksaan radiologi, dan bukti closed-loop tetap hidup sesudahnya.

Alur dijalankan lewat ``.with_user()``: petugas radiologi
(``group_hms_diagnostic_user``) memilih pemeriksaan dari katalog, radiolog
(``group_hms_diagnostic_verifier``) memverifikasi, dan klinisi
(``group_hms_emr_clinician``) mengakui temuan kritisnya.
"""
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

RADIOGRAPHER_GROUP = "custom_hms_base.group_hms_diagnostic_user"
VERIFIER_GROUP = "custom_hms_base.group_hms_diagnostic_verifier"
CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"


@tagged("post_install", "-at_install", "hms")
class RadCatalogCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rad_unit = cls.env["hms.unit"].create({
            "code": "ZT-RAD-KAT", "name": "Radiologi Katalog", "type": "radiology",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-RKAT", "name": "Poli Radiologi Katalog",
            "type": "outpatient_clinic",
        })
        cls.clinician_user = cls.env["res.users"].create({
            "name": "dr. Pengirim Katalog", "login": "zt-rad-katalog-klinisi",
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Ratna Wulandari", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501780031", "user_id": cls.clinician_user.id,
        })
        cls.radiographer_user = cls.env["res.users"].create({
            "name": "Radiografer Katalog", "login": "zt-rad-katalog-radiografer",
            "group_ids": [(4, cls.env.ref(RADIOGRAPHER_GROUP).id)],
        })
        cls.radiographer = cls.env["hms.practitioner"].create({
            "name": "Tono Sugiarto", "type": "radiographer", "nik": "3201010101880032",
            "user_id": cls.radiographer_user.id,
        })
        cls.radiologist_user = cls.env["res.users"].create({
            "name": "dr. Radiolog Katalog", "login": "zt-rad-katalog-radiolog",
            "group_ids": [(4, cls.env.ref(VERIFIER_GROUP).id)],
        })
        cls.radiologist = cls.env["hms.practitioner"].create({
            "name": "Hadi Nugroho", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101700033", "user_id": cls.radiologist_user.id,
        })

        cat_rad = cls.env.ref("custom_hms_base.tariff_cat_rad")
        cls.tariff_usg = cls.env["hms.tariff"].create({
            "code": "ZT-RK-USG", "name": "USG Abdomen",
            "category_id": cat_rad.id, "unit_id": cls.rad_unit.id,
        })
        cls.exam_usg = cls.env["hms.rad.exam"].create({
            "code": "ZT-EX-USG", "name": "USG Abdomen",
            "tariff_id": cls.tariff_usg.id, "modality": "usg",
            "body_part": "Abdomen", "requires_contrast": False,
            "preparation_note": "Puasa 6 jam, kandung kemih penuh.",
            "estimated_minutes": 20, "dose_reference": "Tidak ada radiasi pengion",
        })
        cls.tariff_ct = cls.env["hms.tariff"].create({
            "code": "ZT-RK-CT", "name": "CT Kepala dengan Kontras",
            "category_id": cat_rad.id, "unit_id": cls.rad_unit.id,
        })
        cls.exam_ct = cls.env["hms.rad.exam"].create({
            "code": "ZT-EX-CT", "name": "CT Kepala dengan Kontras",
            "tariff_id": cls.tariff_ct.id, "modality": "ct",
            "body_part": "Kepala", "requires_contrast": True,
            "dose_reference": "1000 mGy·cm (DRL dewasa)",
        })
        # Tarif TANPA entri katalog — jalur lama harus tetap jalan.
        cls.tariff_plain = cls.env["hms.tariff"].create({
            "code": "ZT-RK-PLAIN", "name": "Foto Thorax PA",
            "category_id": cat_rad.id, "unit_id": cls.rad_unit.id,
        })

    def _patient(self):
        seq = self.env["hms.patient"].search_count([]) + 70
        return self.env["hms.patient"].create({
            "name": "Pasien Radiologi Katalog", "gender": "female",
            "birth_date": "1975-07-07", "nik": f"32010145010{seq:05d}",
        })

    def _report(self, tariff):
        encounter = self.env["hms.encounter"].create({
            "patient_id": self._patient().id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "radiology",
            "practitioner_id": self.doctor.id, "target_unit_id": self.rad_unit.id,
            "clinical_note": "Nyeri perut kanan atas",
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        return order.line_ids.rad_report_ids


@tagged("post_install", "-at_install", "hms")
class TestRadExamCatalog(RadCatalogCase):
    def test_ordering_a_catalogued_tariff_fills_modality_and_body_part(self):
        report = self._report(self.tariff_usg)
        self.assertEqual(report.exam_id, self.exam_usg)
        self.assertEqual(report.modality, "usg")
        self.assertEqual(report.body_part, "Abdomen")
        self.assertFalse(report.contrast_used)
        self.assertIn("Puasa", report.preparation_note)

    def test_contrast_requirement_comes_from_the_catalog(self):
        report = self._report(self.tariff_ct)
        self.assertEqual(report.modality, "ct")
        self.assertTrue(report.contrast_used)

    def test_choosing_the_exam_later_fills_the_blanks(self):
        """Petugas radiologi memilih katalog pada ekspertise yang sudah ada."""
        report = self._report(self.tariff_plain).with_user(self.radiographer_user)
        self.assertFalse(report.exam_id)
        self.assertEqual(report.modality, "xray")
        report.write({"exam_id": self.exam_usg.id})
        self.assertEqual(report.modality, "usg")
        self.assertEqual(report.body_part, "Abdomen")

    def test_explicit_values_beat_the_catalog(self):
        """Katalog mengisi yang tidak dikirim; ia tidak menimpa yang dikirim."""
        report = self._report(self.tariff_plain).with_user(self.radiographer_user)
        report.write({"exam_id": self.exam_ct.id, "body_part": "Kepala — potongan tipis"})
        self.assertEqual(report.body_part, "Kepala — potongan tipis")
        self.assertEqual(report.modality, "ct")

    def test_uncatalogued_tariff_still_produces_a_report(self):
        report = self._report(self.tariff_plain)
        self.assertEqual(len(report), 1)
        self.assertFalse(report.exam_id)
        self.assertEqual(report.state, "scheduled")

    def test_one_active_catalog_entry_per_tariff(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["hms.rad.exam"].create({
                "code": "ZT-EX-USG2", "name": "USG Abdomen Duplikat",
                "tariff_id": self.tariff_usg.id, "modality": "usg",
            })
            self.env.flush_all()

    def test_negative_duration_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.rad.exam"].create({
                "code": "ZT-EX-NEG", "name": "Durasi Negatif",
                "tariff_id": self.tariff_plain.id, "modality": "xray",
                "estimated_minutes": -5,
            })


@tagged("post_install", "-at_install", "hms")
class TestRadExamKeepsClosedLoop(RadCatalogCase):
    def test_critical_closed_loop_still_works_with_a_catalogued_exam(self):
        """Katalog tidak boleh memutus lingkaran nilai kritis.

        Dijalankan dari tiga akun peran berbeda, persis seperti alur nyata:
        radiografer mengerjakan, radiolog memverifikasi, klinisi mengakui.
        """
        report = self._report(self.tariff_ct)
        self.assertEqual(report.exam_id, self.exam_ct)

        as_radiographer = report.with_user(self.radiographer_user)
        as_radiographer.action_perform()
        as_radiographer.write({
            "findings": "Tampak lesi hiperdens di ganglia basalis kiri.",
            "impression": "Perdarahan intraserebral akut.",
            "is_critical": True,
        })
        as_radiographer.action_report()

        as_radiologist = report.with_user(self.radiologist_user)
        as_radiologist.action_verify()
        self.assertEqual(report.state, "verified")
        self.assertEqual(report.ack_state, "pending")
        # Modalitas dari katalog bertahan melewati seluruh siklus.
        self.assertEqual(report.modality, "ct")
        self.assertEqual(report.body_part, "Kepala")

        as_radiologist.action_notify(channel="phone")
        self.assertTrue(report.notified_at)

        report.with_user(self.clinician_user).action_acknowledge(
            readback="Perdarahan intraserebral akut, pasien disiapkan CITO."
        )
        self.assertEqual(report.ack_state, "acknowledged")
        self.assertEqual(report.acknowledged_by_id, self.clinician_user)
        self.assertEqual(report.order_line_id.state, "done")
