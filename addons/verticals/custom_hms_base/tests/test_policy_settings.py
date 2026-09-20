# -*- coding: utf-8 -*-
"""Parameter kebijakan rumah sakit dan field master parametrik.

Gelombang ini hanya menambah *titik konfigurasi*: tidak ada modul yang membaca
nilai-nilai ini. Yang bisa rusak diam-diam karena itu bukan logikanya,
melainkan (a) default yang tidak pernah mendarat di kolom sehingga administrator
melihat nol di mana seharusnya ada tenggat, dan (b) Selection yang ternyata
menerima nilai sembarang. Dua hal itulah yang diuji di sini.
"""
from odoo.tests import TransactionCase, tagged

# Default yang dijanjikan ke administrator RS. Dipisah dari badan kelas: sebuah
# konstanta yang ditulis di tengah badan kelas tes membuat setiap method
# test_* sesudahnya berhenti dikoleksi tanpa ada yang gagal.
EXPECTED_INT_DEFAULTS = {
    "critical_result_ack_minutes": 30,
    "incident_report_due_hours": 48,
    "klpcm_due_hours": 48,
    "discharge_summary_due_hours": 24,
    "emr_correction_grace_hours": 48,
    "emr_retention_years": 25,
    "titip_kelas_max_days": 3,
    "half_day_grace_hours": 6,
    "claim_expiry_months": 6,
    "readmission_window_days": 30,
    "fragmentation_window_days": 7,
}
EXPECTED_SELECTION_DEFAULTS = {
    "sep_igd_to_inpatient_policy": "merge",
    "grouper_mode": "inacbg",
    "jkn_revenue_basis": "cbg_final",
    "hpp_mode": "perpetual_custom",
}


@tagged("post_install", "-at_install", "hms")
class TestPolicySettings(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Settings = cls.env["hms.settings"]
        cls.settings = cls.Settings.get_settings()

    def test_integer_policy_defaults_are_declared(self):
        """default_get menjawab pertanyaan 'record baru dapat nilai apa'."""
        defaults = self.Settings.default_get(list(EXPECTED_INT_DEFAULTS))
        for field, expected in EXPECTED_INT_DEFAULTS.items():
            self.assertEqual(
                defaults.get(field), expected,
                f"Default {field} seharusnya {expected}, dapat {defaults.get(field)!r}",
            )

    def test_integer_policy_defaults_landed_on_existing_row(self):
        """Kolom baru pada baris pengaturan yang sudah ada harus terisi default."""
        for field, expected in EXPECTED_INT_DEFAULTS.items():
            self.assertEqual(
                self.settings[field], expected,
                f"{field} pada singleton seharusnya {expected}",
            )

    def test_selection_policy_defaults(self):
        defaults = self.Settings.default_get(list(EXPECTED_SELECTION_DEFAULTS))
        for field, expected in EXPECTED_SELECTION_DEFAULTS.items():
            self.assertEqual(defaults.get(field), expected)
            self.assertEqual(self.settings[field], expected)

    def test_float_policy_defaults(self):
        self.assertAlmostEqual(self.settings.checkout_time, 12.0)
        self.assertAlmostEqual(self.settings.claim_variance_threshold, 4000000.0)
        self.assertAlmostEqual(self.settings.stamp_duty_threshold, 5000000.0)
        self.assertAlmostEqual(self.settings.cash_variance_tolerance, 0.0)

    def test_prorate_partial_days_defaults_off(self):
        """Prorata belum terverifikasi terhadap ketentuan BPJS: harus mati."""
        self.assertFalse(self.settings.prorate_partial_days)

    def test_billing_lock_date_starts_empty(self):
        self.assertFalse(self.settings.billing_lock_date)

    def test_grouper_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            self.settings.write({"grouper_mode": "drg_luar_negeri"})

    def test_sep_policy_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            self.settings.write({"sep_igd_to_inpatient_policy": "terserah"})

    def test_jkn_revenue_basis_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            self.settings.write({"jkn_revenue_basis": "kas"})

    def test_hpp_mode_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            self.settings.write({"hpp_mode": "fifo_gudang"})

    def test_selection_accepts_every_declared_key(self):
        """Setiap kunci yang ditawarkan UI harus benar-benar bisa disimpan."""
        for field in EXPECTED_SELECTION_DEFAULTS:
            for key, _label in self.settings._fields[field].selection:
                self.settings.write({field: key})
                self.assertEqual(self.settings[field], key)

    def test_policy_parameters_survive_a_write(self):
        self.settings.write({
            "critical_result_ack_minutes": 15,
            "emr_retention_years": 30,
            "checkout_time": 14.5,
            "cash_variance_tolerance": 2500.0,
            "billing_lock_date": "2026-01-31",
        })
        self.settings.invalidate_recordset()
        self.assertEqual(self.settings.critical_result_ack_minutes, 15)
        self.assertEqual(self.settings.emr_retention_years, 30)
        self.assertAlmostEqual(self.settings.checkout_time, 14.5)
        self.assertAlmostEqual(self.settings.cash_variance_tolerance, 2500.0)
        self.assertEqual(str(self.settings.billing_lock_date), "2026-01-31")


@tagged("post_install", "-at_install", "hms")
class TestParametricMasterFields(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.care_class = cls.env.ref("custom_hms_base.care_class_2")

    def test_icd10_im_flag_is_settable(self):
        code = self.env["hms.icd10"].create({
            "code": "ZT-A15.0", "name_en": "Tuberculosis of lung", "name_id": "TB paru",
        })
        self.assertFalse(code.is_icd10_im)
        code.is_icd10_im = True
        code.invalidate_recordset()
        self.assertTrue(code.is_icd10_im)

    def test_icd9_special_cmg_flag_is_settable(self):
        proc = self.env["hms.icd9"].create({"code": "ZT-39.95", "name": "Hemodialisis"})
        self.assertFalse(proc.is_special_cmg)
        proc.is_special_cmg = True
        proc.invalidate_recordset()
        self.assertTrue(proc.is_special_cmg)

    def test_care_class_carries_jkn_code(self):
        self.assertFalse(self.care_class.jkn_class_code)
        self.care_class.jkn_class_code = "2"
        self.care_class.invalidate_recordset()
        self.assertEqual(self.care_class.jkn_class_code, "2")

    def test_room_kris_flag_is_settable(self):
        unit = self.env["hms.unit"].create({
            "code": "ZT-KRIS-UNIT", "name": "Rawat Inap KRIS", "type": "inpatient",
        })
        ward = self.env["hms.ward"].create({
            "code": "ZT-KRIS-W", "name": "Anggrek", "unit_id": unit.id,
        })
        room = self.env["hms.room"].create({
            "code": "ZT-KRIS-R1", "name": "201", "ward_id": ward.id,
            "class_id": self.care_class.id,
        })
        self.assertFalse(room.is_kris_compliant)
        room.is_kris_compliant = True
        room.invalidate_recordset()
        self.assertTrue(room.is_kris_compliant)

    def test_practitioner_tax_status_defaults_to_non_employee(self):
        doctor = self.env["hms.practitioner"].create({
            "name": "Sari Dewi", "type": "doctor", "nik": "3201010101850001",
        })
        self.assertEqual(doctor.tax_status, "non_employee")
        self.assertFalse(doctor.npwp)

    def test_practitioner_tax_status_rejects_unknown_value(self):
        doctor = self.env["hms.practitioner"].create({
            "name": "Rudi Hartono", "type": "doctor", "nik": "3201010101850002",
        })
        with self.assertRaises(ValueError):
            doctor.write({"tax_status": "pph_final"})

    def test_practitioner_npwp_is_stored(self):
        doctor = self.env["hms.practitioner"].create({
            "name": "Lina Mardiana", "type": "doctor", "nik": "3201010101850003",
            "tax_status": "badan", "npwp": "01.234.567.8-901.000",
        })
        doctor.invalidate_recordset()
        self.assertEqual(doctor.tax_status, "badan")
        self.assertEqual(doctor.npwp, "01.234.567.8-901.000")

    def test_payer_cob_and_aps_defaults(self):
        payer = self.env["hms.payer"].create({
            "code": "ZT-COB", "name": "Asuransi Pelengkap", "type": "insurance",
        })
        self.assertEqual(payer.cob_order, 0)
        self.assertFalse(payer.aps_covered)

    def test_payer_cob_order_is_stored(self):
        payer = self.env["hms.payer"].create({
            "code": "ZT-COB2", "name": "Asuransi Kedua", "type": "insurance",
            "cob_order": 2, "aps_covered": True,
        })
        payer.invalidate_recordset()
        self.assertEqual(payer.cob_order, 2)
        self.assertTrue(payer.aps_covered)

    def test_tariff_category_eklaim_component_is_free_text(self):
        """Char, bukan Selection: enumerasi 18 komponen belum terverifikasi."""
        category = self.env["hms.tariff.category"].create({
            "code": "ZT-EKL", "name": "Tindakan Non Bedah", "report_section": "procedure",
            "eklaim_component": "prosedur_non_bedah",
        })
        category.invalidate_recordset()
        self.assertEqual(category.eklaim_component, "prosedur_non_bedah")
        self.assertEqual(category._fields["eklaim_component"].type, "char")
