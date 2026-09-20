# -*- coding: utf-8 -*-
"""EWS scoring and escalation, eMAR double-check, tasks and hand-over."""
from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class NursingCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RANAP-N", "name": "Rawat Inap N", "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-W-N", "name": "Anggrek", "unit_id": cls.unit.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-RN-1", "name": "N-1", "ward_id": cls.ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id,
        })
        cls.bed = cls.env["hms.bed"].create({
            "code": "ZT-RN-1-A", "name": "A", "room_id": cls.room.id,
        })
        cls.station = cls.env["hms.nursing.station"].create({
            "code": "ZT-NS-N", "name": "Station Anggrek", "ward_id": cls.ward.id,
        })
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Wahyu Setiawan", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101750001", "user_id": cls.env.user.id,
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Ani Rahmawati", "type": "nurse", "nik": "3201014501900011",
            "can_double_check_high_alert": True,
        })
        cls.nurse2 = cls.env["hms.practitioner"].create({
            "name": "Dewi Kartika", "type": "nurse", "nik": "3201014501900012",
            "can_double_check_high_alert": True,
        })
        cls.nurse_junior = cls.env["hms.practitioner"].create({
            "name": "Rina Junior", "type": "nurse", "nik": "3201014501900013",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Marsudi", "nik": "3201010101650001",
            "birth_date": "1965-01-01", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.dpjp.id,
        })
        cls.admission = cls.env["hms.admission"].admit(
            cls.encounter, cls.bed, cls.dpjp,
            entitled_class=cls.env.ref("custom_hms_base.care_class_2"),
        )


@tagged("post_install", "-at_install", "hms")
class TestEws(NursingCase):
    def _observe(self, **kw):
        vals = {"encounter_id": self.encounter.id}
        vals.update(kw)
        return self.env["hms.observation"].create(vals)

    def test_normal_vitals_score_zero(self):
        observation = self._observe(
            respiratory_rate=16, spo2=98, temperature=36.6, systolic=120, pulse=72,
            consciousness="alert",
        )
        self.assertEqual(observation.ews_score_id.score, 0)
        self.assertEqual(observation.ews_score_id.level, "low")

    def test_deteriorating_vitals_score_high(self):
        observation = self._observe(
            respiratory_rate=26, spo2=90, temperature=39.5, systolic=88, pulse=125,
            consciousness="voice",
        )
        self.assertGreaterEqual(observation.ews_score_id.score, 7)
        self.assertEqual(observation.ews_score_id.level, "high")

    def test_oxygen_support_adds_two_points(self):
        without = self._observe(respiratory_rate=16, spo2=98, pulse=70)
        with_o2 = self._observe(respiratory_rate=16, spo2=98, pulse=70, oxygen_support=True)
        self.assertEqual(with_o2.ews_score_id.score - without.ews_score_id.score, 2)

    def test_high_score_creates_an_escalation_task(self):
        observation = self._observe(
            respiratory_rate=28, spo2=89, systolic=85, pulse=130, consciousness="pain",
        )
        score = observation.ews_score_id
        self.assertTrue(score.escalated)
        task = score.escalation_task_id
        self.assertTrue(task)
        self.assertEqual(task.type, "escalation")
        self.assertEqual(task.priority, "2")

    def test_low_score_does_not_escalate(self):
        observation = self._observe(respiratory_rate=16, spo2=98, systolic=120, pulse=70)
        self.assertFalse(observation.ews_score_id.escalated)

    def test_measurement_without_vitals_is_not_scored(self):
        """A weight-only entry must not produce a reassuring zero."""
        observation = self._observe(weight_kg=70.0)
        self.assertFalse(observation.ews_score_id)

    def test_escalation_emits_an_event(self):
        before = self.env["hms.event"].search_count([("topic", "=", "nursing.ews.escalated")])
        self._observe(respiratory_rate=30, spo2=85, systolic=80, pulse=135)
        after = self.env["hms.event"].search_count([("topic", "=", "nursing.ews.escalated")])
        self.assertEqual(after, before + 1)


@tagged("post_install", "-at_install", "hms")
class TestEmar(NursingCase):
    def _schedule(self, high_alert=False):
        template = self.env["product.template"].create({
            "name": "Obat eMAR", "is_storable": True, "tracking": "lot",
            "use_expiration_date": True,
        })
        medicine = self.env["hms.medicine"].create({
            "product_tmpl_id": template.id, "generic_name": "Obat eMAR",
            "item_type": "drug", "is_high_alert": high_alert,
        })
        depot = self.env["hms.depot"].create({
            "code": f"DEP-N{template.id}", "name": "Depo Ranap", "type": "inpatient",
            "location_id": self.env["stock.warehouse"].search([], limit=1).lot_stock_id.id,
        })
        rx = self.env["hms.prescription"].create({
            "encounter_id": self.encounter.id, "practitioner_id": self.dpjp.id,
            "depot_id": depot.id, "type": "inpatient",
            "line_ids": [(0, 0, {"medicine_id": medicine.id, "qty_prescribed": 3})],
        })
        return self.env["hms.emar.schedule"].create({
            "prescription_line_id": rx.line_ids.id,
            "admission_id": self.admission.id,
            "station_id": self.station.id,
            "scheduled_at": fields.Datetime.now(),
        })

    def test_ordinary_medicine_needs_no_witness(self):
        schedule = self._schedule()
        administration = self.env["hms.emar.administration"].create({
            "schedule_id": schedule.id, "given_by_id": self.nurse.id, "outcome": "given",
        })
        self.assertEqual(administration.outcome, "given")
        self.assertEqual(schedule.state, "given")

    def test_high_alert_without_witness_is_refused(self):
        schedule = self._schedule(high_alert=True)
        with self.assertRaises(ValidationError):
            self.env["hms.emar.administration"].create({
                "schedule_id": schedule.id, "given_by_id": self.nurse.id, "outcome": "given",
            })

    def test_high_alert_witness_must_be_a_different_nurse(self):
        schedule = self._schedule(high_alert=True)
        with self.assertRaises(ValidationError):
            self.env["hms.emar.administration"].create({
                "schedule_id": schedule.id, "given_by_id": self.nurse.id,
                "witness_id": self.nurse.id, "outcome": "given",
            })

    def test_high_alert_witness_must_be_authorised(self):
        schedule = self._schedule(high_alert=True)
        with self.assertRaises(ValidationError):
            self.env["hms.emar.administration"].create({
                "schedule_id": schedule.id, "given_by_id": self.nurse.id,
                "witness_id": self.nurse_junior.id, "outcome": "given",
            })

    def test_high_alert_with_a_proper_witness_is_accepted(self):
        schedule = self._schedule(high_alert=True)
        administration = self.env["hms.emar.administration"].create({
            "schedule_id": schedule.id, "given_by_id": self.nurse.id,
            "witness_id": self.nurse2.id, "outcome": "given",
        })
        self.assertTrue(administration.id)

    def test_not_giving_a_dose_requires_a_reason(self):
        schedule = self._schedule()
        with self.assertRaises(ValidationError):
            self.env["hms.emar.administration"].create({
                "schedule_id": schedule.id, "given_by_id": self.nurse.id, "outcome": "refused",
            })


@tagged("post_install", "-at_install", "hms")
class TestTasksAndHandover(NursingCase):
    def test_signed_instruction_becomes_a_nursing_task(self):
        note = self.env["hms.clinical.note"].create({
            "encounter_id": self.encounter.id, "author_id": self.dpjp.id,
            "author_role": "doctor", "assessment": "Observasi",
            "instruction": "Pasang infus RL 20 tpm",
        })
        note.action_sign()
        task = self.env["hms.nursing.task"].search([
            ("source_model", "=", "hms.clinical.note"), ("source_id", "=", note.id),
        ])
        self.assertEqual(len(task), 1)
        self.assertEqual(task.type, "instruction")
        self.assertIn("infus", task.detail)

    def test_unsigned_instruction_creates_no_task(self):
        self.env["hms.clinical.note"].create({
            "encounter_id": self.encounter.id, "author_id": self.dpjp.id,
            "assessment": "Rencana", "instruction": "Belum final",
        })
        self.assertEqual(self.env["hms.nursing.task"].search_count([
            ("type", "=", "instruction"), ("encounter_id", "=", self.encounter.id),
        ]), 0)

    def test_skipping_a_task_requires_a_reason(self):
        task = self.env["hms.nursing.task"].create({
            "patient_id": self.patient.id, "station_id": self.station.id,
            "type": "vitals", "title": "TTV", "due_at": fields.Datetime.now(),
        })
        with self.assertRaises(UserError):
            task.action_skip()
        task.action_skip("Pasien sedang tindakan")
        self.assertEqual(task.state, "skipped")

    def test_overdue_cron_moves_past_due_tasks(self):
        self.env["hms.nursing.task"].create({
            "patient_id": self.patient.id, "station_id": self.station.id,
            "type": "vitals", "title": "TTV lama",
            "due_at": fields.Datetime.subtract(fields.Datetime.now(), hours=3),
            "window_minutes": 30,
        })
        moved = self.env["hms.nursing.task"]._cron_mark_overdue()
        self.assertGreaterEqual(moved, 1)

    def test_handover_draft_is_prefilled_from_the_record(self):
        self.env["hms.observation"].create({
            "encounter_id": self.encounter.id,
            "respiratory_rate": 22, "spo2": 93, "systolic": 105, "pulse": 100,
        })
        handover = self.env["hms.handover"].draft_for(self.admission)
        self.assertIn(self.patient.name, handover.situation)
        self.assertIn("EWS", handover.assessment)
        self.assertIn(self.dpjp.name, handover.background)

    def test_handover_needs_two_different_signatures_and_a_recommendation(self):
        handover = self.env["hms.handover"].draft_for(self.admission)
        with self.assertRaises(UserError):
            handover.action_sign()
        handover.write({
            "given_by_id": self.nurse.id, "received_by_id": self.nurse.id,
            "recommendation": "Pantau EWS tiap 4 jam",
        })
        with self.assertRaises(UserError):
            handover.action_sign()
        handover.write({"received_by_id": self.nurse2.id})
        handover.action_sign()
        self.assertTrue(handover.signed_at)

    def test_signed_nursing_assessment_is_immutable(self):
        assessment = self.env["hms.nursing.assessment"].create({
            "encounter_id": self.encounter.id, "admission_id": self.admission.id,
            "nurse_id": self.nurse.id, "evaluation": "Kondisi stabil",
        })
        assessment.action_sign()
        with self.assertRaises(UserError):
            assessment.write({"evaluation": "diubah"})

    def test_station_board_lists_its_patients(self):
        board = self.station.patient_board()
        self.assertEqual(len(board), 1)
        self.assertEqual(board[0]["patient"], self.patient.name)
        self.assertEqual(board[0]["bed"], self.bed.code)
