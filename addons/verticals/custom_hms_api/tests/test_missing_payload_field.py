# -*- coding: utf-8 -*-
"""Payload yang kurang field wajib adalah kesalahan KLIEN, bukan insiden sistem.

CACAT YANG DIUJI DI SINI
------------------------
Empat puluh tujuh pemanggilan ``body["..."]`` tersebar di sepuluh controller
tanpa penjaga. Payload yang kurang satu kunci karena itu melempar ``KeyError``
mentah, yang jatuh ke cabang ``except Exception`` di ``hms_route``::

    POST /api/v1/nursing/requests {"to_unit": "nutrition", "detail": "..."}
    -> 500 {"code": "internal_error",
            "message": "Terjadi kesalahan sistem. Hubungi administrator..."}

Integritasnya utuh (rollback bekerja, nol baris), tetapi kontraknya bohong dua
kali: klien yang salah kirim disuruh **menghubungi administrator** atas
kesalahannya sendiri, dan setiap payload cacat menulis satu baris ``ERROR``
plus traceback penuh ke log — sehingga galat sungguhan tenggelam di antaranya.

KENAPA PERBAIKANNYA DI BATAS, BUKAN DI 47 TEMPAT
------------------------------------------------
Menambal tiap pemanggilan berarti 47 kesempatan untuk lupa, dan endpoint ke-48
akan lahir tanpa penjaga. ``payload()`` mengembalikan subclass ``dict`` yang
menimpa ``__missing__``; ``hms_route`` menangkap tipe khusus itu.

KENAPA BUKAN ``except KeyError``
--------------------------------
``KeyError`` yang lahir dari dalam logika bisnis — dict internal, cache,
mapping kode — bukan kesalahan klien. Menangkapnya sebagai "field wajib
hilang" akan menyembunyikan bug nyata di balik 422 yang menenangkan, dan
justru pada jalur yang paling sering dilewati. ``test_business_key_error_...``
di bawah adalah yang membuktikan pembedaan itu nyata: ia memaksa ``KeyError``
dengan nama kunci yang **persis sama** dengan field payload, dari dict milik
logika bisnis sendiri, dan tetap menuntut 500.

KONTROL POSITIF
---------------
``test_complete_payload_is_accepted_and_actually_stored`` ada karena tangkapan
yang dipasang keliru bisa membuat setiap permintaan cacat terlihat "bersih"
sambil diam-diam menolak yang sah — dan itu lolos tes 422 dengan gemilang.
Kontrolnya memeriksa barisnya benar-benar ada di basis data, bukan hanya status
responsnya.
"""
import json
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from .common import fixture_password

NURSE_GROUP = "custom_hms_base.group_hms_nurse"

MARKER = "ZT-MISSING-FIELD-PROBE"


@tagged("post_install", "-at_install", "hms")
class MissingPayloadFieldCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.user = cls.env["res.users"].create({
            "name": "Perawat Uji Payload",
            "login": "zt-payload@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [(4, cls.env.ref(NURSE_GROUP).id)],
        })
        cls.station = cls.env["hms.nursing.station"].create({
            "code": "ZT-MF-NS", "name": "Station Uji Payload", "type": "inpatient",
        })

    # --- plumbing (sama alasannya dengan test_rejected_request_rollback) ---
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

    def _requests_left(self):
        return self.env["hms.unit.request"].search_count([("detail", "=", MARKER)])

    def _complete_payload(self):
        """Hanya field wajib. Kunci opsional sengaja TIDAK dikirim supaya tes
        ini sekaligus membuktikan ``body.get(...)`` tetap tidak melempar."""
        return {"station_id": self.station.id, "to_unit": "nutrition", "detail": MARKER}

    # --- 1. field wajib hilang -> 422 -------------------------------------
    def test_missing_required_field_is_a_client_error(self):
        """Reproduksi aslinya: ``station_id`` tidak dikirim."""
        response = self._post(
            "/api/v1/nursing/requests",
            {"to_unit": "nutrition", "detail": MARKER},
        )
        self.assertEqual(
            response.status_code, 422,
            "Payload yang kurang field wajib dijawab %s, bukan 422: %s"
            % (response.status_code, response.text[:300]),
        )
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertIn(
            "station_id", error["fields"],
            "Klien tidak diberi tahu field mana yang hilang: fields=%r" % (error["fields"],),
        )
        self.assertIn("station_id", error["message"])
        self.assertNotIn(
            "administrator", error["message"].lower(),
            "Klien disuruh menghubungi administrator atas kesalahannya sendiri.",
        )
        self.assertEqual(self._requests_left(), 0)

    def test_empty_body_names_the_missing_field_too(self):
        """``body = body or {}`` ada di 39 handler.

        Badan kosong adalah justru payload yang paling mungkin kurang field,
        dan sebuah pembungkus yang jatuh kembali ke ``dict`` biasa di situ akan
        gagal tepat pada kasus yang paling sering terjadi.
        """
        response = self._post("/api/v1/nursing/requests", {})
        self.assertEqual(response.status_code, 422, response.text[:300])
        self.assertEqual(response.json()["error"]["code"], "validation_error")
        self.assertIn("station_id", response.json()["error"]["fields"])

    # --- 2. KONTROL POSITIF ------------------------------------------------
    def test_complete_payload_is_accepted_and_actually_stored(self):
        """Tangkapan yang kelewat lebar menolak permintaan yang sah tanpa suara.

        Status 200 saja tidak cukup sebagai bukti: yang diperiksa adalah
        barisnya ada di basis data sesudah permintaan selesai.
        """
        response = self._post("/api/v1/nursing/requests", self._complete_payload())
        self.assertEqual(response.status_code, 200, response.text[:400])
        self.assertEqual(
            self._requests_left(), 1,
            "Payload LENGKAP tidak tersimpan. Perbaikan yang menolak atau "
            "me-rollback semua permintaan lulus tes 422 dengan gemilang.",
        )
        record = self.env["hms.unit.request"].search([("detail", "=", MARKER)])
        self.assertEqual(record.station_id, self.station)
        self.assertEqual(record.to_unit, "nutrition")

    # --- 3. KeyError bisnis tetap 500 --------------------------------------
    def _business_key_error(self, key):
        """``KeyError`` dari dict MILIK logika bisnis, bukan dari ``body``.

        ``hms.unit.request.create`` memanggil ``hms.event.emit`` sesudah
        INSERT-nya berhasil, jadi ini menempatkan galatnya di dalam tumpukan
        panggilan handler — tempat yang sama dengan bug sungguhan — tanpa
        menambah route palsu ke kode produksi.
        """
        Event = type(self.env["hms.event"])
        original = Event.emit

        def exploding(model, topic, payload):
            original(model, topic, payload)
            internal = {"topik": topic}   # dict internal, bukan badan permintaan
            return internal[key]

        return patch.object(Event, "emit", exploding)

    def test_business_key_error_is_still_an_internal_error(self):
        """Nama kuncinya sengaja ``station_id`` — sama persis dengan field payload.

        Kalau pembedaannya heuristik (mencocokkan nama kunci, atau menangkap
        ``KeyError`` polos), tes ini akan menjawab 422 dan bug sungguhan
        tersembunyi di balik pesan "field wajib hilang". Pembedaan yang benar
        bersifat struktural: ``__missing__`` hanya terpanggil pada dict payload
        itu sendiri.
        """
        with self._business_key_error("station_id"):
            response = self._post("/api/v1/nursing/requests", self._complete_payload())
        self.assertEqual(
            response.status_code, 500,
            "KeyError dari logika bisnis disamarkan jadi kesalahan klien: %s"
            % response.text[:300],
        )
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        self.assertEqual(self._requests_left(), 0)
