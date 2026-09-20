# -*- coding: utf-8 -*-
"""Data minimum untuk menguji rekam medis.

Dipisah ke berkas sendiri, bukan ditaruh sebagai helper di tengah badan kelas
tes: sebuah ``def`` non-``test_`` yang tersisip di antara metode tes memang
tetap jalan, tetapi memisahkannya membuat jumlah tes yang dikumpulkan tidak
pernah bergantung pada urutan penulisan.
"""
from odoo.tests import TransactionCase


class MedrecCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RM-POLI", "name": "Poli Uji Rekam Medis", "type": "outpatient_clinic",
        })
        cls.ward_unit = cls.env["hms.unit"].create({
            "code": "ZT-RM-RANAP", "name": "Bangsal Uji Rekam Medis", "type": "inpatient",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Sri Mulyani", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501860011", "unit_ids": [(4, cls.unit.id)],
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Tuti Herawati", "type": "nurse", "nik": "3201014501860012",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Bagus Prasetyo", "nik": "3201010101870011",
            "birth_date": "1987-01-01", "gender": "male",
        })
        cls.payer = cls.env.ref("custom_hms_base.payer_self")
        cls.icd_a = cls.env["hms.icd10"].create({
            "code": "ZT10", "name_en": "Test condition A", "name_id": "Kondisi uji A",
        })
        cls.icd_b = cls.env["hms.icd10"].create({
            "code": "ZT11", "name_en": "Test condition B", "name_id": "Kondisi uji B",
        })
        cls.icd_c = cls.env["hms.icd10"].create({
            "code": "ZT12", "name_en": "Test condition C", "name_id": "Kondisi uji C",
        })

    @classmethod
    def _encounter(cls, **kw):
        vals = {
            "patient_id": cls.patient.id,
            "unit_id": cls.unit.id,
            "payer_id": cls.payer.id,
            "practitioner_id": cls.doctor.id,
            "type": "outpatient",
        }
        vals.update(kw)
        return cls.env["hms.encounter"].create(vals)

    def _signed_note(self, encounter, **kw):
        vals = {
            "encounter_id": encounter.id,
            "author_id": self.doctor.id,
            "note_type": "soap",
            "subjective": "Keluhan uji",
            "assessment": "Asesmen uji",
            "plan": "Rencana uji",
        }
        vals.update(kw)
        note = self.env["hms.clinical.note"].create(vals)
        note.action_sign()
        return note

    def _final_summary(self, encounter, summary_type="outpatient"):
        summary = self.env["hms.summary"].create({
            "encounter_id": encounter.id,
            "type": summary_type,
            "practitioner_id": self.doctor.id,
            "diagnosis_primary_id": self.icd_a.id,
        })
        summary.action_finalize()
        return summary

    def _complete_and_close(self, encounter, summary_type="outpatient"):
        """Isi berkas selengkap yang dituntut lalu tutup kunjungannya."""
        self._signed_note(encounter)
        self._final_summary(encounter, summary_type)
        encounter.action_close()
        return encounter

    def _role_user(self, login, name, group_xmlids):
        return self.env["res.users"].create({
            "name": name,
            "login": login,
            "group_ids": [(4, self.env.ref(x).id) for x in group_xmlids],
        })
