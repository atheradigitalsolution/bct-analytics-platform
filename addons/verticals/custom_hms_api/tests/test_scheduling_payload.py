# -*- coding: utf-8 -*-
"""Kontrak payload rencana kontrol dan jadwal tindakan.

Alasan yang sama seperti ``test_catalog_payload``: ``api<any>()`` di frontend
tidak punya tipe per-endpoint, jadi nama kunci yang bergeser tidak pernah
menghasilkan galat — hanya layar yang kosong.

Satu hal di sini bukan sekadar nama: ``bpjs_control_status``. Nomor Surat
Kontrol BPJS diterbitkan VClaim, bukan rumah sakit, dan kolomnya SENGAJA
kosong. Kolom kosong tanpa penjelasan terbaca sebagai kelalaian petugas
pendaftaran, dan petugas yang mengira dirinya lalai akan mengarang nomor.
Karena itu status "menunggu integrasi VClaim" diuji, bukan diasumsikan.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_hms_api.controllers.scheduling import (
    followup_row, procedure_row,
)

CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"

# web/app/(app)/kontrol/page.tsx, /pasien/[id]/page.tsx, /encounter/[id]/page.tsx
FOLLOWUP_KEYS_READ_BY_SCREENS = (
    "id", "patient", "encounter", "practitioner", "unit", "planned_date",
    "kind_label", "instruction", "state", "state_label", "days_late",
    "bpjs_control_no", "bpjs_control_status",
)
# web/app/(app)/tindakan/page.tsx
PROCEDURE_KEYS_READ_BY_SCREENS = (
    "id", "name", "patient", "practitioner", "unit", "room", "order_name",
    "planned_start", "original_planned_start", "is_elective", "state",
    "state_label", "postpone_reason_label", "postpone_note", "postpone_count",
)


@tagged("post_install", "-at_install", "hms")
class SchedulingPayloadCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.theatre = cls.env["hms.unit"].create({
            "code": "ZT-API-OK", "name": "Kamar Operasi Uji", "type": "ok",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-API-POLI", "name": "Poli Uji", "type": "outpatient_clinic",
        })
        cls.doctor_user = cls.env["res.users"].create({
            "name": "dr. Uji API", "login": "zt-api-dokter",
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Uji Klinisi", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101720099", "user_id": cls.doctor_user.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-API-TIND", "name": "Apendektomi Uji",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": cls.theatre.id, "duration_minutes": 90,
        })

    def _encounter(self):
        seq = self.env["hms.patient"].search_count([]) + 500
        patient = self.env["hms.patient"].create({
            "name": "Pasien Payload", "gender": "female", "birth_date": "1988-01-01",
            "nik": f"32010101010{seq:05d}",
        })
        return self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })

    def _plan(self, **extra):
        values = {
            "encounter_id": self._encounter().id,
            "practitioner_id": self.doctor.id,
            "unit_id": self.clinic.id,
            "planned_date": fields.Date.context_today(self.env.user),
            "kind": "control",
            "instruction": "Kontrol membawa hasil pemeriksaan.",
        }
        values.update(extra)
        return self.env["hms.followup.plan"].create(values)

    def _schedule(self):
        encounter = self._encounter()
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "target_unit_id": self.theatre.id,
            "line_ids": [(0, 0, {
                "tariff_id": self.tariff.id,
                "scheduled_at": fields.Datetime.now() + timedelta(days=2),
            })],
        })
        order.action_submit()
        return order.line_ids.procedure_schedule_ids

    # --- rencana kontrol --------------------------------------------------
    def test_followup_row_carries_every_key_the_screens_read(self):
        row = followup_row(self._plan())
        missing = [k for k in FOLLOWUP_KEYS_READ_BY_SCREENS if k not in row]
        self.assertFalse(
            missing,
            "Layar rencana kontrol membaca kunci yang tidak ada di payload: %s"
            % missing,
        )
        # Sub-objek yang di-dereference langsung di JSX.
        self.assertEqual(set(row["patient"]), {"id", "name", "mrn"})
        self.assertIn("id", row["encounter"])
        self.assertIn("name", row["unit"])

    def test_empty_bpjs_control_number_is_explained_not_just_empty(self):
        row = followup_row(self._plan())
        self.assertIsNone(row["bpjs_control_no"])
        self.assertEqual(row["bpjs_control_status"], "menunggu integrasi VClaim")

    def test_filled_bpjs_control_number_stops_claiming_it_is_pending(self):
        """Ketika bridging VClaim akhirnya mengisi nomornya, statusnya ikut."""
        plan = self._plan()
        plan.bpjs_control_no = "0001/SK/2026"
        row = followup_row(plan)
        self.assertEqual(row["bpjs_control_no"], "0001/SK/2026")
        self.assertEqual(row["bpjs_control_status"], "terbit")

    def test_followup_row_sends_human_labels_for_state_and_kind(self):
        plan = self._plan()
        plan.action_mark_missed()
        row = followup_row(plan)
        self.assertEqual(row["state"], "missed")
        self.assertEqual(row["state_label"], "Tidak Datang")
        self.assertEqual(row["kind_label"], "Kontrol Ulang")

    # --- jadwal tindakan --------------------------------------------------
    def test_procedure_row_carries_every_key_the_board_reads(self):
        row = procedure_row(self._schedule())
        missing = [k for k in PROCEDURE_KEYS_READ_BY_SCREENS if k not in row]
        self.assertFalse(
            missing,
            "Papan tindakan membaca kunci yang tidak ada di payload: %s" % missing,
        )
        self.assertEqual(set(row["patient"]), {"id", "name", "mrn"})

    def test_postponement_reaches_the_board_as_a_countable_event(self):
        """Indikator mutu menghitung KEJADIAN penundaan, bukan jadwal terakhir."""
        schedule = self._schedule()
        first_plan = schedule.planned_start
        schedule.action_postpone(
            reason="preparation",
            note="Hasil laboratorium pra-operasi belum lengkap.",
            new_start=fields.Datetime.now() + timedelta(days=9),
        )
        row = procedure_row(schedule)
        self.assertEqual(row["state_label"], "Ditunda")
        self.assertEqual(row["postpone_count"], 1)
        self.assertEqual(row["postpone_reason_label"],
                         "Persiapan / Pemeriksaan Penunjang Belum Lengkap")
        self.assertIn("pra-operasi", row["postpone_note"])
        # Tanpa jadwal semula, lama penundaan tidak bisa dihitung setelah
        # jadwalnya diubah — dan semua operasi tampak selalu tepat waktu.
        self.assertEqual(row["original_planned_start"], first_plan)
        self.assertNotEqual(row["planned_start"], first_plan)

    def test_board_row_of_a_fresh_schedule_says_it_was_never_postponed(self):
        row = procedure_row(self._schedule())
        self.assertEqual(row["postpone_count"], 0)
        self.assertIsNone(row["postpone_reason_label"])
        self.assertIsNone(row["postpone_note"])
