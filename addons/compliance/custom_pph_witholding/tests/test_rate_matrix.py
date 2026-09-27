# -*- coding: utf-8 -*-
"""Statutory regression harness for the seeded PPh rate matrix.

Written before the consolidation of the two withholding engines, so that any
later move has a fixed table of expected numbers to be judged against rather
than "it still runs". Each case names the regulation it comes from; a change
here should be a regulation change, not a refactor.

The gross amounts are round figures on purpose - the arithmetic under test is
the rate and the rounding, not the input.
"""

from odoo.tests import TransactionCase, tagged

#: (pph_type, service_category, gross, expected_with_npwp, expected_without_npwp, note)
STATUTORY_CASES = [
    # --- PPh 23: 100% higher without NPWP (UU PPh Pasal 23 ayat (1a)) ------
    ("23", "general", 10_000_000, 200_000, 400_000, "jasa lain 2% / 4%"),
    ("23", "sewa", 5_000_000, 100_000, 200_000, "sewa harta selain tanah-bangunan"),
    ("23", "jasa_teknik", 7_500_000, 150_000, 300_000, "jasa teknik"),
    ("23", "manajemen", 12_000_000, 240_000, 480_000, "jasa manajemen"),
    ("23", "konsultan", 3_300_000, 66_000, 132_000, "jasa konsultan"),
    ("23", "dividen", 100_000_000, 15_000_000, 30_000_000, "dividen ke WP badan 15%"),
    ("23", "bunga", 50_000_000, 7_500_000, 15_000_000, "bunga 15%"),
    ("23", "royalti", 25_000_000, 3_750_000, 7_500_000, "royalti 15%"),
    ("23", "hadiah", 8_000_000, 1_200_000, 2_400_000, "hadiah/penghargaan 15%"),
    # --- PPh 4(2): FINAL, so no NPWP surcharge exists ---------------------
    ("4_2", "sewa_tanah_bangunan", 60_000_000, 6_000_000, 6_000_000, "PP 34/2017, 10% final"),
    ("4_2", "konstruksi_pelaksana_kecil", 200_000_000, 3_500_000, 3_500_000, "PP 9/2022, 1,75%"),
    ("4_2", "konstruksi_pelaksana_menengah_besar", 200_000_000, 5_300_000, 5_300_000, "PP 9/2022, 2,65%"),
    ("4_2", "konstruksi_pelaksana_tanpa_sertifikat", 200_000_000, 8_000_000, 8_000_000, "PP 9/2022, 4%"),
    ("4_2", "konstruksi_perencana_pengawas", 100_000_000, 3_500_000, 3_500_000, "PP 9/2022, 3,5%"),
    ("4_2", "konstruksi_perencana_tanpa_sertifikat", 100_000_000, 6_000_000, 6_000_000, "PP 9/2022, 6%"),
    ("4_2", "bunga_deposito", 10_000_000, 2_000_000, 2_000_000, "PP 123/2015, 20% final"),
    ("4_2", "dividen_orang_pribadi", 40_000_000, 4_000_000, 4_000_000, "PP 19/2009, 10% final"),
    ("4_2", "pengalihan_tanah_bangunan", 800_000_000, 20_000_000, 20_000_000, "PP 34/2016, 2,5%"),
    ("4_2", "hadiah_undian", 20_000_000, 5_000_000, 5_000_000, "PP 132/2000, 25% final"),
    # --- PPh 15: deemed profit, final ------------------------------------
    ("15", "pelayaran_dalam_negeri", 500_000_000, 6_000_000, 6_000_000, "KMK 416/1996, 1,2%"),
    ("15", "penerbangan_dalam_negeri", 500_000_000, 9_000_000, 9_000_000, "KMK 475/1996, 1,8%"),
    ("15", "pelayaran_penerbangan_luar_negeri", 500_000_000, 13_200_000, 13_200_000, "KMK 417/1996, 2,64%"),
    # --- PPh 22: 100% higher without NPWP (Pasal 22 ayat (3)) -------------
    ("22", "general", 40_000_000, 600_000, 1_200_000, "PMK 34/2017, 1,5% / 3%"),
    # --- PPh 26: 20%, treaty rate is a per-partner decision ---------------
    ("26", "general", 30_000_000, 6_000_000, 6_000_000, "UU PPh Pasal 26, 20%"),
    # --- PPh 21 non-employee: 20% higher without NPWP, NOT 100% -----------
    ("21", "bukan_pegawai", 10_000_000, 250_000, 300_000, "PP 58/2023, 2,5% / 3,0%"),
]


@tagged("post_install", "-at_install", "pph")
class TestStatutoryRateMatrix(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.engine = cls.env["custom.witholding.engine"]
        Partner = cls.env["res.partner"]
        cls.with_npwp = Partner.create(
            {"name": "PT Ber-NPWP (uji)", "vat": "0123456789012345"}
        )
        cls.without_npwp = Partner.create({"name": "CV Tanpa NPWP (uji)", "vat": False})
        cls.date = "2026-06-30"

    def _withheld(self, partner, pph_type, category, gross):
        return self.engine.compute(
            partner=partner,
            amount=gross,
            pph_type=pph_type,
            date=self.date,
            service_category=category,
        )["withheld"]

    def test_the_registry_is_not_empty(self):
        """The failure this whole harness exists to catch.

        An empty registry makes compute() return 0 for everything, silently.
        A suite that only checked individual rates would pass that state as
        happily as it passes a correct one, because 0 is what it computes.
        """
        rates = self.env["custom.witholding.rate"].search([])
        self.assertTrue(rates, "the PPh rate registry must be seeded")
        self.assertGreaterEqual(
            len(rates), 20, "the seeded matrix should cover 23 / 4(2) / 15 / 22 / 26 / 21"
        )

    def test_statutory_amounts(self):
        for pph_type, category, gross, expect_npwp, expect_no_npwp, note in STATUTORY_CASES:
            with self.subTest(pph=pph_type, category=category):
                got = self._withheld(self.with_npwp, pph_type, category, gross)
                self.assertEqual(
                    got, expect_npwp,
                    "PPh %s / %s (%s), ber-NPWP: expected %s, got %s"
                    % (pph_type, category, note, expect_npwp, got),
                )
                got = self._withheld(self.without_npwp, pph_type, category, gross)
                self.assertEqual(
                    got, expect_no_npwp,
                    "PPh %s / %s (%s), tanpa NPWP: expected %s, got %s"
                    % (pph_type, category, note, expect_no_npwp, got),
                )

    def test_final_regimes_carry_no_npwp_surcharge(self):
        """PPh 4(2) and 15 are final: a punitive rate would be invented law."""
        rates = self.env["custom.witholding.rate"].search([("pph_type", "in", ["4_2", "15"])])
        self.assertTrue(rates)
        for rate in rates:
            self.assertEqual(
                rate.with_npwp_rate, rate.without_npwp_rate,
                "%s is a final regime; it has no without-NPWP surcharge" % rate.name,
            )

    def test_pph23_surcharge_is_exactly_double(self):
        """UU PPh Pasal 23 ayat (1a): 100% higher, not an arbitrary penalty."""
        rates = self.env["custom.witholding.rate"].search([("pph_type", "=", "23")])
        self.assertTrue(rates)
        for rate in rates:
            self.assertAlmostEqual(
                rate.without_npwp_rate, rate.with_npwp_rate * 2, places=4,
                msg="%s: PPh 23 without NPWP must be exactly double" % rate.name,
            )

    def test_pph21_surcharge_is_twenty_percent_higher(self):
        """UU PPh Pasal 21 ayat (5a): 20% higher, NOT doubled like PPh 23."""
        rates = self.env["custom.witholding.rate"].search([("pph_type", "=", "21")])
        self.assertTrue(rates)
        for rate in rates:
            self.assertAlmostEqual(
                rate.without_npwp_rate, rate.with_npwp_rate * 1.2, places=4,
                msg="%s: PPh 21 without NPWP is 20%% higher, not double" % rate.name,
            )

    def test_unknown_category_falls_back_to_general(self):
        """A category nobody seeded must not silently withhold nothing."""
        got = self._withheld(self.with_npwp, "23", "kategori_yang_tidak_ada", 10_000_000)
        self.assertEqual(got, 200_000, "unknown PPh 23 category should fall back to `general` (2%)")

    def test_rate_lookup_respects_the_effective_date(self):
        """A rate that is not yet in force must not be applied."""
        future = self.env["custom.witholding.rate"].create(
            {
                "pph_type": "23",
                "service_category": "general",
                "with_npwp_rate": 9.0,
                "without_npwp_rate": 18.0,
                "effective_date_from": "2099-01-01",
            }
        )
        self.assertTrue(future)
        self.assertEqual(
            self._withheld(self.with_npwp, "23", "general", 10_000_000),
            200_000,
            "a 2099 rate must not apply to a 2026 transaction",
        )

    def test_every_seeded_rate_cites_its_regulation(self):
        """A rate without a citation cannot be audited, only trusted."""
        uncited = self.env["custom.witholding.rate"].search([]).filtered(
            lambda r: not (r.legal_basis or "").strip()
        )
        self.assertFalse(
            uncited, "rates without a legal_basis: %s" % uncited.mapped("name")
        )
