# -*- coding: utf-8 -*-
"""Jadwal tindakan (termasuk penundaan beralasan) dan rencana kontrol.

Alur dijalankan dari akun peran: dokter bedah / DPJP
(``group_hms_emr_clinician``) menjadwalkan dan menunda tindakan serta
memfinalkan resume, petugas pendaftaran (``group_hms_registration_user``)
menjadwalkan kontrol ke slot.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"
REGISTRATION_GROUP = "custom_hms_base.group_hms_registration_user"


@tagged("post_install", "-at_install", "hms")
class ProcedureFollowupCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.theatre = cls.env["hms.unit"].create({
            "code": "ZT-OK-PF", "name": "Kamar Operasi", "type": "inpatient",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-PF", "name": "Poli Bedah", "type": "outpatient_clinic",
        })
        # Poli terpisah untuk kunjungan kontrol: satu pasien tidak boleh punya
        # dua kunjungan terbuka di poli yang sama pada hari yang sama
        # (hms.encounter._check_single_open_outpatient), dan kontrol memang
        # kunjungan berikutnya, bukan lanjutan kunjungan yang sedang berjalan.
        cls.control_clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-PF-K", "name": "Poli Kontrol Bedah",
            "type": "outpatient_clinic",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-W-PF", "name": "Bedah", "unit_id": cls.theatre.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-OK-1", "name": "OK 1", "ward_id": cls.ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id,
        })
        cls.surgeon_user = cls.env["res.users"].create({
            "name": "dr. Bedah Umum", "login": "zt-pf-bedah",
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.surgeon = cls.env["hms.practitioner"].create({
            "name": "Arif Santoso", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101720041", "user_id": cls.surgeon_user.id,
        })
        cls.frontdesk_user = cls.env["res.users"].create({
            "name": "Petugas Pendaftaran PF", "login": "zt-pf-pendaftaran",
            "group_ids": [(4, cls.env.ref(REGISTRATION_GROUP).id)],
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-PF-APP", "name": "Apendektomi",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": cls.theatre.id, "duration_minutes": 90,
        })
        cls.icd = cls.env["hms.icd10"].create({
            "code": "ZT-K35", "name_en": "Acute appendicitis",
        })

    def _patient(self, name="Pasien Tindakan"):
        seq = self.env["hms.patient"].search_count([]) + 100
        return self.env["hms.patient"].create({
            "name": name, "gender": "male", "birth_date": "1990-09-09",
            "nik": f"32010101010{seq:05d}",
        })

    def _encounter(self, patient=None, unit=None):
        return self.env["hms.encounter"].create({
            "patient_id": (patient or self._patient()).id,
            "unit_id": (unit or self.clinic).id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.surgeon.id,
        })

    def _procedure_line(self, scheduled=True, encounter=None):
        encounter = encounter or self._encounter()
        line_vals = {"tariff_id": self.tariff.id}
        if scheduled:
            line_vals["scheduled_at"] = fields.Datetime.add(
                fields.Datetime.now(), days=2
            )
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.surgeon.id, "target_unit_id": self.theatre.id,
            "line_ids": [(0, 0, line_vals)],
        })
        order.action_submit()
        return order.line_ids


@tagged("post_install", "-at_install", "hms")
class TestProcedureSchedule(ProcedureFollowupCase):
    def test_scheduled_procedure_line_gets_its_schedule(self):
        line = self._procedure_line()
        schedule = line.procedure_schedule_ids
        self.assertEqual(len(schedule), 1)
        self.assertEqual(schedule.state, "planned")
        self.assertEqual(schedule.patient_id, line.patient_id)
        self.assertEqual(schedule.unit_id, self.theatre)
        self.assertEqual(schedule.planned_start, line.scheduled_at)
        # Durasi diambil dari tarif, bukan ditebak.
        self.assertEqual(
            schedule.planned_end, line.scheduled_at + timedelta(minutes=90)
        )
        self.assertEqual(schedule.original_planned_start, line.scheduled_at)

    def test_unscheduled_procedure_line_gets_no_schedule(self):
        """Tindakan yang dikerjakan saat itu juga tidak mengotori papan operasi."""
        line = self._procedure_line(scheduled=False)
        self.assertFalse(line.procedure_schedule_ids)

    def test_postponing_without_a_reason_is_refused(self):
        schedule = self._procedure_line().procedure_schedule_ids.with_user(
            self.surgeon_user
        )
        with self.assertRaises(UserError):
            schedule.action_postpone()
        self.assertEqual(schedule.state, "planned")

    def test_writing_the_postponed_state_directly_is_refused(self):
        """Jalur API/impor tidak boleh melewati kewajiban alasan."""
        schedule = self._procedure_line().procedure_schedule_ids.with_user(
            self.surgeon_user
        )
        with self.assertRaises(ValidationError):
            schedule.write({"state": "postponed"})

    def test_postponing_with_a_reason_is_recorded_and_counted(self):
        line = self._procedure_line()
        schedule = line.procedure_schedule_ids.with_user(self.surgeon_user)
        original = schedule.planned_start
        new_start = fields.Datetime.add(original, days=3)
        schedule.action_postpone(
            reason="facility", note="OK dipakai kasus emergensi", new_start=new_start,
        )
        self.assertEqual(schedule.state, "postponed")
        self.assertEqual(schedule.postpone_reason, "facility")
        self.assertEqual(schedule.postpone_count, 1)
        self.assertEqual(schedule.postponed_by_id, self.surgeon_user)
        self.assertEqual(schedule.planned_start, new_start)
        # Jadwal semula tetap bisa dibaca setelah tanggalnya berubah.
        self.assertEqual(schedule.original_planned_start, original)

        schedule.action_postpone(reason="patient")
        self.assertEqual(schedule.postpone_count, 2)
        self.assertEqual(schedule.original_planned_start, original)

    def test_postponed_procedure_can_be_confirmed_again(self):
        schedule = self._procedure_line().procedure_schedule_ids.with_user(
            self.surgeon_user
        )
        schedule.action_postpone(reason="preparation")
        schedule.action_confirm()
        self.assertEqual(schedule.state, "confirmed")

    def test_full_run_closes_the_order_line(self):
        line = self._procedure_line()
        schedule = line.procedure_schedule_ids.with_user(self.surgeon_user)
        schedule.action_confirm()
        schedule.action_start()
        self.assertEqual(line.state, "in_progress")
        schedule.action_done()
        self.assertEqual(schedule.state, "done")
        self.assertEqual(line.state, "done")
        self.assertGreaterEqual(schedule.duration_minutes, 0)

    def test_confirming_without_a_planned_start_is_refused(self):
        line = self._procedure_line(scheduled=False)
        schedule = self.env["hms.procedure.schedule"].create({
            "order_line_id": line.id,
        })
        with self.assertRaises(UserError):
            schedule.with_user(self.surgeon_user).action_confirm()

    def test_schedule_refuses_a_non_procedure_line(self):
        encounter = self._encounter()
        tariff = self.env["hms.tariff"].create({
            "code": "ZT-PF-LAB", "name": "Pemeriksaan Lab PF",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_lab").id,
            "unit_id": self.clinic.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": self.surgeon.id,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        order.action_submit()
        with self.assertRaises(ValidationError):
            self.env["hms.procedure.schedule"].create({
                "order_line_id": order.line_ids.id,
                "planned_start": fields.Datetime.now(),
            })

    def test_team_must_come_from_the_same_encounter(self):
        line = self._procedure_line()
        other_team = self.env["hms.care.team"].search([
            ("encounter_id", "!=", line.encounter_id.id),
        ], limit=1)
        if not other_team:
            other_team = self.env["hms.care.team"].create({
                "encounter_id": self._encounter().id,
                "practitioner_id": self.surgeon.id, "role": "consultant",
            })
        with self.assertRaises(ValidationError):
            line.procedure_schedule_ids.write({"team_ids": [(4, other_team.id)]})

    def test_planned_end_before_start_is_refused(self):
        line = self._procedure_line()
        schedule = line.procedure_schedule_ids
        with self.assertRaises(ValidationError):
            schedule.write({
                "planned_end": schedule.planned_start - timedelta(hours=1),
            })


@tagged("post_install", "-at_install", "hms")
class TestFollowupPlan(ProcedureFollowupCase):
    def _final_summary(self, followup_date=None, unit=None):
        """Resume yang difinalkan DOKTER, bukan superuser."""
        encounter = self._encounter()
        summary = self.env["hms.summary"].with_user(self.surgeon_user).create({
            "encounter_id": encounter.id,
            "diagnosis_primary_id": self.icd.id,
            "practitioner_id": self.surgeon.id,
            "followup_date": followup_date or False,
            "followup_unit_id": (unit or self.clinic).id if followup_date else False,
            "followup_instruction": "Kontrol luka operasi." if followup_date else False,
        })
        summary.action_finalize()
        return summary

    def test_finalising_a_summary_with_a_date_creates_the_plan(self):
        target = fields.Date.add(fields.Date.context_today(self.env.user), days=7)
        summary = self._final_summary(followup_date=target)
        plan = summary.followup_plan_ids
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan.state, "planned")
        self.assertEqual(plan.kind, "control")
        self.assertEqual(plan.planned_date, target)
        self.assertEqual(plan.unit_id, self.clinic)
        self.assertEqual(plan.patient_id, summary.encounter_id.patient_id)
        self.assertIn("Kontrol", plan.instruction)
        # Field lama di resume tidak dipindahkan, hanya disalin.
        self.assertEqual(summary.followup_date, target)
        self.assertEqual(summary.followup_unit_id, self.clinic)

    def test_bpjs_control_number_is_left_empty(self):
        """Nomor Surat Kontrol datang dari VClaim, bukan dikarang di sini."""
        target = fields.Date.add(fields.Date.context_today(self.env.user), days=7)
        plan = self._final_summary(followup_date=target).followup_plan_ids
        self.assertFalse(plan.bpjs_control_no)

    def test_summary_without_a_date_creates_nothing(self):
        summary = self._final_summary()
        self.assertFalse(summary.followup_plan_ids)

    def test_rejected_finalisation_leaves_no_orphan_plan(self):
        encounter = self._encounter()
        summary = self.env["hms.summary"].with_user(self.surgeon_user).create({
            "encounter_id": encounter.id,
            "followup_date": fields.Date.context_today(self.env.user),
        })
        with self.assertRaises(UserError):
            summary.action_finalize()
        self.assertFalse(
            self.env["hms.followup.plan"].search_count([("summary_id", "=", summary.id)])
        )

    def test_frontdesk_schedules_the_plan_into_a_slot(self):
        target = fields.Date.context_today(self.env.user) + timedelta(
            days=(7 - fields.Date.context_today(self.env.user).weekday()) % 7 or 7
        )
        plan = self._final_summary(followup_date=target).followup_plan_ids
        template = self.env["hms.schedule.template"].create({
            "practitioner_id": self.surgeon.id, "unit_id": self.clinic.id,
            "weekday": str(target.weekday()), "time_from": 8.0, "time_to": 9.0,
            "slot_minutes": 30,
        })
        slot = template.generate_slots(target)[:1]
        plan.with_user(self.frontdesk_user).action_schedule(slot=slot)
        self.assertEqual(plan.state, "scheduled")
        self.assertEqual(plan.slot_id, slot)
        self.assertEqual(plan.practitioner_id, self.surgeon)

    def test_slot_on_another_date_is_refused(self):
        target = fields.Date.add(fields.Date.context_today(self.env.user), days=7)
        plan = self._final_summary(followup_date=target).followup_plan_ids
        slot = self.env["hms.schedule.slot"].create({
            "practitioner_id": self.surgeon.id, "unit_id": self.clinic.id,
            "date": fields.Date.add(target, days=1), "time_from": 8.0, "time_to": 8.5,
        })
        with self.assertRaises(ValidationError):
            plan.write({"slot_id": slot.id})

    def test_fulfilling_the_plan_records_the_next_encounter(self):
        target = fields.Date.add(fields.Date.context_today(self.env.user), days=-2)
        summary = self._final_summary(followup_date=target)
        plan = summary.followup_plan_ids
        next_encounter = self._encounter(
            patient=summary.encounter_id.patient_id, unit=self.control_clinic,
        )
        plan.with_user(self.surgeon_user).action_fulfill(next_encounter)
        self.assertEqual(plan.state, "fulfilled")
        self.assertEqual(plan.fulfilled_encounter_id, next_encounter)
        self.assertGreaterEqual(plan.days_late, 0)

    def test_fulfilling_with_another_patient_is_refused(self):
        target = fields.Date.context_today(self.env.user)
        plan = self._final_summary(followup_date=target).followup_plan_ids
        with self.assertRaises(UserError):
            plan.action_fulfill(self._encounter())

    def test_cron_marks_overdue_plans_missed_using_the_setting(self):
        settings = self.env["hms.settings"].get_settings()
        settings.followup_missed_grace_days = 3
        overdue = fields.Date.add(fields.Date.context_today(self.env.user), days=-10)
        plan = self._final_summary(followup_date=overdue).followup_plan_ids
        self.env["hms.followup.plan"]._cron_mark_missed()
        self.assertEqual(plan.state, "missed")

    def test_cron_respects_the_grace_period(self):
        settings = self.env["hms.settings"].get_settings()
        settings.followup_missed_grace_days = 30
        overdue = fields.Date.add(fields.Date.context_today(self.env.user), days=-10)
        plan = self._final_summary(followup_date=overdue).followup_plan_ids
        self.env["hms.followup.plan"]._cron_mark_missed()
        self.assertEqual(plan.state, "planned")

    def test_fulfilled_plan_cannot_be_cancelled(self):
        target = fields.Date.context_today(self.env.user)
        summary = self._final_summary(followup_date=target)
        plan = summary.followup_plan_ids
        plan.action_fulfill(self._encounter(
            patient=summary.encounter_id.patient_id, unit=self.control_clinic,
        ))
        with self.assertRaises(UserError):
            plan.action_cancel()
