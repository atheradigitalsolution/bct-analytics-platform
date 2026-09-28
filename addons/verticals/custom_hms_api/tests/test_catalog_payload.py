# -*- coding: utf-8 -*-
"""Kontrak nama field katalog yang dibaca layar CPOE dan layar gizi.

KENAPA TES INI ADA, PADAHAL SUDAH ADA TYPESCRIPT
------------------------------------------------
Frontend memanggil ``api<any>()`` tanpa tipe per-endpoint. Mengganti nama
satu kunci — ``specimen_type`` jadi ``specimen``, ``tariff_id`` jadi
``tariff`` — tidak menghasilkan satu pun galat kompilasi; layarnya hanya
diam-diam merender kosong, dan dokter memesan pemeriksaan tanpa melihat
tabung apa yang harus dipakai. Daftar kunci di bawah karena itu bukan
duplikasi serializer: ia satu-satunya tempat yang bisa GAGAL ketika nama
berubah tanpa layarnya ikut diperbarui.

Setiap konstanta menyebut berkas JSX yang membacanya. Kalau sebuah kunci
tidak lagi dibaca layar mana pun, hapus dari sini DAN dari serializer.
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_hms_api.controllers.master import (
    diet_type_row, lab_test_row, rad_exam_row,
)

# web/app/(app)/encounter/[id]/order/page.tsx — tab Laboratorium
LAB_KEYS_READ_BY_CPOE = (
    "tariff_id", "name", "is_panel", "parameter_count", "parameters",
    "specimen_type", "container", "tat_minutes", "note",
)
# web/app/(app)/encounter/[id]/order/page.tsx — tab Radiologi
RAD_KEYS_READ_BY_CPOE = (
    "tariff_id", "name", "modality_label", "body_part", "requires_contrast",
    "preparation_note", "estimated_minutes", "dose_reference",
)
# web/app/(app)/nurse/page.tsx — kartu "Permintaan gizi"
DIET_KEYS_READ_BY_NURSE = (
    "id", "name", "category_label", "texture_label", "energy_kcal",
    "is_therapeutic",
)


@tagged("post_install", "-at_install", "hms")
class CatalogPayloadCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-API-LAB", "name": "Laboratorium Uji", "type": "support",
        })
        cls.lab_tariff = cls.env["hms.tariff"].create({
            "code": "ZT-API-DL", "name": "Darah Lengkap Uji",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_lab").id,
            "unit_id": cls.unit.id,
        })
        cls.rad_tariff = cls.env["hms.tariff"].create({
            "code": "ZT-API-CT", "name": "CT Kepala Uji",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_rad").id,
            "unit_id": cls.unit.id,
        })
        cls.hb = cls.env["hms.lab.parameter"].create({
            "code": "ZT-API-HB", "name": "Hemoglobin", "uom_name": "g/dL",
        })
        cls.wbc = cls.env["hms.lab.parameter"].create({
            "code": "ZT-API-WBC", "name": "Leukosit", "uom_name": "10³/µL",
        })

    def _lab_test(self):
        return self.env["hms.lab.test"].create({
            "code": "ZT-API-LT", "name": "Darah Lengkap Uji",
            "tariff_id": self.lab_tariff.id,
            "parameter_ids": [(6, 0, (self.hb | self.wbc).ids)],
            "is_panel": True,
            "specimen_type": "Darah vena EDTA",
            "container": "Tutup ungu (EDTA) 3 mL",
            "tat_minutes": 60,
        })

    def _rad_exam(self):
        return self.env["hms.rad.exam"].create({
            "code": "ZT-API-RX", "name": "CT Kepala Uji",
            "tariff_id": self.rad_tariff.id, "modality": "ct",
            "body_part": "Kepala", "requires_contrast": True,
            "preparation_note": "Lepas jepit rambut dan gigi palsu.",
            "estimated_minutes": 15, "dose_reference": "60 mGy·cm",
        })

    def _diet(self):
        return self.env["hms.diet.type"].create({
            "code": "ZT-API-DM", "name": "DM 1700 kkal Uji", "category": "special",
            "texture": "regular", "energy_kcal": 1700, "protein_g": 60,
            "is_therapeutic": True,
        })

    def test_lab_row_carries_every_key_the_cpoe_screen_reads(self):
        row = lab_test_row(self._lab_test())
        missing = [key for key in LAB_KEYS_READ_BY_CPOE if key not in row]
        self.assertFalse(
            missing,
            "Layar CPOE membaca kunci yang tidak ada di payload katalog lab: %s"
            % missing,
        )

    def test_lab_row_points_at_the_tariff_that_is_actually_ordered(self):
        """CPOE mengirim ``tariff_id``; katalog tanpa itu tidak bisa dipesan."""
        row = lab_test_row(self._lab_test())
        self.assertEqual(row["tariff_id"], self.lab_tariff.id)
        self.assertEqual(row["tariff_code"], "ZT-API-DL")

    def test_lab_row_lists_the_parameters_that_will_be_produced(self):
        row = lab_test_row(self._lab_test())
        self.assertEqual(row["parameter_count"], 2)
        self.assertEqual({p["name"] for p in row["parameters"]},
                         {"Hemoglobin", "Leukosit"})
        self.assertEqual({p["uom"] for p in row["parameters"]},
                         {"g/dL", "10³/µL"})

    def test_lab_row_empty_text_becomes_null_not_false(self):
        """``false`` di JSX merender kosong tanpa bekas; null jujur."""
        test = self._lab_test()
        test.note = False
        self.assertIsNone(lab_test_row(test)["note"])

    def test_rad_row_carries_every_key_the_cpoe_screen_reads(self):
        row = rad_exam_row(self._rad_exam())
        missing = [key for key in RAD_KEYS_READ_BY_CPOE if key not in row]
        self.assertFalse(
            missing,
            "Layar CPOE membaca kunci yang tidak ada di payload katalog "
            "radiologi: %s" % missing,
        )

    def test_rad_row_sends_the_human_label_not_the_raw_selection(self):
        """Layar menampilkan modalitas apa adanya; "ct" bukan bahasa manusia."""
        row = rad_exam_row(self._rad_exam())
        self.assertEqual(row["modality"], "ct")
        self.assertEqual(row["modality_label"], "CT Scan")
        self.assertTrue(row["requires_contrast"])
        self.assertIn("gigi palsu", row["preparation_note"])

    def test_diet_row_carries_every_key_the_nurse_screen_reads(self):
        row = diet_type_row(self._diet())
        missing = [key for key in DIET_KEYS_READ_BY_NURSE if key not in row]
        self.assertFalse(
            missing,
            "Layar gizi membaca kunci yang tidak ada di payload jenis diet: %s"
            % missing,
        )

    def test_diet_row_marks_therapeutic_diets_readably(self):
        """Diet terapeutik tidak boleh ditukar di dapur; penandanya harus sampai."""
        row = diet_type_row(self._diet())
        self.assertTrue(row["is_therapeutic"])
        self.assertEqual(row["category_label"], "Khusus / Terapeutik")
        self.assertEqual(row["texture_label"], "Biasa")
