# -*- coding: utf-8 -*-
"""Uji rekonsiliasi harga — gerbang utama modul NDI.

Data sampel di ``30-data/02-master-produk.csv`` sudah diverifikasi secara
independen oleh ``30-data/99-verifikasi-aritmetika.py`` (52 produk x 9 tingkat =
468 persamaan, plus jangkar harga produsen SPORA Kementan). Uji ini membalik
arah pembuktian: komponen dimuat ke ``product.template``, lalu ``ndi_hj1``..
``ndi_hj9`` yang dihitung modul dibandingkan dengan kolom ``hj1``..``hj9`` CSV.

Kalau modul dan CSV berbeda, modulnya yang salah.
"""

from decimal import ROUND_HALF_UP, Decimal

from odoo.tests import tagged

from odoo.addons.custom_ndi_master.models.ndi_waterfall import compute_hj_waterfall

from .common import COMPONENT_COLUMNS, NdiSampleCase

#: Toleransi rupiah. CSV dan modul sama-sama membulatkan ke 2 desimal di setiap
#: tingkat, jadi selisih yang sah hanyalah representasi float.
TOLERANCE = 0.01


@tagged("post_install", "-at_install", "ndi")
class TestHjWaterfall(NdiSampleCase):

    def test_hj_matches_sample_csv_for_every_product(self):
        """52 produk x 9 tingkat: ndi_hj* modul == hj* CSV."""
        self.assertEqual(len(self.sample_rows), 52, "Data sampel harus berisi 52 produk.")
        self.assertEqual(len(self.products_by_sku), 52, "Semua 52 produk harus termuat.")

        mismatches = []
        checked = 0
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            for level in range(1, 10):
                expected = float(row["hj%d" % level])
                actual = template["ndi_hj%d" % level]
                checked += 1
                if abs(actual - expected) > TOLERANCE:
                    mismatches.append(
                        "%s HJ%d: modul=%.4f CSV=%.4f selisih=%.4f"
                        % (row["sku"], level, actual, expected, actual - expected)
                    )
        self.assertEqual(checked, 468, "Harus ada 468 persamaan yang diperiksa.")
        self.assertFalse(
            mismatches,
            "Nilai HJ modul menyimpang dari CSV yang sudah diverifikasi:\n  "
            + "\n  ".join(mismatches),
        )

    def test_hj9_equals_hpp_dasar(self):
        """Pasal 13: dasar rantai adalah HPP Dasar apa adanya."""
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            self.assertAlmostEqual(
                template.ndi_hj9,
                template.ndi_hpp_dasar,
                delta=TOLERANCE,
                msg="HJ9 %s harus sama dengan HPP Dasar" % row["sku"],
            )

    def test_hj_is_monotonic_non_increasing_towards_hj9(self):
        """HJ1 >= HJ2 >= ... >= HJ9 selama tiap komponen tidak negatif."""
        for row in self.sample_rows:
            template = self.products_by_sku[row["sku"]]
            ladder = [template["ndi_hj%d" % level] for level in range(1, 10)]
            for higher, lower in zip(ladder, ladder[1:]):
                self.assertGreaterEqual(
                    higher + TOLERANCE,
                    lower,
                    "Urutan HJ1..HJ9 dilanggar pada %s: %r" % (row["sku"], ladder),
                )

    def test_recompute_on_component_change(self):
        """Compute stored benar-benar tergantung komponen, bukan beku di create."""
        template = self.products_by_sku["FG-BRS-01"]
        before = template.ndi_hj1
        template.ndi_margin_het_rp = template.ndi_margin_het_rp + 100.0
        self.assertAlmostEqual(
            template.ndi_hj1,
            before + 100.0,
            delta=TOLERANCE,
            msg="Menaikkan Margin HET Rp 100 harus menaikkan HJ1 Rp 100.",
        )
        self.assertAlmostEqual(
            template.ndi_hj2, before + 100.0 - template.ndi_margin_het_rp, delta=TOLERANCE
        )

    def test_rounding_happens_at_every_tier_not_only_at_the_end(self):
        """Pembulatan per tingkat, bukan sekali di akhir.

        Dibuktikan dengan komponen yang sengaja menghasilkan ekor pecahan pada
        HJ8: menunda pembulatan sampai HJ1 memberi hasil berbeda.
        """
        components = {
            "hpp_dasar": 1000.0,
            "profit_pct": 6.005,
            "risiko_pct": 6.005,
            "pajak_pct": 6.005,
            "ongkir_rp": 0.0,
            "pembulatan_rp": 0.0,
            "insentif_kwartal_rp": 0.0,
            "insentif_bulanan_rp": 0.0,
            "margin_het_rp": 0.0,
        }
        tiered = compute_hj_waterfall(components)

        # Versi yang menunda pembulatan sampai akhir, aritmetika Decimal penuh.
        deferred = Decimal("1000")
        for pct in ("6.005", "6.005", "6.005"):
            deferred = deferred + deferred * Decimal(pct) / Decimal(100)
        deferred = float(deferred.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

        self.assertAlmostEqual(tiered["hj6"], 1191.19, delta=TOLERANCE)
        self.assertAlmostEqual(deferred, 1191.18, delta=TOLERANCE)
        self.assertNotEqual(
            round(tiered["hj6"], 2),
            round(deferred, 2),
            "Kalau kedua urutan pembulatan memberi hasil sama, uji ini tidak "
            "membuktikan apa pun. Pilih komponen lain.",
        )

    def test_component_columns_match_model_fields(self):
        """Nama kolom CSV dan nama field modul tidak boleh berpisah diam-diam."""
        template = self.products_by_sku["FG-BRS-01"]
        for column in COMPONENT_COLUMNS:
            self.assertIn(
                "ndi_%s" % column,
                template._fields,
                "Kolom CSV %s tidak punya field ndi_%s di product.template" % (column, column),
            )
