# -*- coding: utf-8 -*-
"""Uji untuk pintu masuk publik.

Setiap uji di berkas ini menjaga sesuatu yang PERNAH salah di produksi, bukan
sesuatu yang mungkin salah. Baris kosong `{}` yang mendarat lewat endpoint ini pada
2026-09-03, dan tiga jalan keluar `return True` di verifikasi Turnstile, adalah dua
di antaranya.
"""

import json

from odoo.tests.common import TransactionCase, tagged

from ..controllers.public_intake import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    PUBLIC_FIELD_LIMITS,
    _sanitize,
    _verify_turnstile,
)


@tagged("post_install", "-at_install", "custom_onboarding_journey")
class TestPublicIntakeSanitizer(TransactionCase):
    def test_unknown_keys_are_dropped_not_rejected(self):
        clean = _sanitize({"company_name": "PT Contoh", "kolom_asing": "x" * 10})
        self.assertEqual(clean["company_name"], "PT Contoh")
        self.assertNotIn("kolom_asing", clean)

    def test_tax_and_bank_identifiers_never_enter_from_public_route(self):
        """Endpoint publik tidak menerima NPWP atau rekening.

        Ia menerimanya dulu, dan menyimpannya terbaca di basis data kontrol atas
        perintah pengirim yang tidak diverifikasi siapa pun. Yang menjaga view
        hub-portal bersih BUKAN daftar kolom di view itu — melainkan kenyataan
        bahwa nilainya tidak pernah masuk.
        """
        clean = _sanitize(
            {
                "company_name": "PT Contoh",
                "npwp": "00.000.000.0-000.000",
                "bank_name": "Bank Contoh",
                "bank_account": "1234567890",
            }
        )
        for forbidden in ("npwp", "bank_name", "bank_account"):
            self.assertNotIn(forbidden, clean)

    def test_file_uploads_are_not_accepted_anonymously(self):
        clean = _sanitize(
            {"company_name": "PT Contoh", "brd_file_base64s": ["AAAA"], "brd_filenames": ["a.docx"]}
        )
        self.assertNotIn("brd_file_base64s", clean)
        self.assertNotIn("brd_filenames", clean)

    def test_values_are_truncated_to_their_limit(self):
        clean = _sanitize({"company_name": "A" * 5000})
        self.assertEqual(len(clean["company_name"]), 200)

    def test_nested_structures_are_dropped(self):
        """Nilai berupa dict/list tidak boleh menyelinap lewat `str()`."""
        clean = _sanitize({"company_name": "PT Contoh", "message": {"a": ["b"] * 1000}})
        self.assertNotIn("message", clean)

    def test_empty_payload_yields_nothing_required(self):
        self.assertFalse(_sanitize({}).get("company_name"))

    def test_size_cap_is_reachable(self):
        """Batas ukuran harus bisa menyala.

        Daftar-putih sudah membatasi setiap kolom, jadi payload sah terbesar punya
        langit-langit yang bisa dihitung. Kalau batas byte dipasang jauh di atas
        langit-langit itu, ia tidak pernah bisa tercapai — penjagaan yang terlihat
        ada di kode tetapi tidak menguji apa pun. Nilai pertama yang dipakai di
        sini, 64 KB, persis begitu.

        Batas bawah menjaga kiriman jujur tidak pernah ditolak. Batas atas menjaga
        penjagaannya tetap dalam jangkauan: menambah satu kolom besar tanpa
        berpikir menabrak uji ini, bukan pengunjung.
        """
        ceiling = sum(PUBLIC_FIELD_LIMITS.values())
        self.assertGreater(
            DEFAULT_MAX_PAYLOAD_BYTES,
            ceiling,
            "batas lebih kecil dari payload sah terbesar; kiriman jujur akan ditolak",
        )
        self.assertLess(
            DEFAULT_MAX_PAYLOAD_BYTES,
            ceiling * 2,
            "batas terlalu jauh di atas langit-langit daftar-putih; ia tidak akan pernah menyala",
        )


@tagged("post_install", "-at_install", "custom_onboarding_journey")
class TestTurnstileFailsClosed(TransactionCase):
    """Tiga jalan keluar yang dulu semuanya `return True`."""

    def test_missing_secret_rejects_when_required(self):
        self.assertFalse(_verify_turnstile("", "token", None, required=True))

    def test_missing_secret_allows_when_not_required(self):
        self.assertTrue(_verify_turnstile("", "token", None, required=False))

    def test_missing_token_is_always_rejected(self):
        self.assertFalse(_verify_turnstile("s3cret", "", None, required=False))

    def test_verification_call_failure_rejects_when_required(self):
        """Cloudflare tidak terjangkau bukan alasan untuk melewatkan penjagaan.

        `import requests` di dalam fungsi membaca `sys.modules` lebih dulu, jadi
        mengganti entri itu cukup untuk mensimulasikan panggilan yang gagal — tanpa
        menyentuh jaringan dan tanpa menambal `__import__`.
        """
        import sys
        import types

        broken = types.ModuleType("requests")

        def _post(*_a, **_k):
            raise OSError("jaringan mati")

        broken.post = _post
        real = sys.modules.get("requests")
        sys.modules["requests"] = broken
        try:
            self.assertFalse(_verify_turnstile("s3cret", "token", None, required=True))
            self.assertTrue(_verify_turnstile("s3cret", "token", None, required=False))
        finally:
            if real is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = real

    def test_malformed_verification_response_rejects(self):
        """Balasan tanpa `success: true` adalah penolakan, termasuk balasan aneh."""
        import sys
        import types

        mod = types.ModuleType("requests")

        class _Resp:
            @staticmethod
            def json():
                return {"success": False, "error-codes": ["invalid-input-response"]}

        mod.post = lambda *_a, **_k: _Resp()
        real = sys.modules.get("requests")
        sys.modules["requests"] = mod
        try:
            self.assertFalse(_verify_turnstile("s3cret", "token", None, required=True))
            self.assertFalse(_verify_turnstile("s3cret", "token", None, required=False))
        finally:
            if real is None:
                sys.modules.pop("requests", None)
            else:
                sys.modules["requests"] = real


@tagged("post_install", "-at_install", "custom_onboarding_journey")
class TestIntakeThrottle(TransactionCase):
    """Batas laju hidup di basis data, bukan di memori proses.

    Uji ini tidak bisa membuktikan sifat "dibagi antar worker" sendirian — ia satu
    proses. Yang dibuktikannya adalah keadaan yang membuat sifat itu MUNGKIN:
    hitungannya ada di Postgres, sehingga pembaca mana pun melihat angka yang sama.
    Sifat antar-workernya dibuktikan di produksi, dengan kiriman berurutan yang
    ditolak setelah batasnya habis.
    """

    def setUp(self):
        super().setUp()
        self.Throttle = self.env["onboarding.intake.throttle"]
        self.ip = "hash-uji-%s" % self.env.cr.dbname

    def test_counts_up_to_the_limit_then_refuses(self):
        for i in range(3):
            self.assertFalse(
                self.Throttle.check_and_count(self.ip, 3), "kiriman ke-%d harus lolos" % (i + 1)
            )
        self.assertTrue(self.Throttle.check_and_count(self.ip, 3))

    def test_refusal_does_not_extend_the_penalty(self):
        """Percobaan yang ditolak tidak menambah jejak.

        Kalau ia menambah, penyerang bisa memperpanjang hukumannya sendiri tanpa
        batas — dan lebih penting, penghitungnya menjadi tempat menulis tanpa batas
        atas perintah orang anonim.
        """
        for _ in range(2):
            self.Throttle.check_and_count(self.ip, 2)
        self.Throttle.check_and_count(self.ip, 2)
        self.env.cr.execute(
            "SELECT count(*) FROM onboarding_intake_throttle WHERE ip_hash = %s", (self.ip,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], 2)

    def test_zero_limit_disables(self):
        self.assertFalse(self.Throttle.check_and_count(self.ip, 0))

    def test_counter_is_in_postgres_not_in_process_memory(self):
        self.Throttle.check_and_count(self.ip, 5)
        self.env.cr.execute(
            "SELECT count(*) FROM onboarding_intake_throttle WHERE ip_hash = %s", (self.ip,)
        )
        self.assertEqual(self.env.cr.fetchone()[0], 1)


@tagged("post_install", "-at_install", "custom_onboarding_journey")
class TestSubmissionProjection(TransactionCase):
    def test_projection_is_filled_on_create(self):
        payload = {
            "company_name": "PT Contoh",
            "partner_name": "Budi",
            "contact_email": "budi@contoh.invalid",
            "consent_given": True,
            "source": "uji",
        }
        rec = self.env["onboarding.public.submission"].create(
            {"raw_payload_json": json.dumps(payload)}
        )
        self.assertEqual(rec.company_name, "PT Contoh")
        self.assertEqual(rec.contact_email, "budi@contoh.invalid")
        self.assertTrue(rec.consent_given)
        self.assertGreater(rec.payload_bytes, 0)

    def test_contact_email_falls_back_to_partner_email(self):
        rec = self.env["onboarding.public.submission"].create(
            {"raw_payload_json": json.dumps({"partner_email": "a@contoh.invalid"})}
        )
        self.assertEqual(rec.contact_email, "a@contoh.invalid")

    def test_malformed_payload_does_not_break_create(self):
        rec = self.env["onboarding.public.submission"].create({"raw_payload_json": "{bukan json"})
        self.assertFalse(rec.company_name)

    def test_overview_view_hides_the_raw_payload(self):
        """View untuk hub-portal tidak boleh memuat payload mentah atau pengenal pajak."""
        self.env.cr.execute(
            """
            SELECT column_name FROM information_schema.columns
             WHERE table_schema = 'onboarding'
               AND table_name = 'public_submission_overview'
            """
        )
        cols = {r[0] for r in self.env.cr.fetchall()}
        self.assertTrue(cols, "view onboarding.public_submission_overview tidak ada")
        for forbidden in ("raw_payload_json", "npwp", "bank_name", "bank_account", "source_ip_hash"):
            self.assertNotIn(forbidden, cols)
        for expected in ("company_name", "contact_email", "status", "submitted_at"):
            self.assertIn(expected, cols)
