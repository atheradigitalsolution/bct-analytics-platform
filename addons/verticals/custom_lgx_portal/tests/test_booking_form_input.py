# -*- coding: utf-8 -*-
"""Formulir booking menolak isian ngawur, bukan meledak di hadapan pelanggan.

Diuji lewat HTTP dan bukan ORM — berbeda dari test_portal_isolation yang
sengaja turun ke lapisan record rule. Cacat yang dikejar di sini HIDUP di
controller: nilai form datang dari HTTP, bukan dari dropdown, dan siapa pun
dapat mengirim apa saja. Memanggil methodnya langsung akan melewati persis
bagian yang rusak.
"""
import re

from odoo.tests import HttpCase, tagged

SANDI = "uji-booking-2026"


@tagged("post_install", "-at_install")
class TestBookingFormInput(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "PT Pemesan Portal"})
        cls.user = cls.env["res.users"].create({
            "name": "Pemesan", "login": "pemesan@uji.invalid",
            "password": SANDI,
            "partner_id": cls.partner.id,
            "group_ids": [(6, 0, [cls.env.ref("base.group_portal").id])],
        })
        cls.origin = cls.env.ref("custom_lgx_base.loc_cnsha")
        cls.destination = cls.env.ref("custom_lgx_base.loc_idjkt")

    def _csrf(self):
        page = self.url_open("/my/logistik/booking")
        self.assertEqual(page.status_code, 200, "Formulir booking harus dapat dibuka.")
        found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text)
        self.assertTrue(found, "Token CSRF tidak ditemukan di formulir.")
        return found.group(1)

    def _jobs_of_partner(self):
        return self.env["lgx.job"].search([("customer_id", "=", self.partner.id)])

    def test_unreadable_location_is_refused_not_a_crash(self):
        """`int("abc")` melempar ValueError — pelanggan melihat 500, bukan panduan."""
        self.authenticate("pemesan@uji.invalid", SANDI)
        sebelum = len(self._jobs_of_partner())
        response = self.url_open("/my/logistik/booking", data={
            "csrf_token": self._csrf(),
            "job_type": "ff_import",
            "transport_mode": "sea",
            "origin_id": "abc",
            "destination_id": str(self.destination.id),
            "customer_reference": "REF-NGAWUR",
        })
        self.assertEqual(response.status_code, 200,
                         "Isian ngawur harus menghasilkan formulir, bukan halaman galat.")
        self.assertIn("tidak dikenal", response.text)
        self.assertEqual(len(self._jobs_of_partner()), sebelum,
                         "Tidak ada job yang boleh lahir dari pengajuan yang ditolak.")

    def test_nonexistent_location_id_is_refused_too(self):
        """`int("999999")` BERHASIL, lalu basis data yang menolak id itu.

        Bentuk kedua ini lolos dari penjaga yang hanya membungkus int(), dan
        ia justru yang lebih mudah terjadi: id lama dari tab yang sudah usang.
        """
        self.authenticate("pemesan@uji.invalid", SANDI)
        sebelum = len(self._jobs_of_partner())
        response = self.url_open("/my/logistik/booking", data={
            "csrf_token": self._csrf(),
            "job_type": "ff_import",
            "transport_mode": "sea",
            "origin_id": "999999",
            "destination_id": str(self.destination.id),
            "customer_reference": "REF-HILANG",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("tidak dikenal", response.text)
        self.assertEqual(len(self._jobs_of_partner()), sebelum)

    def test_a_valid_booking_is_still_accepted(self):
        """Penjaga tidak boleh rakus.

        Penjaga yang menolak segalanya akan lolos kedua uji di atas dengan
        gemilang, dan mematikan portalnya sekaligus.
        """
        self.authenticate("pemesan@uji.invalid", SANDI)
        response = self.url_open("/my/logistik/booking", data={
            "csrf_token": self._csrf(),
            "job_type": "ff_import",
            "transport_mode": "sea",
            "origin_id": str(self.origin.id),
            "destination_id": str(self.destination.id),
            "customer_reference": "REF-SAH",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("tidak dikenal", response.text)
        job = self._jobs_of_partner().filtered(
            lambda j: j.customer_reference == "REF-SAH")
        self.assertTrue(job, "Pengajuan yang sah harus menghasilkan job.")
        self.assertEqual(job.origin_location_id, self.origin)
        self.assertEqual(job.destination_location_id, self.destination)

    def test_booking_without_locations_is_still_allowed(self):
        """Tidak mengisi simpul adalah pengajuan yang sah — kosong bukan ngawur."""
        self.authenticate("pemesan@uji.invalid", SANDI)
        response = self.url_open("/my/logistik/booking", data={
            "csrf_token": self._csrf(),
            "job_type": "ff_import",
            "transport_mode": "sea",
            "customer_reference": "REF-KOSONG",
        })
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("tidak dikenal", response.text)
        self.assertTrue(self._jobs_of_partner().filtered(
            lambda j: j.customer_reference == "REF-KOSONG"))
