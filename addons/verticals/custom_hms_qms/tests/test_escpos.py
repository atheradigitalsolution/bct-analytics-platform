# -*- coding: utf-8 -*-
"""The ESC/POS builder emits bytes no library validates for us."""
from odoo.tests import TransactionCase, tagged

from ..tools.escpos import CUT_PARTIAL, INIT, SIZE_TRIPLE, EscposBuilder


@tagged("post_install", "-at_install", "hms")
class TestEscpos(TransactionCase):
    def test_output_starts_with_the_initialise_command(self):
        self.assertTrue(EscposBuilder().build().startswith(INIT))

    def test_big_text_uses_the_triple_size_command(self):
        self.assertIn(SIZE_TRIPLE, EscposBuilder().big("A-012").build())

    def test_cut_is_the_last_command(self):
        self.assertTrue(EscposBuilder().center("x").cut().build().endswith(CUT_PARTIAL))

    def test_columns_pad_to_the_configured_width(self):
        out = EscposBuilder(width=32).columns("Estimasi", "15 menit").build()
        line = [p for p in out.split(b"\n") if b"Estimasi" in p][0]
        printable = line.split(b"\x1b")[-1].lstrip(b"a\x00")
        self.assertEqual(len(printable.replace(b"\x1d!\x00", b"")), 32)

    def test_non_ascii_is_replaced_rather_than_crashing(self):
        """A thermal printer speaks one code page; an em dash must not jam it."""
        out = EscposBuilder().center("Antrean — poli anak").build()
        self.assertIn(b"Antrean", out)

    def test_barcode_uses_code128_subset_b(self):
        out = EscposBuilder().barcode("A-012").build()
        self.assertIn(b"{B", out)
        self.assertIn(b"A-012", out)

    def test_qr_payload_is_embedded(self):
        out = EscposBuilder().qr("42|token").build()
        self.assertIn(b"42|token", out)

    def test_58mm_and_80mm_differ_in_line_width(self):
        narrow = EscposBuilder(width=32).line().build()
        wide = EscposBuilder(width=48).line().build()
        self.assertLess(len(narrow), len(wide))
