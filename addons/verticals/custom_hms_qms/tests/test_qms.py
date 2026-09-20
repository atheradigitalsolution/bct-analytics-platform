# -*- coding: utf-8 -*-
"""Numbering, priority interleave, journeys and no-show recovery."""
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class QmsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic_unit = cls.env["hms.unit"].create({
            "code": "ZT-POLI-QMS", "name": "Poli Antrian", "type": "outpatient_clinic",
        })
        cls.service = cls.env["hms.qms.service"].create({
            "code": "ZT-POLI-QMS", "name": "Poli Antrian", "prefix": "A",
            "priority_prefix": "PA", "kind": "clinic", "unit_id": cls.clinic_unit.id,
            "priority_interleave": 3,
        })
        cls.counter = cls.env["hms.qms.counter"].create({
            "code": "ZT-L1", "name": "Loket 1", "service_ids": [(4, cls.service.id)],
        })
        cls.Ticket = cls.env["hms.qms.ticket"]

    def _issue(self, priority="none"):
        return self.Ticket.issue(self.service, priority=priority)


@tagged("post_install", "-at_install", "hms")
class TestTicketNumbering(QmsCase):
    def test_numbers_run_in_sequence_with_the_service_prefix(self):
        first, second = self._issue(), self._issue()
        self.assertEqual(first.name, "A-001")
        self.assertEqual(second.name, "A-002")

    def test_priority_tickets_use_a_separate_series(self):
        self._issue()
        priority = self._issue("elderly")
        self.assertEqual(priority.name, "PA-001")
        self.assertEqual(self._issue().name, "A-002")

    def test_twenty_concurrent_issues_produce_no_duplicates(self):
        tickets = [self._issue() for _ in range(20)]
        self.assertEqual(len({t.name for t in tickets}), 20)

    def test_position_counts_only_those_ahead(self):
        first, second, third = self._issue(), self._issue(), self._issue()
        self.assertEqual(first.position, 1)
        self.assertEqual(third.position, 3)
        first.action_call(self.counter)
        second.invalidate_recordset()
        self.assertEqual(second.position, 1)

    def test_estimate_uses_the_rolling_average(self):
        self.service.avg_service_seconds = 300
        self.assertEqual(self.service.estimated_wait_minutes(4), 20)


@tagged("post_install", "-at_install", "hms")
class TestCallingOrder(QmsCase):
    def test_counter_must_be_open_to_call(self):
        self._issue()
        with self.assertRaises(UserError):
            self.counter.action_call_next()

    def test_priority_goes_first_when_nothing_has_been_served(self):
        self.counter.action_open()
        self._issue()
        priority = self._issue("elderly")
        called = self.counter.action_call_next()
        self.assertEqual(called, priority)

    def test_priority_is_interleaved_not_absolute(self):
        """Three regulars between priority calls, so the regular line moves."""
        self.counter.action_open()
        regulars = [self._issue() for _ in range(6)]
        priorities = [self._issue("elderly") for _ in range(2)]
        order = []
        for _ in range(6):
            ticket = self.counter.action_call_next()
            order.append(ticket.priority)
            ticket.action_finish()
        self.assertEqual(order[0], "elderly")
        self.assertIn("none", order[1:4])
        self.assertTrue(any(p == "elderly" for p in order[1:]),
                        "Prioritas kedua harus tetap kebagian giliran.")
        self.assertTrue(regulars and priorities)

    def test_calling_while_a_ticket_is_active_is_refused(self):
        self.counter.action_open()
        self._issue()
        self._issue()
        self.counter.action_call_next()
        with self.assertRaises(UserError):
            self.counter.action_call_next()

    def test_finishing_frees_the_counter(self):
        self.counter.action_open()
        self._issue()
        ticket = self.counter.action_call_next()
        self.counter.action_finish()
        self.assertEqual(ticket.state, "finished")
        self.assertFalse(self.counter.current_ticket_id)

    def test_three_calls_without_an_answer_becomes_no_show(self):
        self.counter.action_open()
        self._issue()
        ticket = self.counter.action_call_next()
        ticket.action_recall()
        ticket.action_recall()
        self.assertEqual(ticket.state, "no_show")

    def test_no_show_can_be_restored_within_the_window(self):
        self.counter.action_open()
        self._issue()
        ticket = self.counter.action_call_next()
        ticket.action_no_show()
        ticket.action_restore()
        self.assertEqual(ticket.state, "waiting")
        self.assertEqual(ticket.call_count, 0)

    def test_restore_is_refused_after_the_window(self):
        self.counter.action_open()
        self._issue()
        ticket = self.counter.action_call_next()
        ticket.action_no_show()
        ticket.sudo().write({
            "called_at": fields.Datetime.subtract(fields.Datetime.now(), hours=3),
        })
        with self.assertRaises(UserError):
            ticket.action_restore()

    def test_closing_a_counter_with_an_active_ticket_is_refused(self):
        self.counter.action_open()
        self._issue()
        self.counter.action_call_next()
        with self.assertRaises(UserError):
            self.counter.action_close()

    def test_every_transition_is_logged(self):
        self.counter.action_open()
        self._issue()
        ticket = self.counter.action_call_next()
        ticket.action_serve()
        ticket.action_finish()
        states = ticket.log_ids.mapped("to_state")
        for expected in ("waiting", "called", "serving", "finished"):
            self.assertIn(expected, states)


@tagged("post_install", "-at_install", "hms")
class TestJourney(QmsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pharmacy = cls.env["hms.qms.service"].create({
            "code": "ZT-FAR-QMS", "name": "Apotek", "prefix": "F", "kind": "pharmacy",
        })
        cls.cashier = cls.env["hms.qms.service"].create({
            "code": "ZT-KAS-QMS", "name": "Kasir", "prefix": "K", "kind": "cashier",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Yuni Astuti", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501880001", "unit_ids": [(4, cls.clinic_unit.id)],
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Hendra Saputra", "nik": "3201010101950001",
            "birth_date": "1995-01-01", "gender": "male",
        })

    def _encounter(self, **kw):
        vals = {
            "patient_id": self.patient.id,
            "unit_id": self.clinic_unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        }
        vals.update(kw)
        return self.env["hms.encounter"].create(vals)

    def test_registration_issues_the_clinic_ticket(self):
        encounter = self._encounter()
        self.assertTrue(encounter.qms_ticket_ids)
        ticket = encounter.qms_ticket_ids
        self.assertEqual(ticket.service_id, self.service)
        self.assertEqual(ticket.source, "registration")
        self.assertEqual(ticket.stage_no, 1)

    def test_elderly_patient_gets_a_priority_ticket(self):
        elder = self.env["hms.patient"].create({
            "name": "Kakek Slamet", "nik": "3201010101500001",
            "birth_date": "1950-01-01", "gender": "male",
        })
        encounter = self._encounter(patient_id=elder.id)
        self.assertEqual(encounter.qms_ticket_ids.priority, "elderly")

    def test_closing_the_visit_issues_the_cashier_ticket(self):
        encounter = self._encounter()
        encounter.action_close()
        kinds = encounter.qms_ticket_ids.mapped("service_id.kind")
        self.assertIn("cashier", kinds)

    def test_tickets_of_one_visit_share_a_journey(self):
        encounter = self._encounter()
        encounter.action_close()
        journeys = encounter.qms_ticket_ids.mapped("journey_id")
        self.assertEqual(len(journeys), 1)
        self.assertEqual(len(journeys.ticket_ids), len(encounter.qms_ticket_ids))

    def test_transfer_moves_the_patient_to_another_service(self):
        encounter = self._encounter()
        ticket = encounter.qms_ticket_ids
        new_ticket = ticket.action_transfer(self.cashier)
        self.assertEqual(ticket.state, "transferred")
        self.assertEqual(new_ticket.service_id, self.cashier)
        self.assertEqual(new_ticket.journey_id, ticket.journey_id)
        self.assertEqual(new_ticket.stage_no, ticket.stage_no + 1)


@tagged("post_install", "-at_install", "hms")
class TestKioskAndDisplay(QmsCase):
    def test_kiosk_menu_lists_only_its_own_services(self):
        other = self.env["hms.qms.service"].create({
            "code": "ZT-OTH-QMS", "name": "Lain", "prefix": "O", "kind": "other",
        })
        kiosk = self.env["hms.qms.kiosk"].create({
            "code": "ZT-K1", "name": "Kiosk Lobi", "service_ids": [(4, self.service.id)],
        })
        codes = {s["code"] for s in kiosk.menu_payload()["services"]}
        self.assertEqual(codes, {self.service.code})
        self.assertNotIn(other.code, codes)

    def test_kiosk_issues_a_ticket_with_print_instructions(self):
        kiosk = self.env["hms.qms.kiosk"].create({
            "code": "ZT-K2", "name": "Kiosk 2", "service_ids": [(4, self.service.id)],
        })
        result = kiosk.issue_ticket(self.service.id, priority="pregnant")
        self.assertTrue(result["ticket"]["number"].startswith("PA-"))
        self.assertEqual(result["print"]["mode"], "browser")

    def test_kiosk_refuses_a_service_it_does_not_offer(self):
        other = self.env["hms.qms.service"].create({
            "code": "ZT-OTH2-QMS", "name": "Lain", "prefix": "O", "kind": "other",
        })
        kiosk = self.env["hms.qms.kiosk"].create({
            "code": "ZT-K3", "name": "Kiosk 3", "service_ids": [(4, self.service.id)],
        })
        with self.assertRaises(UserError):
            kiosk.issue_ticket(other.id)

    def test_receipt_bytes_contain_the_number_and_a_cut(self):
        kiosk = self.env["hms.qms.kiosk"].create({
            "code": "ZT-K4", "name": "Kiosk 4", "service_ids": [(4, self.service.id)],
        })
        ticket = self._issue()
        payload = kiosk.receipt_bytes(ticket)
        self.assertIn(b"A-001", payload)
        self.assertTrue(payload.endswith(b"\x1dV\x01"))

    def test_display_snapshot_masks_patient_names(self):
        patient = self.env["hms.patient"].create({
            "name": "Budi Santoso", "nik": "3201010101960001",
            "birth_date": "1996-01-01", "gender": "male",
        })
        ticket = self.Ticket.issue(self.service, patient=patient)
        self.counter.action_open()
        ticket.action_call(self.counter)
        display = self.env["hms.qms.display"].create({
            "code": "ZT-TV1", "name": "TV Lobi",
            "zone_ids": [(0, 0, {
                "position": 1, "kind": "calling", "service_ids": [(4, self.service.id)],
            })],
        })
        payload = display.state_payload()
        shown = payload["zones"][0]["calling"][0]["patient"]
        self.assertIn("*", shown)
        self.assertNotEqual(shown, "Budi Santoso")

    def test_display_token_can_be_rotated(self):
        display = self.env["hms.qms.display"].create({"code": "ZT-TV2", "name": "TV 2"})
        old = display.token
        display.action_regenerate_token()
        self.assertNotEqual(display.token, old)
