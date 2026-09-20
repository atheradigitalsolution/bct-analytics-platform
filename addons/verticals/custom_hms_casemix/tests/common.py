# -*- coding: utf-8 -*-
"""Data minimum untuk menguji klaim, termasuk berkas yang lengkap.

Sebagian besar tes di sini butuh satu hal yang mahal disiapkan: kunjungan yang
**berkasnya lengkap**, karena tanpa itu gerbang KLPCM menolak semuanya dan
seluruh state machine tidak pernah tersentuh. ``_claimable_encounter``
menyiapkannya, dan ``tests/test_klpcm_gate.py`` yang membuktikan gerbangnya
memang menolak ketika berkasnya tidak lengkap.
"""
from odoo.tests import TransactionCase


class CasemixCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-CM-POLI", "name": "Poli Uji Casemix", "type": "outpatient_clinic",
        })
        cls.unit_b = cls.env["hms.unit"].create({
            "code": "ZT-CM-POLI-B", "name": "Poli Uji Casemix B",
            "type": "outpatient_clinic",
        })
        cls.ward = cls.env["hms.unit"].create({
            "code": "ZT-CM-RANAP", "name": "Bangsal Uji Casemix", "type": "inpatient",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Hendra Gunawan", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501860021", "unit_ids": [(4, cls.unit.id)],
        })
        cls.nurse = cls.env["hms.practitioner"].create({
            "name": "Wulan Sari", "type": "nurse", "nik": "3201014501860022",
        })
        cls.consent_template = cls.env["hms.consent.template"].create({
            "code": "ZT-CM-GC", "name": "Persetujuan Umum Casemix", "type": "general",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Sulistyo Adi", "nik": "3201010101870021",
            "birth_date": "1987-05-05", "gender": "male",
        })
        cls.payer = cls.env.ref("custom_hms_base.payer_self")
        cls.icd_a = cls.env["hms.icd10"].create({
            "code": "ZC10", "name_en": "Casemix condition A", "name_id": "Kondisi A",
        })
        cls.icd_b = cls.env["hms.icd10"].create({
            "code": "ZC11", "name_en": "Casemix condition B", "name_id": "Kondisi B",
        })
        cls.icd9_a = cls.env["hms.icd9"].create({
            "code": "ZC90", "name": "Tindakan uji A",
        })
        cls.Claim = cls.env["hms.claim"]
        cls.Code = cls.env["hms.claim.code"]

    # --- pembangun kunjungan ---------------------------------------------
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

    @classmethod
    def _complete_documents(cls, encounter, icd10=None):
        """Isi berkas sampai analisis KLPCM tidak menemukan apa pun.

        Daftar yang harus diisi berbeda per jenis kunjungan — itu keputusan
        ``hms.klpcm._required_components``, dan helper ini mengikutinya alih-
        alih menduplikasi daftarnya. Rawat inap menuntut asesmen awal medis,
        asesmen awal keperawatan dan persetujuan; rawat jalan tidak.
        """
        note = cls.env["hms.clinical.note"].create({
            "encounter_id": encounter.id,
            "author_id": cls.doctor.id,
            "note_type": "soap",
            "subjective": "Keluhan uji",
            "assessment": "Asesmen uji",
            "plan": "Rencana uji",
        })
        note.action_sign()
        required = cls.env["hms.klpcm"]._required_components(encounter)
        if "initial_medical" in required:
            initial = cls.env["hms.clinical.note"].create({
                "encounter_id": encounter.id,
                "author_id": cls.doctor.id,
                "note_type": "medical_initial",
                "subjective": "Anamnesis awal",
                "assessment": "Asesmen awal medis",
                "plan": "Rencana awal",
            })
            initial.action_sign()
        if "initial_nursing" in required:
            cls.env["hms.nursing.assessment"].create({
                "encounter_id": encounter.id,
                "nurse_id": cls.nurse.id,
                "type": "initial",
            })
        if "consent" in required:
            consent = cls.env["hms.consent"].create({
                "encounter_id": encounter.id,
                "patient_id": encounter.patient_id.id,
                "template_id": cls.consent_template.id,
                "signer_name": encounter.patient_id.name,
            })
            consent.action_sign()
        diagnosis = cls.env["hms.diagnosis"].create({
            "encounter_id": encounter.id,
            "icd10_id": (icd10 or cls.icd_a).id,
            "rank": "primary",
            "stage": "final",
            "practitioner_id": cls.doctor.id,
        })
        summary = cls.env["hms.summary"].create({
            "encounter_id": encounter.id,
            "type": "discharge" if encounter.type == "inpatient" else "outpatient",
            "practitioner_id": cls.doctor.id,
            "diagnosis_primary_id": (icd10 or cls.icd_a).id,
        })
        summary.action_finalize()
        return diagnosis

    @classmethod
    def _claimable_encounter(cls, icd10=None, **kw):
        """Kunjungan rawat jalan yang berkasnya lengkap dan sudah ditutup."""
        encounter = cls._encounter(**kw)
        diagnosis = cls._complete_documents(encounter, icd10=icd10)
        encounter.action_close()
        return encounter, diagnosis

    @classmethod
    def _claim(cls, encounter=None, **kw):
        if encounter is None:
            encounter, _diagnosis = cls._claimable_encounter()
        vals = {
            "encounter_id": encounter.id,
            "payer_id": encounter.payer_id.id,
            "kind": "bpjs_inacbg",
        }
        vals.update(kw)
        return cls.Claim.create(vals)

    def _coded_claim(self, encounter=None, diagnosis=None, **kw):
        """Klaim yang sudah melewati koding dengan satu diagnosis utama."""
        if encounter is None:
            encounter, diagnosis = self._claimable_encounter()
        claim = self._claim(encounter, **kw)
        claim.action_start_coding()
        self.Code.create({
            "claim_id": claim.id,
            "kind": "icd10",
            "icd10_id": diagnosis.icd10_id.id if diagnosis else self.icd_a.id,
            "role": "principal",
            "source_diagnosis_id": diagnosis.id if diagnosis else False,
            "change_reason": False if diagnosis else "Kode tambahan tanpa sumber.",
        })
        return claim

    def _batch_for(self, claim, **kw):
        vals = {
            "service_period": claim.discharge_at.date().replace(day=1),
            "care_type": claim.care_type,
            "batch_type": "regular",
            "payer_id": claim.payer_id.id,
        }
        vals.update(kw)
        return self.env["hms.claim.batch"].create(vals)

    def _role_user(self, login, name, group_xmlids):
        return self.env["res.users"].create({
            "name": name,
            "login": login,
            "group_ids": [(4, self.env.ref(x).id) for x in group_xmlids],
        })
