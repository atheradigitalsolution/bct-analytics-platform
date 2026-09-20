# -*- coding: utf-8 -*-
"""Master jenis diet, dan sifat aditifnya terhadap kolom teks yang sudah ada."""
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

NURSE_GROUP = "custom_hms_base.group_hms_nurse"


@tagged("post_install", "-at_install", "hms")
class DietTypeCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RANAP-D", "name": "Rawat Inap Diet", "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-W-D", "name": "Melati Diet", "unit_id": cls.unit.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-RD-1", "name": "D-1", "ward_id": cls.ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id,
        })
        cls.bed = cls.env["hms.bed"].create({
            "code": "ZT-RD-1-A", "name": "A", "room_id": cls.room.id,
        })
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Siti Nurhaliza", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501740051", "user_id": cls.env.user.id,
        })
        cls.nurse_user = cls.env["res.users"].create({
            "name": "Perawat Diet", "login": "zt-diet-perawat",
            "group_ids": [(4, cls.env.ref(NURSE_GROUP).id)],
        })
        cls.diet_dm = cls.env["hms.diet.type"].create({
            "code": "ZT-D-DM", "name": "Diet DM 1700 kkal", "category": "special",
            "texture": "regular", "energy_kcal": 1700, "protein_g": 60,
            "is_therapeutic": True, "restrictions": "Tanpa gula sederhana.",
        })
        cls.diet_regular = cls.env["hms.diet.type"].create({
            "code": "ZT-D-BIASA", "name": "Diet Biasa", "category": "regular",
            "texture": "regular", "energy_kcal": 2100, "protein_g": 70,
        })

    def _admission(self):
        seq = self.env["hms.patient"].search_count([]) + 150
        patient = self.env["hms.patient"].create({
            "name": "Pasien Diet", "gender": "female", "birth_date": "1960-02-02",
            "nik": f"32010145010{seq:05d}",
        })
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.unit.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.dpjp.id,
        })
        return self.env["hms.admission"].admit(
            encounter, self.bed, self.dpjp,
            entitled_class=self.env.ref("custom_hms_base.care_class_2"),
        )


@tagged("post_install", "-at_install", "hms")
class TestDietType(DietTypeCase):
    def test_code_is_unique(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"):
            self.env["hms.diet.type"].create({
                "code": "ZT-D-DM", "name": "Duplikat", "category": "regular",
            })
            self.env.flush_all()

    def test_special_diet_must_be_therapeutic(self):
        with self.assertRaises(ValidationError):
            self.env["hms.diet.type"].create({
                "code": "ZT-D-SALAH", "name": "Khusus Tanpa Penanda",
                "category": "special", "is_therapeutic": False,
            })

    def test_negative_nutrition_is_refused(self):
        with self.assertRaises(ValidationError):
            self.env["hms.diet.type"].create({
                "code": "ZT-D-NEG", "name": "Energi Negatif",
                "category": "regular", "energy_kcal": -100,
            })

    def test_admission_keeps_both_the_master_and_the_free_text(self):
        """Kolom teks 'diet' TIDAK berubah makna; master hanya menemaninya."""
        admission = self._admission()
        admission.write({
            "diet_type_id": self.diet_dm.id,
            "diet": "DM 1700 — porsi kecil sering",
        })
        self.assertEqual(admission.diet_type_id, self.diet_dm)
        self.assertIn("porsi kecil", admission.diet)

    def test_admission_without_a_diet_type_is_still_valid(self):
        admission = self._admission()
        admission.write({"diet": "Biasa"})
        self.assertFalse(admission.diet_type_id)
        self.assertEqual(admission.diet, "Biasa")

    def test_nurse_may_read_the_master_but_not_edit_it(self):
        master = self.env["hms.diet.type"].with_user(self.nurse_user)
        self.assertEqual(master.browse(self.diet_dm.id).code, "ZT-D-DM")
        with self.assertRaises(Exception):
            master.browse(self.diet_dm.id).write({"name": "Diubah Perawat"})

    def test_diet_type_only_on_diet_order_lines(self):
        admission = self._admission()
        tariff = self.env["hms.tariff"].create({
            "code": "ZT-D-TAR", "name": "Konsultasi Gizi",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_consult").id,
            "unit_id": self.unit.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": admission.encounter_id.id, "order_type": "other",
            "practitioner_id": self.dpjp.id,
            "line_ids": [(0, 0, {"tariff_id": tariff.id})],
        })
        with self.assertRaises(ValidationError):
            order.line_ids.write({"diet_type_id": self.diet_dm.id})

    def test_diet_order_line_accepts_the_diet_type(self):
        admission = self._admission()
        tariff = self.env["hms.tariff"].create({
            "code": "ZT-D-TAR2", "name": "Diet Rawat Inap",
            "category_id": self.env.ref("custom_hms_base.tariff_cat_consult").id,
            "unit_id": self.unit.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": admission.encounter_id.id, "order_type": "diet",
            "practitioner_id": self.dpjp.id,
            "line_ids": [(0, 0, {
                "tariff_id": tariff.id, "diet_type_id": self.diet_dm.id,
            })],
        })
        self.assertEqual(order.line_ids.diet_type_id, self.diet_dm)
