# -*- coding: utf-8 -*-
"""Aturan NIK pasien demo.

KENAPA BERKAS INI ADA
---------------------
NIK yang seragam terlihat palsu; NIK yang mengkode tanggal lahir yang BUKAN
milik pasiennya lebih buruk lagi, karena ia terlihat benar sampai ada orang
rumah sakit yang memeriksanya di depan calon klien. Aturannya karena itu
diuji, bukan dipercaya.

KONTROL POSITIF YANG DIABADIKAN
-------------------------------
``test_the_plus_forty_rule_applies_to_women_only`` memeriksa DUA arah pada
tanggal yang sama: laki-laki lahir tanggal 25 harus berhari ``25``, perempuan
lahir tanggal 25 harus berhari ``65``. Generator yang menambah 40 kepada
SIAPA PUN lolos dengan gemilang bila hanya sisi perempuan yang diuji, dan
itulah cacat yang paling mudah ditulis.
"""
from datetime import date

from odoo import fields
from odoo.tests import TransactionCase, tagged

from odoo.addons.custom_hms_demo.models.hms_demo_identity import (
    NIK_REGIONS,
    nik_for,
)


@tagged("post_install", "-at_install", "hms")
class DemoNikRuleCase(TransactionCase):
    """Aturan generatornya sendiri, tanpa menyentuh basis data."""

    def test_a_nik_is_sixteen_digits(self):
        nik = nik_for(1, date(1988, 3, 7), "male")
        self.assertEqual(len(nik), 16, nik)
        self.assertTrue(nik.isdigit(), nik)

    def test_a_nik_encodes_the_birth_date_it_was_given(self):
        nik = nik_for(1, date(1988, 3, 7), "male")
        self.assertEqual(nik[6:12], "070388", nik)

    def test_the_plus_forty_rule_applies_to_women_only(self):
        """Kontrol positif dua arah pada tanggal yang sama."""
        born = date(1975, 11, 25)
        self.assertEqual(nik_for(14, born, "male")[6:8], "25")
        self.assertEqual(nik_for(14, born, "female")[6:8], "65")

    def test_the_plus_forty_rule_keeps_month_and_year_untouched(self):
        born = date(1975, 11, 25)
        self.assertEqual(nik_for(14, born, "female")[6:12], "651175")

    def test_the_generator_is_deterministic(self):
        born = date(2001, 1, 2)
        self.assertEqual(nik_for(507, born, "female"), nik_for(507, born, "female"))

    def test_two_different_patients_never_share_a_nik(self):
        """Termasuk saat tanggal lahir dan jenis kelaminnya sama persis."""
        born = date(1990, 6, 15)
        seen = {nik_for(i, born, "male") for i in range(1, 400)}
        self.assertEqual(len(seen), 399)

    def test_the_region_code_is_not_the_same_for_everyone(self):
        born = date(1990, 6, 15)
        regions = {nik_for(i, born, "male")[:6] for i in range(1, 400)}
        self.assertEqual(regions, {code for code, _name in NIK_REGIONS})

    def test_an_id_too_large_for_the_serial_is_refused_not_wrapped(self):
        """Nomor urut hanya 4 digit; membungkusnya diam-diam merusak keunikan."""
        with self.assertRaises(ValueError):
            nik_for(len(NIK_REGIONS) * 10000, date(1990, 6, 15), "male")


@tagged("post_install", "-at_install", "hms")
class SeededPatientNikCase(TransactionCase):
    """Yang benar-benar tersimpan di pasien demo, bukan yang dijanjikan kode."""

    def _patients(self):
        return self.env["hms.patient"].search([("nik", "!=", False)])

    def test_every_seeded_patient_has_a_sixteen_digit_nik(self):
        patients = self._patients()
        self.assertTrue(patients)
        bad = patients.filtered(lambda p: len(p.nik or "") != 16 or not p.nik.isdigit())
        self.assertFalse(bad.mapped("mrn"), "NIK bukan 16 digit angka.")

    def test_every_nik_encodes_its_own_patients_birth_date_and_sex(self):
        mismatched = []
        for patient in self._patients():
            if not patient.birth_date:
                continue
            day = patient.birth_date.day + (40 if patient.gender == "female" else 0)
            expected = "%02d%02d%02d" % (
                day, patient.birth_date.month, patient.birth_date.year % 100,
            )
            if patient.nik[6:12] != expected:
                mismatched.append(
                    "%s %s: NIK %s mengkode %s, lahir %s (%s)"
                    % (patient.mrn, patient.name, patient.nik, patient.nik[6:12],
                       patient.birth_date, patient.gender)
                )
        self.assertFalse(mismatched, "\n".join(mismatched[:10]))

    def test_niks_are_unique_across_the_register(self):
        niks = self._patients().mapped("nik")
        self.assertEqual(len(niks), len(set(niks)))

    def test_the_register_is_not_one_region_pretending_to_be_many(self):
        """Lima puluh NIK dengan satu awalan yang sama terbaca sebagai karangan."""
        prefixes = {nik[:6] for nik in self._patients().mapped("nik")}
        self.assertGreaterEqual(
            len(prefixes), 4,
            "Hanya %s kode wilayah pada seluruh register pasien." % len(prefixes),
        )

    def test_both_sexes_are_represented_so_the_rule_is_actually_exercised(self):
        patients = self._patients().filtered("birth_date")
        self.assertTrue(patients.filtered(lambda p: p.gender == "female"))
        self.assertTrue(patients.filtered(lambda p: p.gender == "male"))

    def test_women_carry_the_offset_and_men_do_not(self):
        """Dua arah pada data nyata: tak satu pun laki-laki berhari > 31."""
        patients = self._patients().filtered("birth_date")
        men = patients.filtered(lambda p: p.gender == "male")
        women = patients.filtered(lambda p: p.gender == "female")
        self.assertFalse(
            men.filtered(lambda p: int(p.nik[6:8]) > 31),
            "Ada NIK laki-laki yang memakai kaidah +40.",
        )
        self.assertFalse(
            women.filtered(lambda p: int(p.nik[6:8]) <= 31),
            "Ada NIK perempuan tanpa kaidah +40.",
        )

    def test_no_patient_is_named_like_a_leftover_test(self):
        """Nama sisa uji coba tidak boleh muncul di layar penjualan."""
        named = self.env["hms.patient"].search([]).filtered(
            lambda p: p.name in ("Uji API", "Beda", "Uji API Dua")
        )
        self.assertFalse(named.mapped("mrn"))

    def test_the_restored_records_kept_their_clinical_history(self):
        """Dipulihkan, bukan dihapus: isi klinisnya justru yang dibutuhkan deck."""
        restored = self.env["hms.patient"].search([
            ("mrn", "in", ("RM-2026-000001", "RM-2026-000002", "RM-2026-000003")),
        ])
        self.assertEqual(len(restored), 3)
        for patient in restored:
            self.assertTrue(patient.birth_date)
            self.assertTrue(patient.address_street)
            self.assertTrue(patient.default_payer_id)

    def test_the_fiftieth_record_is_not_mistaken_for_a_probe(self):
        """RM-2026-000050 dibuat bersama semaian massal; ia harus tetap ada."""
        self.assertTrue(
            self.env["hms.patient"].search([("mrn", "=", "RM-2026-000050")]),
            "RM-2026-000050 ikut terhapus — itu pasien semaian, bukan pasien uji.",
        )

    def test_no_registration_stays_open_past_its_own_day(self):
        """Pendaftaran Terdaftar dari hari lampau = pasien yang menunggu selamanya."""
        today = fields.Date.context_today(self.env["hms.encounter"])
        stale = self.env["hms.encounter"].search([
            ("state", "=", "registered"),
            ("arrival_at", "<", "%s 00:00:00" % today),
        ])
        self.assertFalse(stale.mapped("name"))
