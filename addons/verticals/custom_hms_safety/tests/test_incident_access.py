# -*- coding: utf-8 -*-
"""Siapa boleh melapor, siapa boleh membaca — dibuktikan dari akun peran nyata.

Menguji ini sebagai administrator tidak membuktikan apa pun: ``TransactionCase``
menjalankan ``self.env`` sebagai superuser, dan superuser melewati seluruh
``ir.model.access`` maupun ``ir.rule``. Semua pemeriksaan di berkas ini karena
itu memakai ``.with_user(...)``.

Yang dijaga adalah asimetri yang membuat budaya pelaporan mungkin:
**melapor semurah mungkin, membaca semahal mungkin.**
"""
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "hms")
class TestIncidentAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["hms.unit"].create({
            "code": "ZT-KP-ACL", "name": "Bangsal Uji ACL", "type": "inpatient",
        })
        cls.nurse_user = cls._role_user(
            cls, "zt-kp-perawat", "Perawat KP", ["custom_hms_base.group_hms_nurse"]
        )
        cls.doctor_user = cls._role_user(
            cls, "zt-kp-dokter", "Dokter KP", ["custom_hms_base.group_hms_emr_clinician"]
        )
        cls.pharmacist_user = cls._role_user(
            cls, "zt-kp-apoteker", "Apoteker KP", ["custom_hms_base.group_hms_pharmacist"]
        )
        cls.safety_user = cls._role_user(
            cls, "zt-kp-tim", "Anggota Tim KP",
            ["custom_hms_safety.group_hms_patient_safety"],
        )
        cls.Incident = cls.env["hms.incident.report"]

    def _role_user(self, login, name, group_xmlids):
        return self.env["res.users"].create({
            "name": name,
            "login": login,
            "group_ids": [(4, self.env.ref(x).id) for x in group_xmlids],
        })

    def _incident_by(self, user, **vals):
        base = {
            "unit_id": self.unit.id,
            "incident_type": "knc",
            "chronology": "Kronologi dari peran nyata.",
        }
        base.update(vals)
        return self.Incident.with_user(user).create(base)

    # --- melapor ----------------------------------------------------------
    def test_nurse_can_report_an_incident(self):
        incident = self._incident_by(self.nurse_user)
        self.assertEqual(incident.create_uid, self.nurse_user)
        incident.action_report()
        self.assertEqual(incident.state, "reported")

    def test_doctor_can_report_an_incident(self):
        incident = self._incident_by(self.doctor_user)
        incident.action_report()
        self.assertEqual(incident.state, "reported")

    def test_pharmacist_can_report_an_incident(self):
        incident = self._incident_by(self.pharmacist_user)
        incident.action_report()
        self.assertEqual(incident.state, "reported")

    # --- membaca ----------------------------------------------------------
    def test_clinician_cannot_read_someone_elses_incident(self):
        """Inti PMK 11/2017: laporan tidak terbaca seluruh staf klinis."""
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        with self.assertRaises(AccessError):
            self.Incident.with_user(self.doctor_user).browse(incident.id).chronology

    def test_pharmacist_cannot_read_someone_elses_incident(self):
        incident = self._incident_by(self.nurse_user)
        with self.assertRaises(AccessError):
            self.Incident.with_user(self.pharmacist_user).browse(incident.id).chronology

    def test_search_does_not_leak_other_peoples_incidents(self):
        """`search` menyaring diam-diam; kalau rule salah, kebocorannya tanpa error."""
        mine = self._incident_by(self.doctor_user)
        theirs = self._incident_by(self.nurse_user)
        visible = self.Incident.with_user(self.doctor_user).search([])
        self.assertIn(mine, visible)
        self.assertNotIn(theirs, visible)

    def test_reporter_can_read_their_own_report_after_submitting(self):
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        as_nurse = self.Incident.with_user(self.nurse_user).browse(incident.id)
        self.assertTrue(as_nurse.chronology)

    def test_named_reporter_can_read_a_report_filed_for_them(self):
        practitioner = self.env["hms.practitioner"].create({
            "name": "Perawat Tercatat", "type": "nurse",
            "nik": "3201014501900021", "user_id": self.nurse_user.id,
        })
        incident = self._incident_by(self.doctor_user, reporter_id=practitioner.id)
        as_nurse = self.Incident.with_user(self.nurse_user).browse(incident.id)
        self.assertTrue(as_nurse.chronology)

    def test_safety_team_reads_every_incident(self):
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        as_kp = self.Incident.with_user(self.safety_user).browse(incident.id)
        self.assertTrue(as_kp.chronology)
        self.assertIn(incident, self.Incident.with_user(self.safety_user).search([]))

    # --- menulis ----------------------------------------------------------
    def test_reporter_cannot_edit_after_submitting(self):
        """Laporan terkirim adalah bukti, bukan draf yang bisa ditulis ulang."""
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        with self.assertRaises(AccessError):
            self.Incident.with_user(self.nurse_user).browse(incident.id).write(
                {"chronology": "Versi yang sudah dirapikan."}
            )

    def test_reporter_may_still_fix_a_draft(self):
        incident = self._incident_by(self.nurse_user)
        self.Incident.with_user(self.nurse_user).browse(incident.id).write(
            {"chronology": "Kronologi diperbaiki sebelum dikirim."}
        )
        self.assertIn("diperbaiki", incident.chronology)

    def test_clinician_cannot_investigate_another_persons_incident(self):
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        with self.assertRaises(AccessError):
            self.Incident.with_user(
                self.doctor_user
            ).browse(incident.id).action_start_investigation()

    def test_safety_team_can_run_the_investigation(self):
        incident = self._incident_by(self.nurse_user)
        incident.action_report()
        as_kp = self.Incident.with_user(self.safety_user).browse(incident.id)
        as_kp.action_start_investigation()
        as_kp.write({
            "grade": "blue",
            "root_cause": "Akar masalah uji.",
            "recommendation": "Rekomendasi uji.",
        })
        as_kp.action_grade()
        as_kp.action_close()
        self.assertEqual(incident.state, "closed")

    def test_nobody_may_delete_an_incident_report(self):
        """Laporan yang bisa dihapus bukan laporan."""
        incident = self._incident_by(self.nurse_user)
        for user in (self.nurse_user, self.doctor_user, self.safety_user):
            with self.assertRaises(AccessError):
                self.Incident.with_user(user).browse(incident.id).unlink()

    def test_administrator_is_not_a_safety_team_member_by_inheritance(self):
        """"Grup tim KP saja" berarti juga bukan administrator SIMRS.

        Bila suatu saat group_hms_admin menyiratkan grup ini, seluruh
        kerahasiaan IKP hilang tanpa satu baris pun berubah di modul ini.
        """
        admin_user = self._role_user(
            "zt-kp-admin", "Admin SIMRS KP", ["custom_hms_base.group_hms_admin"]
        )
        self.assertFalse(
            admin_user.has_group("custom_hms_safety.group_hms_patient_safety")
        )
        other = self._incident_by(self.nurse_user)
        with self.assertRaises(AccessError):
            self.Incident.with_user(admin_user).browse(other.id).chronology
