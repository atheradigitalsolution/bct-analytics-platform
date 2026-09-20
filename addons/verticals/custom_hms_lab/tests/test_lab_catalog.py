# -*- coding: utf-8 -*-
"""Katalog pemeriksaan lab, fallback ke hubungan lama, dan gerbang spesimen.

Semua alur di bawah dijalankan lewat ``.with_user(analyst)`` — petugas
laboratorium dengan ``group_hms_diagnostic_user``. Pengguna penjalan tes
adalah superuser dan melewati SEMUA hak akses, jadi tes yang berjalan
sebagai dirinya sendiri tidak membuktikan alur ini bisa dikerjakan orang
yang seharusnya mengerjakannya.
"""
from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

ANALYST_GROUP = "custom_hms_base.group_hms_diagnostic_user"


@tagged("post_install", "-at_install", "hms")
class LabCatalogCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lab_unit = cls.env["hms.unit"].create({
            "code": "ZT-LAB-KAT", "name": "Laboratorium Katalog", "type": "lab",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-KAT", "name": "Poli Katalog", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Bagus Prasetya", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101790021", "user_id": cls.env.user.id,
        })
        # Petugas lab sungguhan. Semua penerimaan/penolakan spesimen di bawah
        # berjalan sebagai dia.
        cls.analyst_user = cls.env["res.users"].create({
            "name": "Analis Katalog", "login": "zt-lab-katalog-analis",
            "group_ids": [(4, cls.env.ref(ANALYST_GROUP).id)],
        })

        cls.p_hb = cls._parameter("ZT-K-HB", "Hemoglobin")
        cls.p_ht = cls._parameter("ZT-K-HT", "Hematokrit")
        cls.p_leu = cls._parameter("ZT-K-LEU", "Leukosit")
        cls.p_glu = cls._parameter("ZT-K-GLU", "Glukosa")

        cat_lab = cls.env.ref("custom_hms_base.tariff_cat_lab")
        # (1) Tarif yang PUNYA entri katalog.
        cls.tariff_panel = cls.env["hms.tariff"].create({
            "code": "ZT-K-DL", "name": "Darah Lengkap",
            "category_id": cat_lab.id, "unit_id": cls.lab_unit.id,
        })
        cls.test_panel = cls.env["hms.lab.test"].create({
            "code": "ZT-T-DL", "name": "Darah Lengkap",
            "tariff_id": cls.tariff_panel.id,
            "specimen_type": "Darah vena EDTA", "container": "Tabung tutup ungu",
            "tat_minutes": 60, "is_panel": True,
            "parameter_ids": [(6, 0, [cls.p_hb.id, cls.p_ht.id, cls.p_leu.id])],
        })
        # (2) Tarif LAMA: hanya hubungan hms.lab.parameter.tariff_ids.
        cls.tariff_legacy = cls.env["hms.tariff"].create({
            "code": "ZT-K-GDS", "name": "Glukosa Darah Sewaktu",
            "category_id": cat_lab.id, "unit_id": cls.lab_unit.id,
            "lab_parameter_ids": [(6, 0, [cls.p_glu.id])],
        })
        # (3) Tarif yang punya KEDUANYA, dengan isi berbeda.
        cls.tariff_both = cls.env["hms.tariff"].create({
            "code": "ZT-K-BOTH", "name": "Pemeriksaan Ganda Jalur",
            "category_id": cat_lab.id, "unit_id": cls.lab_unit.id,
            "lab_parameter_ids": [(6, 0, [cls.p_glu.id])],
        })
        cls.test_both = cls.env["hms.lab.test"].create({
            "code": "ZT-T-BOTH", "name": "Pemeriksaan Ganda Jalur",
            "tariff_id": cls.tariff_both.id,
            "parameter_ids": [(6, 0, [cls.p_hb.id, cls.p_ht.id])],
        })

    @classmethod
    def _parameter(cls, code, name):
        return cls.env["hms.lab.parameter"].create({
            "code": code, "name": name, "uom_name": "g/dL",
            "range_ids": [(0, 0, {"ref_low": 1.0, "ref_high": 100.0})],
        })

    def _patient(self, name="Pasien Katalog"):
        seq = self.env["hms.patient"].search_count([]) + 40
        return self.env["hms.patient"].create({
            "name": name, "gender": "male", "birth_date": "1980-05-05",
            "nik": f"32010101010{seq:05d}",
        })

    def _ordered_line(self, tariff):
        """Baris order lab yang sudah dipesan, belum dimulai."""
        encounter = self.env["hms.encounter"].create({
            "patient_id": self._patient().id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": self.doctor.id, "target_unit_id": self.lab_unit.id,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        return order.line_ids

    def _as_analyst(self, line):
        return line.with_user(self.analyst_user)


@tagged("post_install", "-at_install", "hms")
class TestLabTestCatalog(LabCatalogCase):
    def test_catalog_resolves_every_parameter_of_the_panel(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_receive_specimen()
        self.assertEqual(line.state, "in_progress")
        self.assertEqual(
            set(line.lab_result_ids.mapped("parameter_id.code")),
            {"ZT-K-HB", "ZT-K-HT", "ZT-K-LEU"},
        )
        self.assertEqual(line.lab_result_count, 3)

    def test_tariff_without_catalog_falls_back_to_parameter_tariff_ids(self):
        """Fallback dibuktikan, bukan diasumsikan.

        Tarif lama tidak punya entri ``hms.lab.test`` sama sekali; hasilnya
        harus tetap terbentuk dari ``hms.lab.parameter.tariff_ids``.
        """
        self.assertFalse(self.tariff_legacy.lab_test_ids)
        line = self._as_analyst(self._ordered_line(self.tariff_legacy))
        line.action_receive_specimen()
        self.assertEqual(line.lab_result_ids.parameter_id, self.p_glu)

    def test_catalog_wins_when_both_paths_are_filled(self):
        line = self._as_analyst(self._ordered_line(self.tariff_both))
        line.action_receive_specimen()
        self.assertEqual(
            set(line.lab_result_ids.mapped("parameter_id.code")),
            {"ZT-K-HB", "ZT-K-HT"},
        )

    def test_archived_catalog_entry_falls_back_to_the_old_relation(self):
        """Katalog yang diarsipkan tidak boleh mematikan pemeriksaannya."""
        self.test_both.active = False
        line = self._as_analyst(self._ordered_line(self.tariff_both))
        line.action_receive_specimen()
        self.assertEqual(line.lab_result_ids.parameter_id, self.p_glu)

    def test_empty_catalog_entry_falls_back(self):
        self.test_both.parameter_ids = [(5, 0, 0)]
        line = self._as_analyst(self._ordered_line(self.tariff_both))
        line.action_receive_specimen()
        self.assertEqual(line.lab_result_ids.parameter_id, self.p_glu)

    def test_panel_needs_more_than_one_parameter(self):
        with self.assertRaises(ValidationError):
            self.env["hms.lab.test"].create({
                "code": "ZT-T-SOLO", "name": "Panel Palsu",
                "tariff_id": self.tariff_legacy.id, "is_panel": True,
                "parameter_ids": [(6, 0, [self.p_glu.id])],
            })

    def test_one_active_catalog_entry_per_tariff(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["hms.lab.test"].create({
                "code": "ZT-T-DL2", "name": "Darah Lengkap Duplikat",
                "tariff_id": self.tariff_panel.id,
            })
            self.env.flush_all()

    def test_analyst_may_read_the_catalog_but_not_edit_it(self):
        catalog = self.env["hms.lab.test"].with_user(self.analyst_user)
        self.assertTrue(catalog.browse(self.test_panel.id).name)
        with self.assertRaises(Exception):
            catalog.browse(self.test_panel.id).write({"name": "Diubah Analis"})


@tagged("post_install", "-at_install", "hms")
class TestSpecimenGate(LabCatalogCase):
    def test_receiving_records_who_and_when(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_receive_specimen()
        self.assertEqual(line.specimen_state, "received")
        self.assertEqual(line.specimen_received_by_id, self.analyst_user)
        self.assertTrue(line.specimen_received_at)

    def test_rejected_specimen_stops_the_flow_with_a_reason(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_reject_specimen(reason="hemolysis", note="Serum merah pekat")
        self.assertEqual(line.specimen_state, "rejected")
        self.assertEqual(line.specimen_reject_reason, "hemolysis")
        self.assertEqual(line.specimen_rejected_by_id, self.analyst_user)
        self.assertEqual(line.state, "cancelled")
        self.assertIn("Hemolisis", line.cancel_reason)
        # Alur benar-benar berhenti: tidak ada satu pun baris hasil.
        self.assertFalse(line.lab_result_ids)

    def test_rejection_without_a_reason_is_refused(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        with self.assertRaises(UserError):
            line.action_reject_specimen()
        self.assertEqual(line.specimen_state, "pending")
        self.assertEqual(line.state, "ordered")

    def test_rejected_specimen_cannot_be_started(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_reject_specimen(reason="unlabeled")
        with self.assertRaises(UserError):
            line.action_start()
        self.assertFalse(line.lab_result_ids)

    def test_rejected_specimen_cannot_be_received_afterwards(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_reject_specimen(reason="wrong_container")
        with self.assertRaises(UserError):
            line.action_receive_specimen()

    def test_receiving_twice_does_not_duplicate_results(self):
        line = self._as_analyst(self._ordered_line(self.tariff_panel))
        line.action_receive_specimen()
        line.action_receive_specimen()
        self.assertEqual(line.lab_result_count, 3)

    def test_specimen_gate_is_lab_only(self):
        encounter = self.env["hms.encounter"].create({
            "patient_id": self._patient().id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        tariff = self.env["hms.tariff"].create({
            "code": "ZT-K-TIND", "name": "Tindakan Bukan Lab",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": self.clinic.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        with self.assertRaises(UserError):
            order.line_ids.action_receive_specimen()
