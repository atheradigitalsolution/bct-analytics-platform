# -*- coding: utf-8 -*-
"""Order lifecycle, privilege enforcement and encounter-closing interaction."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestOrder(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lab_unit = cls.env["hms.unit"].create({
            "code": "ZT-LAB", "name": "Laboratorium", "type": "lab",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-ORD", "name": "Poli Uji Order", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Sri Mulyani", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501860001", "unit_ids": [(4, cls.clinic.id)],
        })
        cls.no_lab_doctor = cls.env["hms.practitioner"].create({
            "name": "Agus Salim", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101860002", "can_order_lab": False,
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Dewi Lestari", "nik": "3201014501920001",
            "birth_date": "1992-01-05", "gender": "female",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })
        cls.lab_cat = cls.env.ref("custom_hms_base.tariff_cat_lab")
        cls.admin_cat = cls.env.ref("custom_hms_base.tariff_cat_admin")
        cls.tariff_lab = cls.env["hms.tariff"].create({
            "code": "ZT-LAB-DL", "name": "Darah Lengkap",
            "category_id": cls.lab_cat.id, "unit_id": cls.lab_unit.id,
        })
        cls.tariff_admin = cls.env["hms.tariff"].create({
            "code": "ZT-ADM-RJ", "name": "Administrasi Rawat Jalan",
            "category_id": cls.admin_cat.id,
        })
        cls.Order = cls.env["hms.order"]

    def _order(self, **kw):
        vals = {
            "encounter_id": self.encounter.id,
            "order_type": "lab",
            "practitioner_id": self.doctor.id,
            "target_unit_id": self.lab_unit.id,
            "line_ids": [(0, 0, {"tariff_id": self.tariff_lab.id, "qty": 1})],
        }
        vals.update(kw)
        return self.Order.create(vals)

    def test_order_number_is_generated(self):
        order = self._order()
        self.assertTrue(order.name.startswith("ORD-"))

    def test_header_state_follows_its_lines(self):
        order = self._order()
        self.assertEqual(order.state, "draft")
        order.action_submit()
        self.assertEqual(order.state, "ordered")
        order.line_ids.action_start()
        self.assertEqual(order.state, "in_progress")
        order.line_ids.action_done()
        self.assertEqual(order.state, "done")

    def test_partially_done_order_reads_as_in_progress(self):
        order = self._order()
        order.write({"line_ids": [(0, 0, {"tariff_id": self.tariff_lab.id, "qty": 1})]})
        order.action_submit()
        order.line_ids[0].action_done()
        self.assertEqual(order.state, "in_progress")

    def test_all_cancelled_order_reads_as_cancelled(self):
        order = self._order()
        order.action_submit()
        order.action_cancel()
        self.assertEqual(order.state, "cancelled")

    def test_submitting_an_empty_order_is_refused(self):
        order = self.Order.create({
            "encounter_id": self.encounter.id, "order_type": "lab",
            "practitioner_id": self.doctor.id,
        })
        with self.assertRaises(UserError):
            order.action_submit()

    def test_doctor_without_lab_privilege_cannot_order_lab(self):
        with self.assertRaises(ValidationError):
            self._order(practitioner_id=self.no_lab_doctor.id)

    def test_done_line_cannot_be_cancelled(self):
        order = self._order()
        order.action_submit()
        order.line_ids.action_done()
        with self.assertRaises(UserError):
            order.line_ids.action_cancel()

    def test_line_cannot_skip_from_draft_to_done(self):
        order = self._order()
        with self.assertRaises(UserError):
            order.line_ids.action_done()

    def test_zero_quantity_is_refused(self):
        with self.assertRaises(ValidationError):
            self._order(line_ids=[(0, 0, {"tariff_id": self.tariff_lab.id, "qty": 0})])

    def test_line_unit_defaults_to_the_tariff_provider(self):
        """Lab revenue belongs to the lab, not to the clinic that ordered it."""
        order = self._order()
        self.assertEqual(order.line_ids.unit_id, self.lab_unit)

    def test_open_orders_block_encounter_closing(self):
        order = self._order()
        order.action_submit()
        with self.assertRaises(UserError):
            self.encounter.action_close()

    def test_encounter_closes_once_orders_are_done(self):
        order = self._order()
        order.action_submit()
        order.line_ids.action_done()
        self.encounter.action_close()
        self.assertEqual(self.encounter.state, "finished")

    def test_order_submission_emits_an_event(self):
        before = self.env["hms.event"].search_count([("topic", "=", "order.created")])
        self._order().action_submit()
        after = self.env["hms.event"].search_count([("topic", "=", "order.created")])
        self.assertEqual(after, before + 1)
