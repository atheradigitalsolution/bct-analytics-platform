# -*- coding: utf-8 -*-
"""Empat view SQL laporan, diuji dengan data yang dikendalikan tes ini sendiri.

KENAPA MODUL INI HARUS PUNYA TES
--------------------------------
``hms.report.rl4`` menghasilkan angka yang dilaporkan ke Kementerian
Kesehatan. Ketiga view lainnya menjadi dasar BOR, ALOS dan pendapatan per
unit. Semuanya ``_table_query`` — SQL murni tanpa satu pun jalur Python yang
bisa melempar. Sebuah view yang salah **tidak pernah gagal**: ia mengembalikan
angka, dan angka yang salah terlihat persis seperti angka yang benar.

Yang diuji karena itu bukan "view-nya bisa di-query", melainkan tiga hal yang
bisa bergeser diam-diam:

1. **Penyaring baris** — apa yang SENGAJA tidak ikut dihitung. Setiap view
   punya kontrol negatifnya: kunjungan batal, baris tagihan draf, admisi
   batal, diagnosis kerja, diagnosis sekunder, kunjungan yang belum pulang.
   Tanpa kontrol negatif, melonggarkan satu ``WHERE`` tidak akan pernah
   membuat tes ini merah — dan melonggarkan ``WHERE`` adalah cara paling
   umum sebuah laporan mulai melaporkan terlalu banyak.
2. **Kolom pengelompokan** — ``age_group`` dan ``gender`` pada RL 4a dan
   laporan kunjungan, ``report_section``/``category_id`` pada pendapatan.
   RL 4a dilaporkan PER kelompok umur; batas kelompok yang bergeser satu
   tahun memindahkan kasus ke baris yang salah tanpa mengubah totalnya.
3. **Kardinalitas** — sensus harus menghasilkan satu baris per admisi per
   hari, bukan satu baris per admisi. ``patient_days`` adalah pembilang BOR.

CATATAN TEKNIS: ``flush_all()`` sebelum membaca
-----------------------------------------------
View membaca tabel ``hms_encounter``/``hms_bill_line``/... langsung. ORM tidak
tahu bahwa model laporan bergantung pada tabel model lain, jadi ia tidak akan
mem-flush apa pun sebelum ``search()``. Tanpa ``self.env.flush_all()``, record
yang baru dibuat tes belum ada di basis data dan laporannya kosong — gagal
yang terbaca seperti "view-nya salah".

CATATAN: basis data uji berisi data demo. Setiap assertion karena itu
menyaring ke record milik tes ini (``patient_id``/``encounter_id``), tidak
pernah menghitung seluruh isi view.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class HmsReportingCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payer = cls.env.ref("custom_hms_base.payer_self")
        cls.class_2 = cls.env.ref("custom_hms_base.care_class_2")
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-RPT-POLI", "name": "Poli Laporan", "type": "outpatient_clinic",
        })
        cls.ward_unit = cls.env["hms.unit"].create({
            "code": "ZT-RPT-RANAP", "name": "Ranap Laporan", "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-RPT-W", "name": "Bangsal Laporan", "unit_id": cls.ward_unit.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-RPT-R", "name": "R-Lap", "ward_id": cls.ward.id,
            "class_id": cls.class_2.id, "capacity": 4,
        })
        cls.beds = cls.env["hms.bed"].create([
            {"code": "ZT-RPT-B%d" % i, "name": str(i), "room_id": cls.room.id}
            for i in range(1, 4)
        ])
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Laporan DPJP", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101750055",
        })
        cls.icd = cls.env["hms.icd10"].create({
            "code": "ZT99.9", "name_en": "Report test condition",
            "name_id": "Kondisi uji laporan",
        })
        cls.icd_other = cls.env["hms.icd10"].create({
            "code": "ZT88.8", "name_en": "Other report test condition",
        })
        cls.category = cls.env["hms.tariff.category"].create({
            "code": "ZT-RPT-CAT", "name": "Kategori Laporan", "report_section": "procedure",
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-RPT-TRF", "name": "Tindakan Laporan",
            "category_id": cls.category.id, "unit_id": cls.unit.id,
        })

    # --- pembangun data ---------------------------------------------------
    _seq = 0

    @classmethod
    def _next(cls):
        HmsReportingCase._seq += 1
        return HmsReportingCase._seq

    def _patient(self, age_years, gender="male"):
        today = fields.Date.context_today(self.env.user)
        # Mundur satu hari dari ulang tahun supaya usianya pasti `age_years`
        # penuh dan tidak bergantung pada jam berapa tes dijalankan.
        birth = today.replace(year=today.year - age_years) - timedelta(days=1)
        return self.env["hms.patient"].create({
            "name": "Pasien Laporan %d" % self._next(),
            "gender": gender, "birth_date": birth,
            "nik": "3201010101%06d" % self._next(),
        })

    def _encounter(self, patient, **extra):
        values = {
            "patient_id": patient.id, "unit_id": self.unit.id,
            "payer_id": self.payer.id, "practitioner_id": self.dpjp.id,
        }
        values.update(extra)
        return self.env["hms.encounter"].create(values)

    def _rows(self, model, field, record_id):
        self.env.flush_all()
        return self.env[model].search([(field, "=", record_id)])

    # --- hms.report.visit -------------------------------------------------
    def test_visit_counts_a_visit_once_with_its_grouping_columns(self):
        patient = self._patient(30, gender="female")
        encounter = self._encounter(patient, type="emergency", visit_type="followup",
                                    triage_level="yellow")
        rows = self._rows("hms.report.visit", "encounter_id", encounter.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.visit_count, 1)
        self.assertEqual(rows.encounter_type, "emergency")
        self.assertEqual(rows.visit_type, "followup")
        self.assertEqual(rows.gender, "female")
        self.assertEqual(rows.age_group, "25 - 44 th")
        self.assertEqual(rows.unit_id, self.unit)
        self.assertEqual(rows.payer_id, self.payer)

    def test_visit_age_groups_follow_the_reported_bands(self):
        """Batas kelompok umur adalah bentuk laporannya, bukan detail kosmetik."""
        for age, expected in ((0, "0 - <1 th"), (4, "1 - 4 th"), (14, "5 - 14 th"),
                              (24, "15 - 24 th"), (44, "25 - 44 th"),
                              (64, "45 - 64 th"), (80, "65 th ke atas")):
            patient = self._patient(age)
            encounter = self._encounter(patient)
            rows = self._rows("hms.report.visit", "encounter_id", encounter.id)
            self.assertEqual(rows.age_group, expected,
                             "Usia %s masuk kelompok yang salah." % age)

    def test_visit_excludes_a_cancelled_visit(self):
        """KONTROL NEGATIF: kunjungan batal bukan kunjungan."""
        encounter = self._encounter(self._patient(30))
        self.assertEqual(len(self._rows("hms.report.visit", "encounter_id", encounter.id)), 1)
        encounter.action_cancel()
        self.assertEqual(
            len(self._rows("hms.report.visit", "encounter_id", encounter.id)), 0,
            "Kunjungan yang dibatalkan masih dihitung sebagai kunjungan.",
        )

    # --- hms.report.revenue -----------------------------------------------
    def _bill_with_line(self, **line_extra):
        encounter = self._encounter(self._patient(40))
        values = {
            "tariff_id": self.tariff.id, "name": "Baris Laporan",
            "qty": 2.0, "unit_price": 150000.0,
            "unit_id": self.unit.id, "practitioner_id": self.dpjp.id,
            "amount_medical": 100000.0, "amount_facility": 60000.0,
            "amount_consumable": 40000.0,
        }
        values.update(line_extra)
        return self.env["hms.bill"].create({
            "encounter_id": encounter.id, "line_ids": [(0, 0, values)],
        })

    def test_revenue_reports_a_confirmed_line_with_its_components(self):
        bill = self._bill_with_line()
        rows = self._rows("hms.report.revenue", "bill_id", bill.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.qty, 2.0)
        self.assertEqual(rows.amount_gross, 300000.0)
        self.assertEqual(rows.amount_medical, 100000.0)
        self.assertEqual(rows.amount_facility, 60000.0)
        self.assertEqual(rows.amount_consumable, 40000.0)
        self.assertEqual(rows.category_id, self.category)
        self.assertEqual(rows.report_section, "procedure")
        self.assertEqual(rows.unit_id, self.unit)
        self.assertEqual(rows.payer_id, self.payer)

    def test_revenue_counts_the_discount_separately_from_the_gross(self):
        bill = self._bill_with_line(discount_percent=10.0)
        rows = self._rows("hms.report.revenue", "bill_id", bill.id)
        self.assertEqual(rows.amount_gross, 300000.0,
                         "Bruto harus sebelum diskon; kalau tidak, diskonnya hilang dari laporan.")
        self.assertEqual(rows.amount_discount, 30000.0)

    def test_revenue_excludes_a_line_that_is_not_confirmed(self):
        """KONTROL NEGATIF: draf dan batal bukan pendapatan."""
        for state in ("draft", "cancelled"):
            bill = self._bill_with_line(state=state)
            self.assertEqual(
                len(self._rows("hms.report.revenue", "bill_id", bill.id)), 0,
                "Baris tagihan berstatus %s ikut dihitung sebagai pendapatan." % state,
            )

    # --- hms.report.census ------------------------------------------------
    def _admission(self, bed, days_ago_admitted, days_ago_discharged=None):
        encounter = self._encounter(self._patient(55), unit_id=self.ward_unit.id)
        admission = self.env["hms.admission"].admit(
            encounter, bed, self.dpjp, entitled_class=self.class_2,
        )
        now = fields.Datetime.now()
        values = {"admitted_at": now - timedelta(days=days_ago_admitted)}
        if days_ago_discharged is not None:
            values["discharged_at"] = now - timedelta(days=days_ago_discharged)
        admission.write(values)
        return admission

    def test_census_produces_one_row_per_day_occupied(self):
        """``patient_days`` adalah pembilang BOR; satu baris per admisi merusaknya."""
        admission = self._admission(self.beds[0], days_ago_admitted=2, days_ago_discharged=0)
        rows = self._rows("hms.report.census", "admission_id", admission.id)
        self.assertEqual(len(rows), 3, "Rawat inap 3 hari harus menghasilkan 3 baris sensus.")
        self.assertEqual(sum(rows.mapped("patient_days")), 3)
        self.assertEqual(sum(rows.mapped("admissions")), 1,
                         "Hari masuk harus dihitung tepat sekali.")
        self.assertEqual(sum(rows.mapped("discharges")), 1,
                         "Hari keluar harus dihitung tepat sekali.")
        self.assertEqual(set(rows.mapped("ward_id")), {self.ward})
        self.assertEqual(set(rows.mapped("payer_id")), {self.payer})

    def test_census_counts_a_patient_still_in_bed_up_to_today(self):
        admission = self._admission(self.beds[1], days_ago_admitted=1)
        rows = self._rows("hms.report.census", "admission_id", admission.id)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(rows.mapped("discharges")), 0,
                         "Pasien yang belum pulang tercatat sebagai pulang.")

    def test_census_excludes_a_cancelled_admission(self):
        """KONTROL NEGATIF: admisi batal tidak pernah memakai bed."""
        admission = self._admission(self.beds[2], days_ago_admitted=1, days_ago_discharged=0)
        self.assertEqual(len(self._rows("hms.report.census", "admission_id", admission.id)), 2)
        admission.write({"state": "cancelled"})
        self.assertEqual(
            len(self._rows("hms.report.census", "admission_id", admission.id)), 0,
            "Admisi yang dibatalkan masih menyumbang hari rawat.",
        )

    # --- hms.report.rl4 ---------------------------------------------------
    def _discharged_inpatient(self, age=50, gender="male", disposition="home",
                              rank="primary", stage="final", icd=None, state="discharged"):
        patient = self._patient(age, gender=gender)
        encounter = self._encounter(patient, type="inpatient", unit_id=self.ward_unit.id)
        self.env["hms.diagnosis"].create({
            "encounter_id": encounter.id, "icd10_id": (icd or self.icd).id,
            "rank": rank, "stage": stage,
        })
        encounter.write({
            "state": state,
            "closed_at": fields.Datetime.now(),
            "discharge_disposition": disposition,
        })
        return encounter

    def test_rl4_reports_one_case_per_discharged_inpatient(self):
        encounter = self._discharged_inpatient(age=70, gender="female")
        rows = self._rows("hms.report.rl4", "encounter_id", encounter.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.case_count, 1)
        self.assertEqual(rows.icd10_id, self.icd)
        self.assertEqual(rows.icd10_code, "ZT99.9")
        self.assertEqual(rows.gender, "female")
        self.assertEqual(rows.age_group, "65 th ke atas")
        self.assertEqual(rows.is_death, 0)
        self.assertEqual(rows.discharge_disposition, "home")

    def test_rl4_marks_a_death_as_a_death(self):
        """Kolom yang paling sering diperiksa dinas kesehatan."""
        encounter = self._discharged_inpatient(disposition="deceased")
        rows = self._rows("hms.report.rl4", "encounter_id", encounter.id)
        self.assertEqual(rows.is_death, 1)

    def test_rl4_ignores_a_working_diagnosis(self):
        """KONTROL NEGATIF: diagnosis kerja bukan diagnosis pulang.

        Menghitungnya akan melaporkan ulang setiap kasus yang diagnosisnya
        direvisi selama perawatan.
        """
        encounter = self._discharged_inpatient(stage="working")
        self.assertEqual(
            len(self._rows("hms.report.rl4", "encounter_id", encounter.id)), 0,
            "Diagnosis kerja ikut terhitung di RL 4a.",
        )

    def test_rl4_ignores_a_secondary_diagnosis(self):
        """KONTROL NEGATIF: RL 4a adalah morbiditas menurut diagnosis UTAMA."""
        encounter = self._discharged_inpatient(rank="secondary")
        self.assertEqual(
            len(self._rows("hms.report.rl4", "encounter_id", encounter.id)), 0,
            "Diagnosis sekunder ikut terhitung sebagai diagnosis utama.",
        )

    def test_rl4_counts_the_primary_diagnosis_once_when_others_exist(self):
        """Satu kasus = satu baris, meski kunjungan punya banyak diagnosis."""
        encounter = self._discharged_inpatient()
        self.env["hms.diagnosis"].create({
            "encounter_id": encounter.id, "icd10_id": self.icd_other.id,
            "rank": "secondary", "stage": "final",
        })
        rows = self._rows("hms.report.rl4", "encounter_id", encounter.id)
        self.assertEqual(len(rows), 1,
                         "Diagnosis sekunder menggandakan kasusnya di RL 4a.")
        self.assertEqual(rows.icd10_id, self.icd)

    def test_rl4_ignores_a_visit_that_has_not_gone_home(self):
        """KONTROL NEGATIF: RL 4a melaporkan pasien yang SUDAH keluar."""
        encounter = self._discharged_inpatient(state="admitted")
        self.assertEqual(
            len(self._rows("hms.report.rl4", "encounter_id", encounter.id)), 0,
            "Pasien yang masih dirawat sudah dilaporkan sebagai kasus keluar.",
        )

    def test_rl4_ignores_an_outpatient_visit(self):
        """KONTROL NEGATIF: RL 4a adalah morbiditas RAWAT INAP."""
        patient = self._patient(30)
        encounter = self._encounter(patient, type="outpatient")
        self.env["hms.diagnosis"].create({
            "encounter_id": encounter.id, "icd10_id": self.icd.id,
            "rank": "primary", "stage": "final",
        })
        encounter.write({"state": "discharged", "closed_at": fields.Datetime.now()})
        self.assertEqual(
            len(self._rows("hms.report.rl4", "encounter_id", encounter.id)), 0,
            "Kunjungan rawat jalan masuk ke laporan morbiditas rawat inap.",
        )
