# -*- coding: utf-8 -*-
"""Permintaan yang DITOLAK tidak boleh meninggalkan barisnya di basis data.

CACAT YANG DIUJI DI SINI
------------------------
``hms_route`` menangkap setiap exception bisnis dan **mengembalikan** sebuah
``Response``. Bagi dispatcher Odoo, handler yang kembali normal adalah handler
yang sukses: ``service.model.retrying`` menjalankan ``cr.commit()`` sesudahnya.
Akibatnya baris yang sudah ter-INSERT sebelum exception naik ikut tersimpan,
sementara klien diberi tahu operasinya ditolak.

Reproduksi aslinya::

    POST /api/v1/nursing/requests
        {"station_id": N, "to_unit": "pharmacy", "detail": "...",
         "diet_type_id": M}
    -> 422 "Jenis diet hanya berlaku untuk permintaan ke unit gizi."
    -> tetapi baris hms_unit_request TERSIMPAN: pharmacy | open | diet_type_id=M

Basis data menyimpan baris yang melanggar constraint yang namanya disebut di
pesan galatnya sendiri. Cacatnya ada di dekorator, jadi ia mengenai **semua**
endpoint, bukan hanya yang ini.

KENAPA LEWAT HTTP SUNGGUHAN, BUKAN MEMANGGIL MODEL
---------------------------------------------------
Memanggil ``hms.unit.request.create()`` langsung dari tes akan selalu terlihat
benar: ``assertRaises`` membungkusnya dengan savepoint yang di-rollback. Yang
rusak bukan modelnya melainkan **batas HTTP** — siapa yang memutuskan commit.
Hanya ``HttpCase`` yang melewati ``_serve_db`` → ``retrying`` → ``cr.commit()``
yang sebenarnya, dan karena itu hanya ``HttpCase`` yang bisa merah.

KONTROL POSITIF
---------------
``test_successful_request_is_still_committed`` ada supaya perbaikan yang
me-rollback *semua* permintaan tidak ikut lulus. Tanpa kontrol itu, "API yang
tidak pernah menyimpan apa pun" adalah cara termudah membuat berkas ini hijau.
"""
import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged
from .common import fixture_password

NURSE_GROUP = "custom_hms_base.group_hms_nurse"
REGISTRATION_GROUP = "custom_hms_base.group_hms_registration_user"
CLINICIAN_GROUP = "custom_hms_base.group_hms_emr_clinician"

MARKER = "ZT-ROLLBACK-PROBE"


@tagged("post_install", "-at_install", "hms")
class RejectedRequestRollbackCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.user = cls.env["res.users"].create({
            "name": "Perawat Uji Rollback",
            "login": "zt-rollback@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [
                (4, cls.env.ref(NURSE_GROUP).id),
                (4, cls.env.ref(REGISTRATION_GROUP).id),
                (4, cls.env.ref(CLINICIAN_GROUP).id),
            ],
        })
        cls.station = cls.env["hms.nursing.station"].create({
            "code": "ZT-RB-NS", "name": "Station Uji Rollback", "type": "inpatient",
        })
        cls.diet = cls.env["hms.diet.type"].create({
            "code": "ZT-RB-DIET", "name": "Diet Uji Rollback",
            "category": "regular", "texture": "regular",
        })
        # Kunjungan dipakai jalur observasi: ``hms.observation`` mewarisi
        # ``hms.audited`` (create -> hms.access.log) DAN menerbitkan event,
        # jadi satu permintaan menyentuh ketiga hal yang rollback harus
        # tangani sekaligus: baris bisnis, baris audit, baris outbox.
        cls.clinic = cls.env["hms.unit"].create({
            "code": "ZT-RB-POLI", "name": "Poli Uji Rollback",
            "type": "outpatient_clinic",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien Uji Rollback", "gender": "male",
            "birth_date": "1985-03-04", "nik": "3201010101850077",
        })
        cls.encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.clinic.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
        })
        # Admisi dipakai satu-satunya tes penolakan yang datang dari handler
        # sendiri, bukan dari exception: `inpatient.discharge` menulis
        # `discharge_disposition` LALU menjawab 409 kalau masih ada penghalang.
        cls.ward_unit = cls.env["hms.unit"].create({
            "code": "ZT-RB-RANAP", "name": "Rawat Inap Uji Rollback",
            "type": "inpatient",
        })
        cls.ward = cls.env["hms.ward"].create({
            "code": "ZT-RB-W", "name": "Bangsal Uji", "unit_id": cls.ward_unit.id,
        })
        cls.room = cls.env["hms.room"].create({
            "code": "ZT-RB-R1", "name": "R1", "ward_id": cls.ward.id,
            "class_id": cls.env.ref("custom_hms_base.care_class_2").id, "capacity": 1,
        })
        cls.bed = cls.env["hms.bed"].create({
            "code": "ZT-RB-B1", "name": "A", "room_id": cls.room.id,
        })
        cls.dpjp = cls.env["hms.practitioner"].create({
            "name": "Uji Rollback DPJP", "title_prefix": "dr.", "type": "doctor",
            "nik": "3201010101790088",
        })
        cls.inpatient_encounter = cls.env["hms.encounter"].create({
            "patient_id": cls.patient.id, "unit_id": cls.ward_unit.id,
            "payer_id": cls.env.ref("custom_hms_base.payer_self").id,
            "practitioner_id": cls.dpjp.id,
        })
        cls.admission = cls.env["hms.admission"].admit(
            cls.inpatient_encounter, cls.bed, cls.dpjp,
            entitled_class=cls.env.ref("custom_hms_base.care_class_2"),
        )

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

    def _post(self, path, payload, token=None, idempotency_key=None):
        headers = {
            "Content-Type": "application/json",
            "Host": self._host(),
            "Authorization": "Bearer %s" % (token or self._token()),
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        response = self.url_open(path, data=json.dumps(payload), headers=headers)
        # Permintaan berjalan pada TestCursor tersendiri; cache environment tes
        # harus dibuang sebelum menghitung baris, kalau tidak yang terbaca
        # adalah keadaan sebelum permintaan.
        self.env.invalidate_all()
        return response

    def _requests_left(self):
        return self.env["hms.unit.request"].search_count([("detail", "=", MARKER)])

    def _nutrition_payload(self):
        return {"station_id": self.station.id, "to_unit": "nutrition",
                "detail": MARKER, "diet_type_id": self.diet.id}

    def _rejected_payload(self):
        """Persis reproduksi aslinya: diet dikirim ke unit yang bukan gizi."""
        return {"station_id": self.station.id, "to_unit": "pharmacy",
                "detail": MARKER, "diet_type_id": self.diet.id}

    def _exploding_emit(self, exception):
        """Ganti ``hms.event.emit`` dengan versi yang meledak SESUDAH menulis.

        ``hms.unit.request.create`` memanggil ``emit`` setelah INSERT-nya
        berhasil, jadi ini memberi bentuk kegagalan yang persis sama dengan
        cacat aslinya — baris sudah ada di basis data ketika exception naik —
        tanpa menambah route palsu ke kode produksi.
        """
        Event = type(self.env["hms.event"])
        original = Event.emit

        def exploding(model, topic, payload):
            original(model, topic, payload)
            raise exception

        return patch.object(Event, "emit", exploding)

    # --- kontrol positif: jalur sukses HARUS tetap ter-commit -------------
    def test_successful_request_is_still_committed(self):
        response = self._post("/api/v1/nursing/requests", self._nutrition_payload())
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(
            self._requests_left(), 1,
            "Permintaan yang DITERIMA harus tersimpan. Perbaikan yang me-rollback "
            "semua permintaan membuat API berhenti menyimpan apa pun.",
        )

    # --- ValidationError --------------------------------------------------
    def test_validation_error_leaves_no_row(self):
        response = self._post("/api/v1/nursing/requests", self._rejected_payload())
        self.assertEqual(response.status_code, 422, response.text[:400])
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertEqual(
            self._requests_left(), 0,
            "422 dikirim ke klien tetapi barisnya tersimpan: basis data menyimpan "
            "permintaan yang melanggar constraint yang disebut pesan galatnya.",
        )

    # --- UserError --------------------------------------------------------
    def test_user_error_leaves_no_row(self):
        with self._exploding_emit(UserError("Uji: aturan bisnis menolak setelah tulis.")):
            response = self._post("/api/v1/nursing/requests", self._nutrition_payload())
        self.assertEqual(response.status_code, 400, response.text[:400])
        self.assertEqual(response.json()["error"]["code"], "business_rule")
        self.assertEqual(self._requests_left(), 0)

    # --- exception tak terduga -------------------------------------------
    def test_unexpected_exception_leaves_no_row(self):
        with self._exploding_emit(RuntimeError("Uji: kegagalan tak terduga setelah tulis.")):
            response = self._post("/api/v1/nursing/requests", self._nutrition_payload())
        self.assertEqual(response.status_code, 500, response.text[:400])
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertEqual(self._requests_left(), 0)

    # --- outbox realtime --------------------------------------------------
    def _observation_payload(self):
        return {"pulse": 88, "respiratory_rate": 18, "note": MARKER}

    def _observations_left(self):
        return self.env["hms.observation"].sudo().search_count([("note", "=", MARKER)])

    def test_rejected_request_publishes_no_event(self):
        """Outbox tidak boleh mengumumkan sesuatu yang tidak pernah terjadi.

        ``hms.observation.create`` menulis barisnya, lalu ``hms.event.emit``
        menulis baris outbox dan mendaftarkan callback ``cr.postcommit``.
        Kegagalan sesudah itu harus membuang keduanya — itu kontrak outbox
        (DECISIONS §3), dan tanpa rollback kontrak itu bohong: barisnya
        tersimpan dan cron penyapu akan menerbitkannya belakangan, mengumumkan
        observasi yang tidak pernah tercatat.
        """
        Event = self.env["hms.event"].sudo()
        before = Event.search_count([("topic", "=", "observation.recorded")])
        with self._exploding_emit(UserError("Uji: gagal sesudah event ditulis.")):
            response = self._post(
                "/api/v1/encounters/%d/observations" % self.encounter.id,
                self._observation_payload(),
            )
        self.assertEqual(response.status_code, 400, response.text[:400])
        self.assertEqual(
            Event.search_count([("topic", "=", "observation.recorded")]), before,
            "Permintaan yang ditolak meninggalkan event di outbox.",
        )
        self.assertEqual(self._observations_left(), 0)

    # --- jejak audit ------------------------------------------------------
    def test_rejected_request_leaves_no_audit_row_for_a_write_that_never_happened(self):
        """Pertukaran yang diterima secara sadar, dengan angkanya.

        ``hms.access.log`` ditulis pada cursor yang sama
        (``custom_hms_audit/models/hms_audited_mixin.py``), jadi rollback ikut
        membuangnya. Diukur di tumpukan bayangan, **enam** permintaan gagal
        lewat API menghasilkan **nol** baris ``hms.access.log``: mixin hanya
        menimpa ``read()``, sementara akses field ORM lewat ``fetch()``, dan
        tabelnya memang tidak memuat satu pun baris ``action='read'`` (22 baris,
        seluruhnya write/create/disclose/print).

        Yang tersisa adalah kasus di bawah: mutasi pada model beraudit yang
        kemudian gagal. Barisnya dibuang bersama mutasinya, dan itu yang benar —
        jejak audit yang mencatat perubahan yang tidak pernah terjadi lebih
        menyesatkan daripada tidak ada jejak sama sekali.
        """
        Log = self.env["hms.access.log"].sudo()
        before = Log.search_count([])
        with self._exploding_emit(UserError("Uji: gagal sesudah tulis beraudit.")):
            response = self._post(
                "/api/v1/encounters/%d/observations" % self.encounter.id,
                self._observation_payload(),
            )
        self.assertEqual(response.status_code, 400, response.text[:400])
        self.assertEqual(self._observations_left(), 0)
        self.assertEqual(
            Log.search_count([]), before,
            "Jejak audit mencatat perubahan yang barisnya sudah di-rollback.",
        )

    # --- penolakan yang datang dari handler, bukan dari exception ---------
    def test_handler_rejection_after_a_write_leaves_nothing_behind(self):
        """409 "belum dapat dipulangkan" tidak boleh menyimpan separuhnya.

        ``inpatient.discharge`` menulis ``discharge_disposition`` sebelum
        memeriksa penghalang pemulangan. Tanpa rollback, jawaban "pasien belum
        dapat dipulangkan" tetap meninggalkan cara-keluar yang tersimpan di
        admisi — dan cara keluar adalah kolom yang dilaporkan ke RL 4a.
        Penolakan yang tidak melempar exception harus diperlakukan sama dengan
        yang melempar.
        """
        self.assertFalse(self.admission.discharge_disposition)
        response = self._post(
            "/api/v1/inpatient/%d/discharge" % self.admission.id,
            {"disposition": "home"},
        )
        self.assertEqual(response.status_code, 409, response.text[:400])
        self.assertEqual(response.json()["error"]["code"], "discharge_blocked")
        self.assertFalse(
            self.admission.discharge_disposition,
            "Permintaan ditolak 409 tetapi cara keluar pasien tersimpan.",
        )

    # --- amplop galat -----------------------------------------------------
    def test_a_database_level_failure_still_answers_with_the_json_envelope(self):
        """Galat tingkat Postgres pun harus keluar sebagai ``{"error": ...}``.

        Pelanggaran NOT NULL membuat transaksi Postgres masuk status aborted.
        Sebelum rollback dipasang, ``hms_route`` memang membentuk Response 500
        beramplop JSON — tetapi ``service.model.retrying`` sesudahnya memanggil
        ``cr.flush()`` pada transaksi yang sudah aborted, exception KEDUA naik
        dan menimpa jawabannya dengan halaman HTML 500 werkzeug. Layar Next.js
        mem-parse setiap respons sebagai JSON, jadi yang sampai ke pengguna
        bukan pesan galat melainkan ``Unexpected token '<'``.

        ``cr.rollback()` di jalur penolakan membersihkan status aborted itu,
        sehingga flush/commit sesudahnya berhasil dan amplopnya selamat.
        """
        response = self._post(
            "/api/v1/patients",
            {"name": "Pasien Tanpa Tanggal Lahir", "nik": "3201010101990456",
             "gender": "male"},
        )
        self.assertEqual(response.status_code, 500, response.text[:200])
        self.assertEqual(
            response.headers.get("Content-Type"), "application/json; charset=utf-8",
            "Batas API menjawab dengan halaman HTML, bukan amplop JSON: %s"
            % response.text[:200],
        )
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertEqual(
            self.env["hms.patient"].sudo().search_count(
                [("name", "=", "Pasien Tanpa Tanggal Lahir")]), 0,
        )

    # --- idempotensi ------------------------------------------------------
    # Endpoint observasi dipakai di sini karena ia ``idempotent=True`` DAN
    # kegagalannya bisa dipastikan naik di dalam handler sebagai exception
    # Python, bukan sebagai galat tingkat basis data.
    def test_failed_request_is_not_stored_as_a_replayable_response(self):
        key = "ZT-ROLLBACK-IDEM-GAGAL"
        Idem = self.env["hms.api.idempotency"].sudo()
        with self._exploding_emit(UserError("Uji: gagal sesudah baris ditulis.")):
            response = self._post(
                "/api/v1/encounters/%d/observations" % self.encounter.id,
                self._observation_payload(), idempotency_key=key,
            )
        self.assertEqual(response.status_code, 400, response.text[:400])
        self.assertEqual(
            Idem.search_count([("key", "=", key)]), 0,
            "Permintaan gagal tersimpan sebagai respons yang bisa diputar ulang.",
        )
        self.assertEqual(self._observations_left(), 0)

    def test_successful_request_is_still_stored_for_replay(self):
        key = "ZT-ROLLBACK-IDEM-SUKSES"
        Idem = self.env["hms.api.idempotency"].sudo()
        token = self._token()
        path = "/api/v1/encounters/%d/observations" % self.encounter.id

        first = self._post(path, self._observation_payload(), token=token,
                           idempotency_key=key)
        self.assertEqual(first.status_code, 200, first.text[:400])
        self.assertEqual(Idem.search_count([("key", "=", key)]), 1)

        second = self._post(path, self._observation_payload(), token=token,
                            idempotency_key=key)
        self.assertEqual(second.status_code, 200, second.text[:400])
        self.assertEqual(second.headers.get("X-HMS-Idempotent-Replay"), "1")
        self.assertEqual(
            self._observations_left(), 1,
            "Pengulangan dengan kunci yang sama mencatat observasi kedua.",
        )
