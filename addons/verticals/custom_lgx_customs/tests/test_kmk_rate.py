# -*- coding: utf-8 -*-
"""Butir A26 — kurs KMK sebagai master, bukan angka yang diketik tanpa pembanding.

`fx_rate_tax` adalah pengali SETIAP pungutan impor. Nilai Pabean, Bea Masuk,
PPN Impor, PPnBM, dan PPh 22 semuanya berskala linear terhadapnya. Satu nol
yang kelebihan mengalikan seluruhnya sepuluh kali — dan tidak ada satu pun
angka lain di dokumen yang akan terlihat ganjil, karena semuanya ikut bergerak,
konsisten dan salah.

Itu sebabnya kesalahan kurs adalah jenis yang bertahan sampai pemeriksaan:
tidak ada yang tidak cocok dengan apa pun.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKmkRate(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.usd = cls.env.ref("base.USD")
        cls.customer = cls.env["res.partner"].create({
            "name": "PT Importir KMK", "vat": "9911223344556677",
            "lgx_nib": "1112223334445", "lgx_customs_access_type": "importer",
        })
        cls.ppjk = cls.env["res.partner"].create({
            "name": "PT PPJK KMK", "lgx_is_ppjk": True, "vat": "9900112233445599",
        })
        cls.expert = cls.env["lgx.customs.expert"].create({
            "name": "Ahli KMK", "certificate_no": "AK-KMK-0001",
            "certificate_expiry": "2030-01-01", "ppjk_partner_id": cls.ppjk.id,
        })
        cls.job = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": cls.customer.id, "etd": "2026-09-01",
        })
        cls.office = cls.env.ref("custom_lgx_base.office_040300")
        # Periode KMK: Rabu 2026-09-16 sampai Selasa 2026-09-22.
        cls.kmk = cls.env["lgx.kmk.rate"].create({
            "kmk_number": "KMK-99/KM.10/2026",
            "currency_id": cls.usd.id,
            "rate": 15_912.0,
            "valid_from": "2026-09-16",
            "valid_to": "2026-09-22",
        })

    def _declaration(self, **kwargs):
        values = {
            "job_id": self.job.id,
            "doc_type": "bc20_pib",
            "principal_id": self.customer.id,
            "ppjk_id": self.ppjk.id,
            "customs_expert_id": self.expert.id,
            "customs_office_id": self.office.id,
            "currency_id": self.usd.id,
            "registration_date": "2026-09-18",
            "fx_rate_tax": 15_912.0,
            "line_ids": [(0, 0, {
                "hs_code_id": self.env.ref("custom_lgx_customs.hs_84713020").id,
                "description": "Laptop", "quantity": 10, "customs_value": 5000.0,
            })],
        }
        values.update(kwargs)
        return self.env["lgx.customs.declaration"].create(values)

    # --- master -------------------------------------------------------------
    def test_lookup_uses_the_document_date_not_today(self):
        """Deklarasi yang dibuka kembali harus tetap menunjukkan kurs saat itu.

        Kalau tidak, rekonsiliasi terhadap SPPB yang sudah terbit tidak akan
        pernah cocok lagi.
        """
        Kmk = self.env["lgx.kmk.rate"]
        self.assertEqual(Kmk.lgx_find(self.usd, "2026-09-18"), self.kmk)
        self.assertEqual(Kmk.lgx_find(self.usd, "2026-09-16"), self.kmk)
        self.assertEqual(Kmk.lgx_find(self.usd, "2026-09-22"), self.kmk)
        self.assertFalse(
            Kmk.lgx_find(self.usd, "2026-09-23"),
            "Periode KMK berakhir Selasa; Rabu sudah periode berikutnya.",
        )
        self.assertFalse(Kmk.lgx_find(self.usd, "2026-09-15"))

    # --- deklarasi ----------------------------------------------------------
    def test_matching_rate_is_ok(self):
        declaration = self._declaration()
        self.assertEqual(declaration.fx_rate_kmk_status, "ok")
        self.assertEqual(declaration.fx_rate_kmk_id, self.kmk)

    def test_rate_outside_any_recorded_period_is_unknown_not_ok(self):
        """Tanpa pembanding, kurs dinyatakan tidak dapat diverifikasi.

        Melaporkannya "cocok" karena tidak ada pembanding adalah cara tabel KMK
        tidak pernah diisi.
        """
        declaration = self._declaration(registration_date="2026-10-15")
        self.assertEqual(declaration.fx_rate_kmk_status, "unknown")
        self.assertNotEqual(declaration.fx_rate_kmk_status, "ok")
        self.assertIn("fiskal.kemenkeu.go.id", declaration.fx_rate_kmk_message)

    def test_unknown_does_not_block_submission_but_leaves_a_trace(self):
        """Memblokir karena master belum diisi akan menghentikan operasi.

        Yang dituntut bukan kesempurnaan data, melainkan jejak: pesan tercatat
        di chatter sehingga pemeriksaan tiga bulan kemudian punya titik mula.
        """
        declaration = self._declaration(registration_date="2026-10-15")
        sebelum = len(declaration.message_ids)
        declaration.action_submit()
        self.assertEqual(declaration.state, "submitted")
        self.assertGreater(len(declaration.message_ids), sebelum)

    def test_mismatched_rate_blocks_submission_until_a_reason_is_given(self):
        """Selisih kurs tidak boleh lewat tanpa jejak.

        Angka 159120 di bawah adalah kesalahan ketik yang paling mungkin: satu
        nol kelebihan. Seluruh pungutan menjadi sepuluh kali lipat, dan setiap
        angka turunannya tetap konsisten satu sama lain.
        """
        declaration = self._declaration(fx_rate_tax=159_120.0)
        self.assertEqual(declaration.fx_rate_kmk_status, "mismatch")
        self.assertIn("KMK-99/KM.10/2026", declaration.fx_rate_kmk_message)

        with self.assertRaises(UserError) as ctx:
            declaration.action_submit()
        self.assertIn("kurs", str(ctx.exception).lower())

        declaration.fx_rate_override_reason = (
            "Kurs sesuai KMK koreksi yang terbit belakangan; nomor menyusul."
        )
        declaration.action_submit()
        self.assertEqual(declaration.state, "submitted")

    def test_company_currency_needs_no_kmk(self):
        """Kontrol positif: penjaga tidak boleh rakus.

        Deklarasi dalam rupiah tidak punya kurs untuk diperiksa, dan menuntut
        KMK untuknya akan memblokir pekerjaan yang benar.
        """
        declaration = self._declaration(
            currency_id=self.env.company.currency_id.id, fx_rate_tax=1.0)
        self.assertEqual(declaration.fx_rate_kmk_status, "ok")
        declaration.action_submit()
        self.assertEqual(declaration.state, "submitted")
