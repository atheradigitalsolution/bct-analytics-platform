# -*- coding: utf-8 -*-
"""Tiga worklist penunjang: yang dibaca LAYAR, bukan yang dijanjikan penyemai.

KENAPA BERKAS INI ADA
---------------------
Laboratorium, radiologi, dan apotek adalah tiga layar yang diperagakan
berdampingan dengan dasbor yang penuh — dan ketiganya kosong. Bukan karena
datanya tidak ada: 46 hasil lab, 4 ekspertise, dan 1 resep memang tersimpan,
tetapi SEMUANYA sudah selesai. Worklist menampilkan pekerjaan yang sedang
berjalan, dan pekerjaan yang sudah beres bukan salah satunya.

Karena itu yang diuji di sini adalah **endpoint**, bukan jumlah baris di
tabel. Tes "ada 46 hasil lab" hijau dengan gemilang pada keadaan yang justru
sedang diperbaiki; hanya permintaan ke ``/api/v1/lab/worklist`` yang mengukur
hal yang sama dengan layarnya.

KONTROL POSITIF YANG DIABADIKAN
-------------------------------
Penyemai yang menaruh SEMUA pekerjaan di satu status "menunggu" lulus uji
"≥5 baris" dengan sempurna sambil membuat alurnya berbohong: rumah sakit yang
tidak pernah menyelesaikan apa pun. Karena itu setiap worklist diuji dua
arah — pekerjaan berjalan HARUS muncul, pekerjaan selesai (``verified`` /
``dispensed``) harus tetap ada di basis data dan tetap DI LUAR worklist.

Batasnya (5 baris) bersumber dari kebutuhan layar — sebuah daftar yang cukup
untuk dipandang sebagai daftar — bukan dari jumlah baris yang kebetulan
dihasilkan penyemai hari ini. Menegakkan angka persis membuat tes ini merah
setiap kali seseorang menambah satu order.
"""
import json
from unittest.mock import patch

from odoo.addons.custom_hms_api.tests.common import fixture_password
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

GROUPS = (
    "custom_hms_base.group_hms_diagnostic_verifier",
    "custom_hms_base.group_hms_pharmacist",
)

LAB_WORKLIST_STATES = ("pending", "entered", "validated")
RAD_WORKLIST_STATES = ("scheduled", "performed", "reported")
RX_QUEUE_STATES = ("submitted", "verified", "preparing", "ready")


@tagged("post_install", "-at_install", "hms")
class DemoWorklistCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.user = cls.env["res.users"].create({
            "name": "Pembaca Worklist Demo",
            "login": "zt-worklist@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [(4, cls.env.ref(g).id) for g in GROUPS],
        })

    # --- plumbing ---------------------------------------------------------
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

    def _get(self, path):
        response = self.url_open(path, headers={
            "Host": self._host(),
            "Authorization": "Bearer %s" % self._token(),
        })
        self.assertEqual(response.status_code, 200, response.text[:400])
        return response.json()

    def _lab_items(self):
        return self._get("/api/v1/lab/worklist")["items"]

    def _lab_states(self):
        """Status lab hidup DI DALAM baris worklist.

        Payload lab dikelompokkan per baris order dan status ada pada tiap
        hasil, bukan pada barisnya — jadi sebaran status dibaca dari sana.
        """
        return {r["state"] for item in self._lab_items() for r in item["results"]}

    # =====================================================================
    # Laboratorium
    # =====================================================================
    def test_lab_worklist_has_work_on_the_bench(self):
        items = self._lab_items()
        self.assertGreaterEqual(
            len(items), 5,
            "Layar worklist lab menampilkan %s baris; berdampingan dengan "
            "dasbor yang penuh itu terbaca sebagai lab yang tidak bekerja."
            % len(items),
        )

    def test_lab_worklist_shows_the_flow_not_one_frozen_step(self):
        states = self._lab_states()
        self.assertGreaterEqual(
            len(states), 3,
            "Seluruh pekerjaan lab berada di status %s. Satu status saja "
            "memperagakan antrian yang macet, bukan alur yang hidup." % sorted(states),
        )

    def test_finished_lab_work_stays_out_of_the_worklist(self):
        """Kontrol positif: yang sudah diverifikasi TIDAK boleh ikut tampil."""
        verified = self.env["hms.lab.result"].search_count([("state", "=", "verified")])
        self.assertGreater(
            verified, 0,
            "Tidak ada satu pun hasil lab yang selesai: penyemai menaruh "
            "semuanya di antrian, dan itu membuat alurnya berbohong.",
        )
        leaked = {s for s in self._lab_states() if s not in LAB_WORKLIST_STATES}
        self.assertFalse(leaked, "Status di luar antrian ikut tampil: %s" % sorted(leaked))

    def test_a_critical_value_is_still_waiting_to_be_acknowledged(self):
        """Slide menjanjikan closed-loop nilai kritis; harus ada yang terbuka."""
        waiting = self.env["hms.lab.result"].search([
            ("is_critical", "=", True), ("ack_state", "in", ("pending", "overdue")),
        ])
        self.assertTrue(
            waiting,
            "Tidak ada nilai kritis yang menunggu pengakuan: layar closed-loop "
            "TBaK tidak punya apa pun untuk diperagakan.",
        )

    def test_a_finished_lab_test_never_rests_on_an_unreceived_specimen(self):
        """Pemeriksaan selesai atas spesimen yang tidak pernah diterima."""
        incoherent = self.env["hms.order.line"].search([
            ("order_type", "=", "lab"), ("state", "=", "done"),
            ("specimen_state", "=", "pending"),
        ])
        self.assertFalse(
            incoherent.mapped("name"),
            "%s baris lab selesai sementara spesimennya belum diterima."
            % len(incoherent),
        )

    # =====================================================================
    # Radiologi
    # =====================================================================
    def test_radiology_worklist_has_examinations_waiting(self):
        items = self._get("/api/v1/radiology/worklist")["items"]
        self.assertGreaterEqual(
            len(items), 5,
            "Worklist radiologi menampilkan %s baris." % len(items),
        )

    def test_radiology_worklist_shows_more_than_one_step(self):
        states = {i["state"] for i in self._get("/api/v1/radiology/worklist")["items"]}
        self.assertGreaterEqual(
            len(states), 2,
            "Seluruh permintaan radiologi berada di status %s." % sorted(states),
        )

    def test_finished_radiology_work_stays_out_of_the_worklist(self):
        verified = self.env["hms.rad.report"].search_count([("state", "=", "verified")])
        self.assertGreater(verified, 0, "Tidak ada ekspertise yang selesai sama sekali.")
        leaked = {i["state"] for i in self._get("/api/v1/radiology/worklist")["items"]
                  if i["state"] not in RAD_WORKLIST_STATES}
        self.assertFalse(leaked, "Status di luar antrian ikut tampil: %s" % sorted(leaked))

    # =====================================================================
    # Apotek
    # =====================================================================
    def test_pharmacy_queue_has_prescriptions_waiting(self):
        items = self._get("/api/v1/pharmacy/queue")["items"]
        self.assertGreaterEqual(
            len(items), 5,
            "Antrian apotek menampilkan %s baris." % len(items),
        )

    def test_pharmacy_queue_shows_the_flow_not_one_frozen_step(self):
        states = {i["state"] for i in self._get("/api/v1/pharmacy/queue")["items"]}
        self.assertGreaterEqual(
            len(states), 3,
            "Seluruh resep berada di status %s." % sorted(states),
        )

    def test_dispensed_prescriptions_stay_out_of_the_queue(self):
        dispensed = self.env["hms.prescription"].search_count([("state", "=", "dispensed")])
        self.assertGreater(
            dispensed, 0,
            "Tidak ada resep yang pernah diserahkan: apotek yang hanya "
            "menumpuk antrian memperagakan loket yang tidak bekerja.",
        )
        leaked = {i["state"] for i in self._get("/api/v1/pharmacy/queue")["items"]
                  if i["state"] not in RX_QUEUE_STATES}
        self.assertFalse(leaked, "Status di luar antrian ikut tampil: %s" % sorted(leaked))

    def test_the_queue_carries_a_high_alert_prescription_awaiting_double_check(self):
        """Obat high-alert menuntut saksi kedua; harus terlihat di antrian."""
        items = self._get("/api/v1/pharmacy/queue")["items"]
        high_alert = [i for i in items if i["has_high_alert"]]
        self.assertTrue(
            high_alert,
            "Tidak ada resep high-alert di antrian: penanda double-check "
            "apoteker tidak punya apa pun untuk ditunjukkan.",
        )
        pending = self.env["hms.prescription"].search([
            ("id", "in", [i["id"] for i in high_alert]), ("witness_id", "=", False),
        ])
        self.assertTrue(
            pending,
            "Semua resep high-alert di antrian sudah punya saksi; tidak ada "
            "yang memperagakan verifikasi dua orang yang masih ditunggu.",
        )

    # =====================================================================
    # Pagar database demo
    # =====================================================================
    def test_the_new_seeding_path_also_refuses_a_database_that_is_not_demo(self):
        """Jalur baru harus menolak sekeras ``post_init_hook``.

        Pagar yang hanya dipasang di pintu lama memindahkan kecelakaannya,
        tidak mencegahnya: order penunjang demo di database produksi menempel
        pada kunjungan sungguhan dan menagih pasien sungguhan.
        """
        builder = self.env["hms.demo.builder"]
        content = self.env["hms.demo.content"]
        with patch.object(type(builder), "_database_name", lambda self: "rs_produksi"):
            with self.assertRaises(UserError):
                content._support_worklists()
            with self.assertRaises(UserError):
                builder.seed_support_worklists()

    # =====================================================================
    # Idempotensi
    # =====================================================================
    def test_seeding_the_worklists_twice_changes_nothing(self):
        models = ("hms.order", "hms.order.line", "hms.lab.result", "hms.rad.report",
                  "hms.prescription", "hms.prescription.line")
        before = {m: self.env[m].search_count([]) for m in models}
        for model, states in (("hms.lab.result", LAB_WORKLIST_STATES),
                              ("hms.rad.report", RAD_WORKLIST_STATES),
                              ("hms.prescription", RX_QUEUE_STATES)):
            before["%s/antrian" % model] = self.env[model].search_count([
                ("state", "in", list(states)),
            ])
        self.env["hms.demo.builder"].seed_all()
        after = {m: self.env[m].search_count([]) for m in models}
        for model, states in (("hms.lab.result", LAB_WORKLIST_STATES),
                              ("hms.rad.report", RAD_WORKLIST_STATES),
                              ("hms.prescription", RX_QUEUE_STATES)):
            after["%s/antrian" % model] = self.env[model].search_count([
                ("state", "in", list(states)),
            ])
        self.assertEqual(before, after)
