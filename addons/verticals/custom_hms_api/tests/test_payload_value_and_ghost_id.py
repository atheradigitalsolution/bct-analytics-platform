# -*- coding: utf-8 -*-
"""Dua bentuk 500 yang tersisa: nilai tak terkonversi, dan id hantu.

BENTUK 2 — NILAI YANG TIDAK BISA DIKONVERSI
-------------------------------------------
Empat puluh satu ekspresi ``int(...)`` / ``float(...)`` atas nilai badan
permintaan tersebar di sembilan controller; tiga puluh delapan di antaranya
berbentuk ``int(body["x"])`` — satu ekspresi, dua kegagalan berbeda. Gelombang
10 menutup kegagalan pertama (kuncinya tidak ada -> ``MissingPayloadField``).
Yang kedua masih terbuka::

    POST /api/v1/nursing/requests {"station_id": "dua", ...}
    -> 500 {"code": "internal_error", "message": "... Hubungi administrator ..."}

Nol baris tersimpan, jadi integritasnya utuh — tetapi kontraknya bohong dengan
cara yang persis sama seperti sebelum Gelombang 10.

BENTUK 3 — ID HANTU
-------------------
``browse(999999)`` **truthy** (lihat ``test_browse_of_a_ghost_id_is_truthy``),
jadi ``if not record`` tidak menolong dan idnya mengalir apa adanya ke
``create()``. Postgres menolaknya sebagai pelanggaran kunci asing dan
``except Exception`` di ``hms_route`` mengubahnya menjadi 500::

    POST /api/v1/nursing/requests {"station_id": 999999, ...}
    -> 500

JALUR BACA TIDAK IKUT DIUBAH
----------------------------
``GET /patients/999999`` sudah 404 karena ``hms_route`` menangkap
``MissingError``. Angka "63 ``browse()`` tanpa ``.exists()``" bukan 63 masalah;
yang bermasalah hanya id hantu yang sampai ke sebuah tulisan.

KENAPA SELISIH, BUKAN ANGKA MUTLAK
-----------------------------------
Setiap assertion baris di berkas ini mengukur jumlah SEBELUM dan SESUDAH lalu
membandingkan selisihnya. Assertion yang menuntut angka mutlak sesudah sebuah
penolakan sedang menguji fixture-nya sendiri, bukan kodenya: ia tetap hijau
kalau penolakannya tidak pernah terjadi tapi fixture kebetulan kosong.

KONTROL POSITIF — YANG PALING MUDAH DILUPAKAN
----------------------------------------------
Penjaga yang terlalu rakus lulus tes "payload cacat ditolak" dengan gemilang
sambil menolak permintaan yang sah. Tiga kontrol karena itu diabadikan sebagai
tes permanen, bukan probe sekali jalan:

* payload lengkap dan sah -> sukses, selisih +1;
* ``"7"`` sebagai TEKS tetap sah (``int("7")`` bekerja) dan ``"12.5"`` sebagai
  teks tetap sah untuk field uang (``float("12.5")`` bekerja);
* id yang benar-benar ada tetap diterima.
"""
import json
from unittest.mock import patch

import psycopg2

from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import fixture_password

GROUPS = (
    "custom_hms_base.group_hms_nurse",
    "custom_hms_base.group_hms_registration_user",
)

MARKER = "ZT-VALUE-GHOST-PROBE"
GHOST_ID = 999999


@tagged("post_install", "-at_install", "hms")
class PayloadValueAndGhostIdCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.user = cls.env["res.users"].create({
            "name": "Perawat Uji Nilai",
            "login": "zt-nilai@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [(4, cls.env.ref(g).id) for g in GROUPS],
        })
        cls.station = cls.env["hms.nursing.station"].create({
            "code": "ZT-VG-NS", "name": "Station Uji Nilai", "type": "inpatient",
        })
        cls.patient = cls.env["hms.patient"].create({
            "name": "Pasien Uji Nilai",
            "nik": "9999000011112221",
            "gender": "male",
            "birth_date": "1990-01-01",
        })

    # --- plumbing (sama alasannya dengan test_missing_payload_field) -------
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
            path,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Host": self._host(),
                "Authorization": "Bearer %s" % self._token(),
            },
        )
        self.env.invalidate_all()
        return response

    def _requests(self):
        return self.env["hms.unit.request"].search_count([("detail", "=", MARKER)])

    def _deposits(self):
        return self.env["hms.deposit"].search_count([("reference", "=", MARKER)])

    def _patients(self):
        return self.env["hms.patient"].search_count([("nik", "=", "9999000011112221")])

    def _valid(self, **over):
        values = {"station_id": self.station.id, "to_unit": "nutrition", "detail": MARKER}
        values.update(over)
        return values

    # =====================================================================
    # BENTUK 2 — nilai yang tidak bisa dikonversi
    # =====================================================================
    def test_unconvertible_value_is_a_client_error(self):
        """Reproduksi aslinya: ``{"station_id": "dua"}``."""
        before = self._requests()
        response = self._post("/api/v1/nursing/requests", self._valid(station_id="dua"))
        self.assertEqual(
            response.status_code, 422,
            "Nilai yang tidak bisa dikonversi dijawab %s, bukan 422: %s"
            % (response.status_code, response.text[:300]),
        )
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertIn(
            "station_id", error["fields"],
            "Klien tidak diberi tahu field mana yang nilainya ditolak: fields=%r"
            % (error["fields"],),
        )
        self.assertIn("station_id", error["message"])
        self.assertNotIn(
            "administrator", error["message"].lower(),
            "Klien disuruh menghubungi administrator atas kesalahannya sendiri.",
        )
        self.assertEqual(
            self._requests() - before, 0,
            "Permintaan yang ditolak tetap menyimpan baris.",
        )

    def test_unconvertible_money_value_names_its_own_field(self):
        """Bukan hanya ``int``: ``float(body["amount"])`` di ``/deposits``.

        Kalau penjaganya dipasang di satu controller dan bukan di batas, tes
        ini yang memperlihatkannya.
        """
        before = self._deposits()
        response = self._post("/api/v1/deposits", {
            "patient_id": self.patient.id, "amount": "banyak", "reference": MARKER,
        })
        self.assertEqual(response.status_code, 422, response.text[:300])
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertIn("amount", error["fields"], error["fields"])
        self.assertEqual(self._deposits() - before, 0)

    # =====================================================================
    # BENTUK 3 — id hantu
    # =====================================================================
    def test_browse_of_a_ghost_id_is_truthy(self):
        """Fakta ORM yang menjadi dasar seluruh perbaikan ini.

        Kalau Odoo suatu hari membuat ``browse()`` atas id yang tidak ada
        menjadi falsy, ``.exists()`` berubah jadi mubazir dan setiap tes di
        bawahnya berhenti menguji apa pun **tanpa memberi tahu siapa pun**.
        Tes ini berteriak lebih dulu.
        """
        ghost = self.env["hms.nursing.station"].browse(GHOST_ID)
        self.assertTrue(
            bool(ghost),
            "browse() atas id yang tidak ada sudah TIDAK truthy lagi — "
            "perbaikan id hantu perlu ditinjau ulang.",
        )
        self.assertFalse(ghost.exists())

    def test_ghost_id_reaching_a_write_is_a_client_error(self):
        before = self._requests()
        response = self._post("/api/v1/nursing/requests", self._valid(station_id=GHOST_ID))
        self.assertEqual(
            response.status_code, 422,
            "Id hantu dijawab %s, bukan 422: %s"
            % (response.status_code, response.text[:300]),
        )
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertIn(
            "station_id", error["fields"],
            "Field yang merujuk data hantu tidak disebut: fields=%r" % (error["fields"],),
        )
        self.assertIn("station_id", error["message"])
        self.assertIn(
            "tidak ada", error["message"].lower(),
            "Pesannya tidak mengatakan bahwa data yang dirujuk tidak ada: %s"
            % error["message"],
        )
        self.assertNotIn("administrator", error["message"].lower())
        self.assertEqual(self._requests() - before, 0)

    # =====================================================================
    # KONTROL POSITIF — penjaga yang rakus gagal di sini, bukan di atas
    # =====================================================================
    def test_valid_payload_with_real_id_is_stored(self):
        before = self._requests()
        response = self._post("/api/v1/nursing/requests", self._valid())
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(
            self._requests() - before, 1,
            "Payload sah dengan id nyata tidak tersimpan (selisih %s)."
            % (self._requests() - before),
        )

    def test_numeric_text_is_still_a_valid_id(self):
        """``int("7")`` bekerja, jadi ``"7"`` sebagai TEKS harus tetap sah.

        Penjaga yang menolak setiap nilai bertipe ``str`` lulus setiap tes
        penolakan di berkas ini dan tetap merusak klien yang benar.
        """
        before = self._requests()
        response = self._post(
            "/api/v1/nursing/requests", self._valid(station_id=str(self.station.id)),
        )
        self.assertEqual(
            response.status_code, 200,
            "Id yang dikirim sebagai teks angka ikut ditolak: %s" % response.text[:300],
        )
        self.assertEqual(self._requests() - before, 1)

    def test_decimal_text_is_still_a_valid_amount(self):
        """``float("12.5")`` bekerja; ``"12.5"`` sebagai teks harus tetap sah."""
        before = self._deposits()
        response = self._post("/api/v1/deposits", {
            "patient_id": self.patient.id, "amount": "12.5", "reference": MARKER,
        })
        self.assertEqual(
            response.status_code, 200,
            "Jumlah desimal sebagai teks ikut ditolak: %s" % response.text[:300],
        )
        self.assertEqual(self._deposits() - before, 1)
        self.assertEqual(
            self.env["hms.deposit"].search([("reference", "=", MARKER)], limit=1).amount,
            12.5,
        )

    # =====================================================================
    # YANG TIDAK BOLEH IKUT TERTANGKAP
    # =====================================================================
    def test_business_unique_constraint_is_not_reported_as_a_ghost_id(self):
        """Constraint bisnis kita sendiri lewat jalur psycopg2 yang SAMA.

        ``models.Constraint("unique(nik)")`` melahirkan ``UniqueViolation``
        (pgcode 23505) dari ``create()`` yang sama dengan pelanggaran kunci
        asing (23503). Menangkap ``IntegrityError`` apa adanya akan melaporkan
        NIK ganda sebagai "data yang dirujuk tidak ada" — sebuah pesan yang
        salah TENTANG data yang sebenarnya ada.
        """
        duplicate = {
            "name": "Pasien Kembar", "nik": self.patient.nik,
            "gender": "female", "birth_date": "1991-02-02",
        }
        # PENJAGA ATAS TES INI SENDIRI. Versi pertama tes ini lupa
        # ``birth_date`` dan karena itu memicu NotNullViolation (23502), bukan
        # UniqueViolation (23505): ia hijau sambil tidak pernah menyentuh
        # constraint bisnis yang seharusnya diuji. Sebuah tes yang diam-diam
        # berpindah sasaran tidak menguji apa pun, jadi sasarannya ditegaskan
        # di sini.
        with self.assertRaises(psycopg2.errors.UniqueViolation) as caught, \
                mute_logger("odoo.sql_db"), self.env.cr.savepoint(flush=False):
            self.env["hms.patient"].create(duplicate)
            self.env.flush_all()
        self.assertEqual(caught.exception.pgcode, "23505")
        self.env.invalidate_all()

        before = self._patients()
        response = self._post("/api/v1/patients", duplicate)
        body = response.text[:400]
        self.assertNotIn(
            "tidak ada", body.lower(),
            "Pelanggaran keunikan dilaporkan seolah datanya tidak ada: %s" % body,
        )
        if response.status_code == 422:
            self.assertNotIn("nik", response.json()["error"].get("fields", {}))
        self.assertEqual(
            self._patients() - before, 0,
            "Pasien dengan NIK ganda tersimpan.",
        )

    def _business_value_error(self, text):
        """``ValueError`` dari dalam logika bisnis, bukan dari konversi payload.

        ``hms.unit.request.create`` memanggil ``hms.event.emit`` sesudah
        INSERT-nya berhasil, jadi galatnya lahir di dalam tumpukan panggilan
        handler — tempat yang sama dengan bug sungguhan.
        """
        Event = type(self.env["hms.event"])
        original = Event.emit

        def exploding(model, topic, payload):
            original(model, topic, payload)
            return int(text)  # cacat internal, bukan nilai dari klien

        return patch.object(Event, "emit", exploding)

    def test_business_value_error_is_still_an_internal_error(self):
        """Teksnya sengaja SAMA PERSIS dengan sebuah nilai di badan permintaan.

        Pembedaan yang hanya mencocokkan nilai gagal di sini dan menyamarkan
        bug internal sebagai "payload jelek" — bug yang akan hidup lama karena
        setiap kemunculannya terbaca sebagai kesalahan klien. Pembedaan yang
        benar bersifat struktural: bingkai terdalam traceback harus berada di
        ``controllers/``, tempat konversi payload memang terjadi; logika bisnis
        tinggal di ``models/``.
        """
        before = self._requests()
        with self._business_value_error("dua"):
            response = self._post(
                "/api/v1/nursing/requests", self._valid(type="dua"),
            )
        self.assertEqual(
            response.status_code, 500,
            "ValueError dari logika bisnis disamarkan jadi kesalahan klien: %s"
            % response.text[:300],
        )
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertEqual(self._requests() - before, 0)
