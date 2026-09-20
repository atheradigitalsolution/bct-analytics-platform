# -*- coding: utf-8 -*-
"""Reference ranges, flagging, critical values and the two-step release."""
from datetime import timedelta

from odoo import fields
from odoo.addons.custom_hms_base.models.hms_critical_ack import (
    CRITICAL_ACK_WRITABLE_FIELDS,
)
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

# Helper-helper di level MODUL, bukan di badan kelas: sebuah definisi non-`def`
# di tengah badan kelas tes pernah membuat seluruh `test_*` setelahnya berhenti
# dikoleksi tanpa satu pun kegagalan muncul.
VERIFIER_GROUP = "custom_hms_base.group_hms_diagnostic_verifier"
CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"
CRITICAL_HB = 5.0
NORMAL_HB = 14.0


@tagged("post_install", "-at_install", "hms")
class TestLab(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.lab_unit = cls.env["hms.unit"].create({
            "code": "ZT-LAB-T", "name": "Laboratorium", "type": "lab",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-LAB", "name": "Poli Uji Lab", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Hendra Gunawan", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101800011", "user_id": cls.env.user.id,
        })
        cls.hb = cls.env["hms.lab.parameter"].create({
            "code": "ZT-HB", "name": "Hemoglobin", "uom_name": "g/dL",
            "range_ids": [
                # Adult male, adult female, and infant: the same number means
                # three different things across these rows.
                (0, 0, {"gender": "male", "age_from": 15, "ref_low": 13.0, "ref_high": 17.0,
                        "critical_low": 7.0, "critical_high": 20.0}),
                (0, 0, {"gender": "female", "age_from": 15, "ref_low": 12.0, "ref_high": 15.0,
                        "critical_low": 7.0, "critical_high": 20.0}),
                (0, 0, {"age_from": 0, "age_to": 14, "ref_low": 11.0, "ref_high": 14.0,
                        "critical_low": 6.0, "critical_high": 19.0}),
            ],
        })
        # Klinisi sungguhan, terpisah dari pengguna penjalan tes: tes yang
        # berjalan sebagai superuser melewati SEMUA hak akses, jadi hak
        # kolom-terbatas hanya bisa dibuktikan lewat .with_user().
        cls.clinician_user = cls.env["res.users"].create({
            "name": "dr. Sinta Prameswari", "login": "zt-lab-clinician",
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.clinician = cls.env["hms.practitioner"].create({
            "name": "Sinta Prameswari", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101800012", "user_id": cls.clinician_user.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-LAB-HB", "name": "Hemoglobin",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_lab").id,
            "unit_id": cls.lab_unit.id,
            "lab_parameter_ids": [(4, cls.hb.id)],
        })

    def _patient(self, gender="male", birth="1985-01-01", name="Pasien Lab"):
        return self.env["hms.patient"].create({
            "name": name, "gender": gender, "birth_date": birth,
            "nik": f"32010101010{self.env['hms.patient'].search_count([]) + 10:05d}",
        })

    def _ordered_line(self, patient, practitioner=None):
        practitioner = practitioner or self.doctor
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": practitioner.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "lab",
            "practitioner_id": self.doctor.id, "target_unit_id": self.lab_unit.id,
            "line_ids": [(0, 0, {"tariff_id": self.tariff.id})],
        })
        order.action_submit()
        order.line_ids.action_start()
        return order.line_ids

    def _critical_verified(self, value=CRITICAL_HB, practitioner=None):
        """Hasil kritis yang sudah lolos dua langkah pelepasan."""
        line = self._ordered_line(self._patient(), practitioner=practitioner)
        result = line.lab_result_ids
        result.value_numeric = value
        result.action_enter()
        result.action_validate()
        result.action_verify()
        return result

    def _other_verifier(self, login):
        return self.env["res.users"].create({
            "name": "dr. Penerima Laporan", "login": login,
            "group_ids": [(4, self.env.ref(VERIFIER_GROUP).id)],
        })

    def test_starting_a_lab_line_creates_one_result_per_parameter(self):
        line = self._ordered_line(self._patient())
        self.assertEqual(line.lab_result_count, 1)
        self.assertEqual(line.lab_result_ids.parameter_id, self.hb)
        self.assertEqual(line.lab_result_ids.state, "pending")

    def test_range_selection_follows_sex(self):
        male = self.hb.find_range(gender="male", age_years=30)
        female = self.hb.find_range(gender="female", age_years=30)
        self.assertAlmostEqual(male.ref_low, 13.0)
        self.assertAlmostEqual(female.ref_low, 12.0)

    def test_range_selection_follows_age(self):
        child = self.hb.find_range(gender="male", age_years=5)
        self.assertAlmostEqual(child.ref_high, 14.0)

    def test_value_normal_for_a_man_is_high_for_a_child(self):
        """The same 15.5 g/dL reads differently depending on the patient."""
        man = self._ordered_line(self._patient("male", "1985-01-01", "Pria Dewasa"))
        man.lab_result_ids.value_numeric = 15.5
        self.assertEqual(man.lab_result_ids.flag, "normal")

        child_patient = self._patient("male", "2020-01-01", "Anak")
        child = self._ordered_line(child_patient)
        child.lab_result_ids.value_numeric = 15.5
        self.assertEqual(child.lab_result_ids.flag, "high")

    def test_low_and_high_flags(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 10.0
        self.assertEqual(result.flag, "low")
        result.value_numeric = 18.0
        self.assertEqual(result.flag, "high")

    def test_critical_values_are_flagged_and_marked(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 6.0
        self.assertEqual(result.flag, "critical_low")
        self.assertTrue(result.is_critical)

    def test_two_step_release_is_enforced(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 14.0
        with self.assertRaises(UserError):
            result.action_verify()
        result.action_enter()
        with self.assertRaises(UserError):
            result.action_verify()
        result.action_validate()
        result.action_verify()
        self.assertEqual(result.state, "verified")

    def test_verifying_every_parameter_closes_the_order_line(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 14.0
        result.action_enter()
        result.action_validate()
        result.action_verify()
        self.assertEqual(line.state, "done")

    def test_critical_result_emits_a_dedicated_event(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 5.0
        result.action_enter()
        result.action_validate()
        before = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        result.action_verify()
        after = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        self.assertEqual(after, before + 1)

    def test_normal_result_does_not_emit_a_critical_event(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = 14.0
        result.action_enter()
        result.action_validate()
        before = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        result.action_verify()
        after = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        self.assertEqual(after, before)

    def test_critical_threshold_must_sit_outside_the_reference_range(self):
        with self.assertRaises(ValidationError):
            self.env["hms.lab.reference.range"].create({
                "parameter_id": self.hb.id, "ref_low": 12.0, "ref_high": 15.0,
                "critical_low": 13.0,
            })

    # ------------------------------------------------------------------
    # Closed-loop nilai kritis
    # ------------------------------------------------------------------
    def test_non_critical_result_needs_no_acknowledgement(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = NORMAL_HB
        result.action_enter()
        result.action_validate()
        result.action_verify()
        self.assertFalse(result.is_critical)
        self.assertEqual(result.ack_state, "not_required")
        with self.assertRaises(UserError):
            result.action_acknowledge()

    def test_unverified_critical_result_cannot_be_acknowledged(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = CRITICAL_HB
        result.action_enter()
        self.assertTrue(result.is_critical)
        # Belum dilepas ke rekam medis: jamnya belum berjalan.
        self.assertEqual(result.ack_state, "not_required")
        with self.assertRaises(UserError):
            result.action_acknowledge()

    def test_freshly_verified_critical_result_is_pending(self):
        result = self._critical_verified()
        self.assertTrue(result.is_critical)
        self.assertEqual(result.ack_state, "pending")
        self.assertEqual(result.ack_minutes, 0)

    def test_critical_result_past_the_deadline_is_overdue(self):
        settings = self.env["hms.settings"].get_settings()
        result = self._critical_verified()
        result.verified_at = fields.Datetime.now() - timedelta(
            minutes=settings.critical_result_ack_minutes + 5
        )
        self.assertEqual(result.ack_state, "overdue")

    def test_overdue_threshold_follows_the_hospital_setting(self):
        """Ambangnya benar-benar datang dari hms.settings, bukan dari angka mati."""
        settings = self.env["hms.settings"].get_settings()
        settings.critical_result_ack_minutes = 600
        lenient = self._critical_verified()
        lenient.verified_at = fields.Datetime.now() - timedelta(minutes=45)
        self.assertEqual(lenient.ack_state, "pending")

        settings.critical_result_ack_minutes = 15
        strict = self._critical_verified()
        strict.verified_at = fields.Datetime.now() - timedelta(minutes=45)
        self.assertEqual(strict.ack_state, "overdue")

    def test_cron_moves_a_stale_pending_row_to_overdue(self):
        """Tanpa cron, `pending` tidak pernah berpindah sendiri.

        `verified_at` dimundurkan lewat SQL mentah supaya TIDAK ada dependensi
        ORM yang berubah — persis seperti keadaan nyata ketika tenggat lewat
        sementara tidak ada yang menyentuh barisnya.
        """
        result = self._critical_verified()
        self.assertEqual(result.ack_state, "pending")
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hms_lab_result SET verified_at = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(minutes=120), result.id),
        )
        result.invalidate_recordset()
        self.assertEqual(result.ack_state, "pending")

        moved = self.env["hms.lab.result"]._cron_refresh_ack_state()
        self.assertGreaterEqual(moved, 1)
        result.invalidate_recordset()
        self.assertEqual(result.ack_state, "overdue")

    def test_acknowledging_closes_the_loop(self):
        result = self._critical_verified()
        result.verified_at = fields.Datetime.now() - timedelta(minutes=12)
        result.action_acknowledge(readback="Hb 5,0 g/dL — kritis rendah, ulangi sampling.")
        self.assertEqual(result.ack_state, "acknowledged")
        self.assertEqual(result.acknowledged_by_id, self.env.user)
        self.assertTrue(result.acknowledged_at)
        self.assertIn("kritis rendah", result.ack_readback)
        # 12 menit berlalu antara verifikasi dan pengakuan.
        self.assertEqual(result.ack_minutes, 12)

    def test_second_acknowledgement_does_not_overwrite_the_first(self):
        result = self._critical_verified()
        result.action_acknowledge()
        first_at = result.acknowledged_at
        first_by = result.acknowledged_by_id
        result.verified_at = fields.Datetime.now() - timedelta(minutes=99)
        result.action_acknowledge()
        self.assertEqual(result.acknowledged_at, first_at)
        self.assertEqual(result.acknowledged_by_id, first_by)

    def test_acknowledger_is_always_the_logged_in_user(self):
        """Identitas pengaku tidak dapat dititipkan pemanggil."""
        result = self._critical_verified()
        impostor = self._other_verifier("zt-lab-ack-impostor")
        receiver = self._other_verifier("zt-lab-ack-receiver")
        # Ditanam lebih dulu lewat ORM; aksi harus tetap menimpanya.
        result.acknowledged_by_id = impostor
        result.with_user(receiver).action_acknowledge()
        result.invalidate_recordset()
        self.assertEqual(result.acknowledged_by_id, receiver)
        self.assertNotEqual(result.acknowledged_by_id, impostor)

    def test_acknowledgement_emits_an_event(self):
        result = self._critical_verified()
        before = self.env["hms.event"].search_count([("topic", "=", "result.acknowledged")])
        result.action_acknowledge()
        after = self.env["hms.event"].search_count([("topic", "=", "result.acknowledged")])
        self.assertEqual(after, before + 1)

    def test_notification_keeps_the_first_timestamp(self):
        result = self._critical_verified()
        result.action_notify(channel="phone")
        self.assertTrue(result.notified_at)
        self.assertEqual(result.notified_by_id, self.env.user)
        # Default tujuannya adalah dokter penanggung jawab kunjungan.
        self.assertEqual(result.notified_to_id, self.doctor)
        self.assertEqual(result.notify_channel, "phone")
        first_at = result.notified_at
        result.action_notify(channel="in_person")
        self.assertEqual(result.notified_at, first_at)
        self.assertEqual(result.notify_channel, "in_person")

    def test_non_critical_result_cannot_be_notified(self):
        line = self._ordered_line(self._patient())
        result = line.lab_result_ids
        result.value_numeric = NORMAL_HB
        result.action_enter()
        result.action_validate()
        result.action_verify()
        with self.assertRaises(UserError):
            result.action_notify()

    # ------------------------------------------------------------------
    # Hak tulis kolom-terbatas bagi klinisi.
    #
    # Sebelum ini `group_hms_emr_clinician` hanya punya perm_read, sehingga
    # dokter — justru pihak yang seharusnya mengakui nilai kritis — selalu
    # kena AccessError di `action_acknowledge()`. Fitur yang tidak bisa
    # dipakai peran yang dituju itu rusak, bukan aman.
    #
    # Semua tes di bawah WAJIB memakai .with_user(): pengguna penjalan tes
    # adalah superuser dan melewati ACL, record rule, dan pagar kolom
    # sekaligus, jadi menjalankannya tanpa .with_user() tidak membuktikan
    # apa pun.
    # ------------------------------------------------------------------
    def test_every_whitelisted_column_exists_on_this_model(self):
        """Daftar putih yang menyebut kolom tak-ada adalah pagar yang bocor."""
        missing = CRITICAL_ACK_WRITABLE_FIELDS - set(self.env["hms.lab.result"]._fields)
        self.assertFalse(missing, f"kolom daftar putih tidak ada di model: {missing}")

    def test_clinician_can_acknowledge_a_critical_result_of_their_own_patient(self):
        result = self._critical_verified(practitioner=self.clinician)
        result.with_user(self.clinician_user).action_acknowledge(
            readback="Hb 5,0 g/dL — kritis rendah, ulangi sampling."
        )
        result.invalidate_recordset()
        self.assertEqual(result.ack_state, "acknowledged")
        self.assertEqual(result.acknowledged_by_id, self.clinician_user)
        self.assertIn("kritis rendah", result.ack_readback)

    def test_clinician_can_notify_but_not_touch_the_result_itself(self):
        result = self._critical_verified(practitioner=self.clinician)
        result.with_user(self.clinician_user).action_notify(channel="phone")
        result.invalidate_recordset()
        self.assertEqual(result.notify_channel, "phone")
        self.assertEqual(result.notified_by_id, self.clinician_user)

    def test_clinician_cannot_write_fields_outside_the_whitelist(self):
        """Inilah yang membuat hibah perm_write tetap sempit.

        Tanpa tes ini, `perm_write=1` bagi klinisi berarti dokter bisa
        mengarang ulang angka hasil laboratorium.
        """
        result = self._critical_verified(practitioner=self.clinician)
        as_clinician = result.with_user(self.clinician_user)
        for vals in ({"value_numeric": 99.0}, {"state": "rejected"},
                     {"note": "diubah diam-diam"}, {"verified_at": fields.Datetime.now()}):
            with self.assertRaises(AccessError):
                as_clinician.write(vals)
        result.invalidate_recordset()
        self.assertEqual(result.value_numeric, CRITICAL_HB)
        self.assertEqual(result.state, "verified")
        self.assertFalse(result.note)

    def test_clinician_cannot_mix_a_forbidden_field_into_an_allowed_write(self):
        """Satu kolom terlarang membatalkan seluruh write, bukan disaring diam-diam."""
        result = self._critical_verified(practitioner=self.clinician)
        with self.assertRaises(AccessError):
            result.with_user(self.clinician_user).write({
                "ack_readback": "sah", "value_numeric": 1.0,
            })
        result.invalidate_recordset()
        self.assertFalse(result.ack_readback)
        self.assertEqual(result.value_numeric, CRITICAL_HB)

    def test_clinician_cannot_acknowledge_a_patient_they_do_not_treat(self):
        """Record rule F-EMR-07: hak tulis berhenti di batas pasien yang dirawat."""
        result = self._critical_verified()  # DPJP-nya dokter lain, unit lain
        with self.assertRaises(AccessError):
            result.with_user(self.clinician_user).action_acknowledge()

    def test_clinician_covering_the_unit_may_acknowledge(self):
        """Pola F-EMR-07 berbasis unit, bukan care-team ketat.

        Dokter jaga yang menggantikan sejawat harus bisa menutup lingkaran
        nilai kritis pasien di depannya; aturan yang melarangnya diakali
        dengan berbagi login.
        """
        result = self._critical_verified()  # DPJP = self.doctor
        self.clinic.write({"practitioner_ids": [(4, self.clinician.id)]})
        result.with_user(self.clinician_user).action_acknowledge()
        result.invalidate_recordset()
        self.assertEqual(result.ack_state, "acknowledged")

    def test_lab_staff_still_write_any_field(self):
        result = self._critical_verified()
        analyst = self._other_verifier("zt-lab-acl-analyst")
        result.with_user(analyst).write({"note": "catatan analis", "value_numeric": 4.5})
        result.invalidate_recordset()
        self.assertEqual(result.note, "catatan analis")
        self.assertAlmostEqual(result.value_numeric, 4.5)

    def test_admin_still_writes_any_field_on_any_patient(self):
        """Administrator menyiratkan group_hms_emr_clinician lewat emr_full.

        Tanpa aturan pengimbang, record rule klinisi akan ikut mengunci admin.
        """
        result = self._critical_verified()
        admin = self.env.ref("base.user_admin")
        result.with_user(admin).write({"note": "koreksi administrator"})
        result.invalidate_recordset()
        self.assertEqual(result.note, "koreksi administrator")

    def test_cron_still_refreshes_ack_state_under_its_own_user(self):
        """Pagar kolom tidak boleh mematahkan penyapu `ack_state`.

        Cron berjalan sebagai pengguna miliknya sendiri, bukan sebagai
        penguji. Kalau override write() ikut mengenainya, indikator mutu
        berhenti bergerak tanpa satu pun error yang terlihat.
        """
        cron = self.env.ref("custom_hms_lab.cron_hms_lab_ack_overdue")
        result = self._critical_verified()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hms_lab_result SET verified_at = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(minutes=120), result.id),
        )
        result.invalidate_recordset()
        moved = self.env["hms.lab.result"].with_user(cron.user_id)._cron_refresh_ack_state()
        self.assertGreaterEqual(moved, 1)
        result.invalidate_recordset()
        self.assertEqual(result.ack_state, "overdue")
