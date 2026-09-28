# -*- coding: utf-8 -*-
"""Nama alasan penundaan harus sama pada arah baca dan arah tulis.

GET ``/procedure-schedules/<id>`` mengirim ``postpone_reason`` dan
``postpone_note``; POST ``/procedure-schedules/<id>/postpone`` dulu hanya
membaca ``reason`` dan ``note``. Mengirim kembali nama yang baru saja dibaca
karena itu **berhasil dengan 400** — "alasan penundaan wajib diisi" —
seolah petugas tidak mengisinya. Hal yang sama berlaku untuk ``cancel_reason``
pada aksi ``cancel``, baik di jadwal tindakan maupun di rencana kontrol.

Ini alias, bukan perubahan kontrak: ejaan lama (``reason``/``note``) tetap
harus bekerja, dan tes di bawah menguji **keduanya**. Kalau salah satu ejaan
diam-diam berhenti bekerja, penundaan berhenti tercatat — dan penundaan yang
tidak tercatat adalah indikator mutu yang selalu terlihat sempurna.
"""
import json
from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged
from .common import fixture_password

CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"
NOTE_TEXT = "Hasil laboratorium pra-operasi belum lengkap."


@tagged("post_install", "-at_install", "hms")
class PostponeContractAliasCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.theatre = cls.env["hms.unit"].create({
            "code": "ZT-ALIAS-OK", "name": "Kamar Operasi Alias", "type": "ok",
        })
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-ALIAS-POLI", "name": "Poli Alias", "type": "outpatient_clinic",
        })
        cls.user = cls.env["res.users"].create({
            "name": "dr. Uji Alias", "login": "zt-alias@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [(4, cls.env.ref(CLINICIAN_GROUP).id)],
        })
        cls.doctor = cls.env["hms.practitioner"].create({
            "name": "Uji Alias", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101720077", "user_id": cls.user.id,
        })
        cls.tariff = cls.env["hms.tariff"].create({
            "code": "ZT-ALIAS-TIND", "name": "Apendektomi Alias",
            "category_id": cls.env.ref("custom_hms_base.tariff_cat_procedure").id,
            "unit_id": cls.theatre.id, "duration_minutes": 90,
        })

    # --- plumbing ---------------------------------------------------------
    # ``dbfilter = ^%d$`` pada deployment ini: database dipilih dari label
    # pertama Host. ``HttpCase`` memanggil ``http://127.0.0.1:<port>``, yang
    # memberi domain "127" dan karena itu **404 untuk setiap route** — bukan
    # kegagalan kontrak, hanya permintaan yang tidak pernah menemukan
    # databasenya. Host dikarang dari nama database yang sedang diuji supaya
    # tesnya tidak terikat pada satu nama domain.
    def _host(self):
        return "%s.test.invalid" % self.env.cr.dbname

    def _token(self):
        response = self.url_open(
            "/api/v1/auth/login",
            data=json.dumps({"login": self.user.login, "password": self.password}),
            headers={"Content-Type": "application/json", "Host": self._host()},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        return response.json()["access_token"]

    def _post(self, path, payload):
        response = self.url_open(
            path, data=json.dumps(payload),
            headers={"Content-Type": "application/json", "Host": self._host(),
                     "Authorization": "Bearer %s" % self._token()},
        )
        self.env.invalidate_all()
        return response

    def _schedule(self, suffix):
        patient = self.env["hms.patient"].create({
            "name": "Pasien Alias %s" % suffix, "gender": "female",
            "birth_date": "1988-01-01", "nik": "320101010188%04d" % suffix,
        })
        encounter = self.env["hms.encounter"].create({
            "patient_id": patient.id, "unit_id": self.clinic.id,
            "payer_id": self.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": self.doctor.id,
        })
        order = self.env["hms.order"].create({
            "encounter_id": encounter.id, "order_type": "procedure",
            "practitioner_id": self.doctor.id,
            "target_unit_id": self.theatre.id,
            "line_ids": [(0, 0, {
                "tariff_id": self.tariff.id,
                "scheduled_at": fields.Datetime.now() + timedelta(days=2),
            })],
        })
        order.action_submit()
        schedule = order.line_ids.procedure_schedule_ids
        self.assertTrue(schedule, "Jadwal tindakan tidak terbentuk dari order uji.")
        return schedule

    # --- penundaan --------------------------------------------------------
    def test_postpone_accepts_the_old_spelling(self):
        schedule = self._schedule(1)
        response = self._post(
            "/api/v1/procedure-schedules/%d/postpone" % schedule.id,
            {"reason": "preparation", "note": NOTE_TEXT},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(schedule.state, "postponed")
        self.assertEqual(schedule.postpone_reason, "preparation")
        self.assertEqual(schedule.postpone_note, NOTE_TEXT)

    def test_postpone_accepts_the_spelling_the_read_side_emits(self):
        schedule = self._schedule(2)
        response = self._post(
            "/api/v1/procedure-schedules/%d/postpone" % schedule.id,
            {"postpone_reason": "preparation", "postpone_note": NOTE_TEXT},
        )
        self.assertEqual(
            response.status_code, 200,
            "Mengirim kembali nama yang baru saja dibaca dari GET ditolak: %s"
            % response.text[:400],
        )
        self.assertEqual(schedule.state, "postponed")
        self.assertEqual(schedule.postpone_reason, "preparation")
        self.assertEqual(schedule.postpone_note, NOTE_TEXT)

    def test_postpone_without_any_reason_is_still_refused(self):
        """Alias tidak boleh menjadi pintu belakang untuk penundaan tanpa alasan."""
        schedule = self._schedule(3)
        response = self._post(
            "/api/v1/procedure-schedules/%d/postpone" % schedule.id, {},
        )
        self.assertEqual(response.status_code, 400, response.text[:400])
        self.assertEqual(response.json()["error"]["code"], "business_rule")
        self.assertNotEqual(schedule.state, "postponed")

    # --- pembatalan -------------------------------------------------------
    def test_procedure_cancel_accepts_both_spellings(self):
        first = self._schedule(4)
        response = self._post(
            "/api/v1/procedure-schedules/%d/cancel" % first.id, {"reason": "Pasien menolak."},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(first.cancel_reason, "Pasien menolak.")

        second = self._schedule(5)
        response = self._post(
            "/api/v1/procedure-schedules/%d/cancel" % second.id,
            {"cancel_reason": "Ruang operasi dipakai kasus emergensi."},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(second.cancel_reason, "Ruang operasi dipakai kasus emergensi.")

    def test_followup_cancel_accepts_both_spellings(self):
        plans = []
        for index in (6, 7):
            patient = self.env["hms.patient"].create({
                "name": "Pasien Kontrol %s" % index, "gender": "male",
                "birth_date": "1980-01-01", "nik": "320101010188%04d" % index,
            })
            encounter = self.env["hms.encounter"].create({
                "patient_id": patient.id, "unit_id": self.clinic.id,
                "payer_id": self.env.ref("custom_hms_base.payer_self").id,
                "practitioner_id": self.doctor.id,
            })
            plans.append(self.env["hms.followup.plan"].create({
                "encounter_id": encounter.id, "practitioner_id": self.doctor.id,
                "unit_id": self.clinic.id,
                "planned_date": fields.Date.context_today(self.env.user),
                "kind": "control", "instruction": "Kontrol membawa hasil.",
            }))

        response = self._post(
            "/api/v1/followup-plans/%d/cancel" % plans[0].id, {"reason": "Pasien pindah kota."},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(plans[0].cancel_reason, "Pasien pindah kota.")

        response = self._post(
            "/api/v1/followup-plans/%d/cancel" % plans[1].id,
            {"cancel_reason": "Rencana digabung ke kontrol lain."},
        )
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(plans[1].cancel_reason, "Rencana digabung ke kontrol lain.")
