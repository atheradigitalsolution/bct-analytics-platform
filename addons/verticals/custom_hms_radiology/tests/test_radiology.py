# -*- coding: utf-8 -*-
"""Radiology worklist and the verification gate."""
from datetime import timedelta

from odoo import fields
from odoo.addons.custom_hms_base.models.hms_critical_ack import (
    CRITICAL_ACK_WRITABLE_FIELDS,
)
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

# Helper di level MODUL, bukan di badan kelas: definisi non-`def` di tengah
# badan kelas tes pernah membuat seluruh `test_*` setelahnya berhenti
# dikoleksi tanpa satu pun kegagalan muncul.
VERIFIER_GROUP = "custom_hms_base.group_hms_diagnostic_verifier"
CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"
CRITICAL_FINDINGS = "Tampak gambaran lusen di hemithorax kanan."
CRITICAL_IMPRESSION = "Pneumotoraks kanan luas."


@tagged("post_install", "-at_install", "hms")
class TestRadiology(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rad_unit = cls.env["hms.unit"].create({
            "code": "ZT-RAD-T", "name": "Radiologi", "type": "radiology",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-POLI-RAD", "name": "Poli Uji Radiologi", "type": "outpatient_clinic",
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Maya Sari", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501810001", "user_id": cls.env.user.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-RAD-THX", "name": "Rontgen Thorax PA",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_rad").id,
            "unit_id": cls.rad_unit.id,
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Toni Kurniawan", "nik": "3201010101910005",
            "birth_date": "1991-05-05", "gender": "male",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.doctor.id,
        })

        # Klinisi sungguhan, terpisah dari pengguna penjalan tes: tes yang
        # berjalan sebagai superuser melewati SEMUA hak akses, jadi hak
        # kolom-terbatas hanya bisa dibuktikan lewat .with_user().
        cls.clinician_user = cls.env["res.users"].create({
            "name": "dr. Rangga Putra", "login": "zt-rad-clinician",
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.clinician = cls.env["hms.practitioner"].create({
            "name": "Rangga Putra", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201014501810002", "user_id": cls.clinician_user.id,
        })
        cls.own_patient = cls.env["hms.patient"].create({
            "name": "Sri Lestari", "nik": "3201010101910006",
            "birth_date": "1988-03-03", "gender": "female",
        })
        cls.own_encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.own_patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.clinician.id,
        })

    def _ordered(self, encounter=None):
        encounter = encounter or self.encounter
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "radiology",
            "practitioner_id": self.doctor.id, "target_unit_id": self.rad_unit.id,
            "clinical_note": "Batuk lama, curiga TB",
            "line_ids": [(0, 0, {"tariff_id": self.tariff.id})],
        })
        order.action_submit()
        return order.line_ids.rad_report_ids

    def _critical_verified(self, encounter=None):
        """Ekspertise dengan temuan kritis yang sudah diverifikasi radiolog."""
        report = self._ordered(encounter=encounter)
        report.action_perform()
        report.write({
            "findings": CRITICAL_FINDINGS,
            "impression": CRITICAL_IMPRESSION,
            "is_critical": True,
        })
        report.action_report()
        report.action_verify()
        return report

    def _other_verifier(self, login):
        return self.env["res.users"].create({
            "name": "dr. Penerima Laporan Radiologi", "login": login,
            "group_ids": [(4, self.env.ref(VERIFIER_GROUP).id)],
        })

    def test_ordering_creates_the_worklist_entry(self):
        report = self._ordered()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.state, "scheduled")
        self.assertIn("TB", report.clinical_info)

    def test_report_requires_findings_and_impression(self):
        report = self._ordered()
        report.action_perform()
        with self.assertRaises(UserError):
            report.action_report()

    def test_full_flow_closes_the_order_line(self):
        report = self._ordered()
        report.action_perform()
        report.write({"findings": "Tidak tampak infiltrat.", "impression": "Thorax normal."})
        report.action_report()
        report.action_verify()
        self.assertEqual(report.state, "verified")
        self.assertEqual(report.order_line_id.state, "done")

    def test_cannot_verify_before_reporting(self):
        report = self._ordered()
        report.action_perform()
        with self.assertRaises(UserError):
            report.action_verify()

    def test_verified_report_cannot_be_cancelled(self):
        report = self._ordered()
        report.action_perform()
        report.write({"findings": "x", "impression": "y"})
        report.action_report()
        report.action_verify()
        with self.assertRaises(UserError):
            report.action_cancel()

    def test_critical_finding_emits_an_event(self):
        report = self._ordered()
        report.action_perform()
        report.write({
            "findings": "Tampak gambaran lusen di hemithorax kanan.",
            "impression": "Pneumotoraks kanan luas.",
            "is_critical": True,
        })
        report.action_report()
        before = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        report.action_verify()
        after = self.env["hms.event"].search_count([("topic", "=", "result.critical")])
        self.assertEqual(after, before + 1)

    # ------------------------------------------------------------------
    # Closed-loop temuan kritis
    # ------------------------------------------------------------------
    def test_non_critical_report_needs_no_acknowledgement(self):
        report = self._ordered()
        report.action_perform()
        report.write({"findings": "Tidak tampak infiltrat.", "impression": "Thorax normal."})
        report.action_report()
        report.action_verify()
        self.assertFalse(report.is_critical)
        self.assertEqual(report.ack_state, "not_required")
        with self.assertRaises(UserError):
            report.action_acknowledge()

    def test_unverified_critical_report_cannot_be_acknowledged(self):
        report = self._ordered()
        report.action_perform()
        report.write({
            "findings": CRITICAL_FINDINGS, "impression": CRITICAL_IMPRESSION,
            "is_critical": True,
        })
        report.action_report()
        self.assertEqual(report.ack_state, "not_required")
        with self.assertRaises(UserError):
            report.action_acknowledge()

    def test_freshly_verified_critical_report_is_pending(self):
        report = self._critical_verified()
        self.assertEqual(report.ack_state, "pending")
        self.assertEqual(report.ack_minutes, 0)

    def test_critical_report_past_the_deadline_is_overdue(self):
        settings = self.env["hms.settings"].get_settings()
        report = self._critical_verified()
        report.verified_at = fields.Datetime.now() - timedelta(
            minutes=settings.critical_result_ack_minutes + 5
        )
        self.assertEqual(report.ack_state, "overdue")

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
        """`verified_at` dimundurkan lewat SQL mentah: tidak ada dependensi ORM
        yang berubah, persis seperti tenggat yang lewat tanpa disentuh siapa pun."""
        report = self._critical_verified()
        self.assertEqual(report.ack_state, "pending")
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hms_rad_report SET verified_at = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(minutes=120), report.id),
        )
        report.invalidate_recordset()
        self.assertEqual(report.ack_state, "pending")

        moved = self.env["hms.rad.report"]._cron_refresh_ack_state()
        self.assertGreaterEqual(moved, 1)
        report.invalidate_recordset()
        self.assertEqual(report.ack_state, "overdue")

    def test_acknowledging_closes_the_loop(self):
        report = self._critical_verified()
        report.verified_at = fields.Datetime.now() - timedelta(minutes=8)
        report.action_acknowledge(readback="Pneumotoraks kanan luas — pasien disiapkan WSD.")
        self.assertEqual(report.ack_state, "acknowledged")
        self.assertEqual(report.acknowledged_by_id, self.env.user)
        self.assertIn("WSD", report.ack_readback)
        self.assertEqual(report.ack_minutes, 8)

    def test_second_acknowledgement_does_not_overwrite_the_first(self):
        report = self._critical_verified()
        report.action_acknowledge()
        first_at = report.acknowledged_at
        first_by = report.acknowledged_by_id
        report.verified_at = fields.Datetime.now() - timedelta(minutes=99)
        report.action_acknowledge()
        self.assertEqual(report.acknowledged_at, first_at)
        self.assertEqual(report.acknowledged_by_id, first_by)

    def test_acknowledger_is_always_the_logged_in_user(self):
        report = self._critical_verified()
        impostor = self._other_verifier("zt-rad-ack-impostor")
        receiver = self._other_verifier("zt-rad-ack-receiver")
        report.acknowledged_by_id = impostor
        report.with_user(receiver).action_acknowledge()
        report.invalidate_recordset()
        self.assertEqual(report.acknowledged_by_id, receiver)
        self.assertNotEqual(report.acknowledged_by_id, impostor)

    def test_acknowledgement_emits_an_event(self):
        report = self._critical_verified()
        before = self.env["hms.event"].search_count([("topic", "=", "result.acknowledged")])
        report.action_acknowledge()
        after = self.env["hms.event"].search_count([("topic", "=", "result.acknowledged")])
        self.assertEqual(after, before + 1)

    def test_notification_keeps_the_first_timestamp(self):
        report = self._critical_verified()
        report.action_notify(channel="phone")
        self.assertTrue(report.notified_at)
        self.assertEqual(report.notified_by_id, self.env.user)
        self.assertEqual(report.notified_to_id, self.doctor)
        first_at = report.notified_at
        report.action_notify(channel="in_person")
        self.assertEqual(report.notified_at, first_at)
        self.assertEqual(report.notify_channel, "in_person")

    def test_non_critical_report_cannot_be_notified(self):
        report = self._ordered()
        report.action_perform()
        report.write({"findings": "Tidak tampak infiltrat.", "impression": "Thorax normal."})
        report.action_report()
        report.action_verify()
        with self.assertRaises(UserError):
            report.action_notify()

    # ------------------------------------------------------------------
    # Hak tulis kolom-terbatas bagi klinisi.
    #
    # Pola dan alasannya sama persis dengan custom_hms_lab: sebelum ini
    # `group_hms_emr_clinician` hanya punya perm_read, sehingga dokter
    # pengirim — pihak yang seharusnya mengakui temuan kritis — selalu kena
    # AccessError di `action_acknowledge()`.
    #
    # Semua tes di bawah WAJIB memakai .with_user(): pengguna penjalan tes
    # adalah superuser dan melewati ACL, record rule, dan pagar kolom
    # sekaligus.
    # ------------------------------------------------------------------
    def test_every_whitelisted_column_exists_on_this_model(self):
        """Daftar putih yang menyebut kolom tak-ada adalah pagar yang bocor."""
        missing = CRITICAL_ACK_WRITABLE_FIELDS - set(self.env["hms.rad.report"]._fields)
        self.assertFalse(missing, f"kolom daftar putih tidak ada di model: {missing}")

    def test_clinician_can_acknowledge_a_critical_finding_of_their_own_patient(self):
        report = self._critical_verified(encounter=self.own_encounter)
        report.with_user(self.clinician_user).action_acknowledge(
            readback="Pneumotoraks kanan luas — siapkan WSD."
        )
        report.invalidate_recordset()
        self.assertEqual(report.ack_state, "acknowledged")
        self.assertEqual(report.acknowledged_by_id, self.clinician_user)
        self.assertIn("WSD", report.ack_readback)

    def test_clinician_can_notify_but_not_touch_the_report_itself(self):
        report = self._critical_verified(encounter=self.own_encounter)
        report.with_user(self.clinician_user).action_notify(channel="phone")
        report.invalidate_recordset()
        self.assertEqual(report.notify_channel, "phone")
        self.assertEqual(report.notified_by_id, self.clinician_user)

    def test_clinician_cannot_write_fields_outside_the_whitelist(self):
        """Inilah yang membuat hibah perm_write tetap sempit.

        Tanpa tes ini, `perm_write=1` bagi klinisi berarti dokter pengirim
        bisa menulis ulang kesan radiolog.
        """
        report = self._critical_verified(encounter=self.own_encounter)
        as_clinician = report.with_user(self.clinician_user)
        for vals in ({"impression": "Normal."}, {"state": "reported"},
                     {"findings": "Tidak ada kelainan."}, {"is_critical": False}):
            with self.assertRaises(AccessError):
                as_clinician.write(vals)
        report.invalidate_recordset()
        self.assertEqual(report.impression, CRITICAL_IMPRESSION)
        self.assertEqual(report.state, "verified")
        self.assertTrue(report.is_critical)

    def test_clinician_cannot_mix_a_forbidden_field_into_an_allowed_write(self):
        """Satu kolom terlarang membatalkan seluruh write, bukan disaring diam-diam."""
        report = self._critical_verified(encounter=self.own_encounter)
        with self.assertRaises(AccessError):
            report.with_user(self.clinician_user).write({
                "ack_readback": "sah", "impression": "Normal.",
            })
        report.invalidate_recordset()
        self.assertFalse(report.ack_readback)
        self.assertEqual(report.impression, CRITICAL_IMPRESSION)

    def test_clinician_cannot_acknowledge_a_patient_they_do_not_treat(self):
        """Record rule F-EMR-07: hak tulis berhenti di batas pasien yang dirawat."""
        report = self._critical_verified()  # DPJP-nya dokter lain
        with self.assertRaises(AccessError):
            report.with_user(self.clinician_user).action_acknowledge()

    def test_clinician_covering_the_unit_may_acknowledge(self):
        report = self._critical_verified()  # DPJP = self.doctor
        self.clinic.write({"practitioner_ids": [(4, self.clinician.id)]})
        report.with_user(self.clinician_user).action_acknowledge()
        report.invalidate_recordset()
        self.assertEqual(report.ack_state, "acknowledged")

    def test_radiology_staff_still_write_any_field(self):
        report = self._critical_verified()
        staff = self._other_verifier("zt-rad-acl-staff")
        report.with_user(staff).write({"body_part": "Thorax", "suggestion": "Kontrol 1x24 jam"})
        report.invalidate_recordset()
        self.assertEqual(report.body_part, "Thorax")
        self.assertEqual(report.suggestion, "Kontrol 1x24 jam")

    def test_admin_still_writes_any_field_on_any_patient(self):
        """Administrator menyiratkan group_hms_emr_clinician lewat emr_full."""
        report = self._critical_verified()
        admin = self.env.ref("base.user_admin")
        report.with_user(admin).write({"body_part": "Thorax PA"})
        report.invalidate_recordset()
        self.assertEqual(report.body_part, "Thorax PA")

    def test_cron_still_refreshes_ack_state_under_its_own_user(self):
        """Pagar kolom tidak boleh mematahkan penyapu `ack_state`."""
        cron = self.env.ref("custom_hms_radiology.cron_hms_rad_ack_overdue")
        report = self._critical_verified()
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE hms_rad_report SET verified_at = %s WHERE id = %s",
            (fields.Datetime.now() - timedelta(minutes=120), report.id),
        )
        report.invalidate_recordset()
        moved = self.env["hms.rad.report"].with_user(cron.user_id)._cron_refresh_ack_state()
        self.assertGreaterEqual(moved, 1)
        report.invalidate_recordset()
        self.assertEqual(report.ack_state, "overdue")
