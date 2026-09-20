# -*- coding: utf-8 -*-
"""Permintaan gizi yang membawa jenis diet — tanpa mengubah yang sudah ada.

Seluruh alur dijalankan lewat ``.with_user(nurse_user)``: perawat ruangan
adalah yang meneruskan perintah diet dokter ke dapur, dan dialah yang sudah
punya hak tulis ke antrian unit. Tidak ada grup baru dan tidak ada
``sudo()``.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

NURSE_GROUP = "custom_hms_base.group_hms_nurse"


@tagged("post_install", "-at_install", "hms")
class NutritionRequestCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RANAP-G", "name": "Rawat Inap Gizi", "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-W-G", "name": "Mawar Gizi", "unit_id": cls.unit.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-RG-1", "name": "G-1", "ward_id": cls.ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id,
        })
        cls.bed = cls.env["hms.bed"].create({
            "code": "ZT-RG-1-A", "name": "A", "room_id": cls.room.id,
        })
        cls.station = cls.env["hms.nursing.station"].create({
            "code": "ZT-NS-G", "name": "Station Mawar", "ward_id": cls.ward.id,
        })
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Bambang Iriawan", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101710061", "user_id": cls.env.user.id,
        })
        cls.nurse_user = cls.env["res.users"].create({
            "name": "Perawat Gizi", "login": "zt-gizi-perawat",
            "group_ids": [(4, cls.env.ref(NURSE_GROUP).id)],
        })
        cls.diet = cls.env["hms.diet.type"].create({
            "code": "ZT-G-RG", "name": "Diet Rendah Garam II", "category": "special",
            "texture": "regular", "energy_kcal": 1900, "protein_g": 65,
            "is_therapeutic": True, "restrictions": "Garam maksimal 600 mg/hari.",
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-G-TAR", "name": "Diet Rawat Inap",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_consult").id,
            "unit_id": cls.unit.id,
        })

    def _admission(self, bed=None):
        seq = self.env["hms.patient"].search_count([]) + 200
        patient = self.env["hms.patient"].create({
            "name": "Pasien Gizi", "gender": "male", "birth_date": "1955-03-03",
            "nik": f"32010101010{seq:05d}",
        })
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.dpjp.id,
        })
        return self.env["hms.admission"].admit(
            encounter, bed or self.bed, self.dpjp,
            entitled_class=self.env.ref("custom_hms_base.care_class_2"),
        )

    def _diet_line(self, admission, diet=True):
        order = self.env["hms.order"].create({
            "encounter_id": admission.encounter_id.id, "order_type": "diet",
            "practitioner_id": self.dpjp.id, "target_unit_id": self.unit.id,
            "line_ids": [(0, 0, {
                "tariff_id": self.tariff.id,
                "diet_type_id": self.diet.id if diet else False,
            })],
        })
        order.action_submit()
        return order.line_ids


@tagged("post_install", "-at_install", "hms")
class TestNutritionRequest(NutritionRequestCase):
    def test_nurse_forwards_the_diet_order_to_the_kitchen(self):
        admission = self._admission()
        line = self._diet_line(admission).with_user(self.nurse_user)
        request = line.action_request_nutrition()
        self.assertEqual(len(request), 1)
        self.assertEqual(request.to_unit, "nutrition")
        self.assertEqual(request.diet_type_id, self.diet)
        self.assertEqual(request.station_id, self.station)
        self.assertEqual(request.admission_id, admission)
        self.assertEqual(request.order_line_id, line)
        self.assertEqual(request.state, "open")
        self.assertEqual(request.requested_by_id, self.nurse_user)

    def test_forwarding_twice_reuses_the_open_request(self):
        admission = self._admission()
        line = self._diet_line(admission).with_user(self.nurse_user)
        first = line.action_request_nutrition()
        second = line.action_request_nutrition()
        self.assertEqual(first, second)
        self.assertEqual(len(line.nutrition_request_ids), 1)

    def test_a_handled_request_does_not_block_the_next_meal(self):
        admission = self._admission()
        line = self._diet_line(admission).with_user(self.nurse_user)
        first = line.action_request_nutrition()
        first.action_handle()
        second = line.action_request_nutrition()
        self.assertNotEqual(first, second)
        self.assertEqual(len(line.nutrition_request_ids), 2)

    def test_legacy_nutrition_request_without_a_diet_type_is_still_valid(self):
        """Permintaan gizi lama tetap sah apa adanya."""
        admission = self._admission()
        request = self.env["hms.unit.request"].with_user(self.nurse_user).create({
            "station_id": self.station.id, "admission_id": admission.id,
            "to_unit": "nutrition", "type": "Tambah porsi",
            "detail": "Tambah satu porsi bubur untuk keluarga penunggu.",
        })
        self.assertFalse(request.diet_type_id)
        self.assertEqual(request.state, "open")
        self.assertEqual(request.to_unit, "nutrition")

    def test_diet_type_is_refused_on_a_non_nutrition_request(self):
        admission = self._admission()
        with self.assertRaises(ValidationError):
            self.env["hms.unit.request"].with_user(self.nurse_user).create({
                "station_id": self.station.id, "admission_id": admission.id,
                "to_unit": "pharmacy", "detail": "Salah tujuan",
                "diet_type_id": self.diet.id,
            })

    def test_non_diet_order_line_cannot_request_nutrition(self):
        admission = self._admission()
        order = self.env["hms.order"].create({
            "encounter_id": admission.encounter_id.id, "order_type": "other",
            "practitioner_id": self.dpjp.id,
            "line_ids": [(0, 0, {"tariff_id": self.tariff.id})],
        })
        order.action_submit()
        with self.assertRaises(UserError):
            order.line_ids.with_user(self.nurse_user).action_request_nutrition()

    def test_outpatient_diet_order_has_no_kitchen_to_ask(self):
        """Dapur melayani per bed; order diet rawat jalan tidak punya admisi."""
        encounter = self.env["hms.encounter"].create({
            "patient_id": self.env["hms.patient"].create({
                "name": "Pasien Rawat Jalan Gizi", "gender": "female",
                "birth_date": "1992-04-04",
                "nik": f"32010145010{self.env['hms.patient'].search_count([]) + 300:05d}",
            }).id,
            "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.dpjp.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "diet",
            "practitioner_id": self.dpjp.id,
            "line_ids": [(0, 0, {
                "tariff_id": self.tariff.id, "diet_type_id": self.diet.id,
            })],
        })
        order.action_submit()
        with self.assertRaises(UserError):
            order.line_ids.with_user(self.nurse_user).action_request_nutrition()

    def test_detail_falls_back_to_the_diet_name(self):
        admission = self._admission()
        line = self._diet_line(admission).with_user(self.nurse_user)
        request = line.action_request_nutrition()
        self.assertIn("Rendah Garam", request.detail)
