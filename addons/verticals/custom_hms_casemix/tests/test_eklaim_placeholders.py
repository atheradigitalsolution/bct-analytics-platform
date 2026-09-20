# -*- coding: utf-8 -*-
"""Bukti bahwa tidak ada satu pun enumerasi E-Klaim yang dikarang.

Tes ini menjaga sebuah *ketiadaan*, dan ketiadaan adalah hal yang paling
mudah hilang tanpa disadari: seseorang yang ingin "melengkapi" modul akan
menambahkan daftar ``jenis_rawat`` dari blog dalam satu commit yang terlihat
membantu. Tes di bawah akan gagal saat itu terjadi.
"""
import pathlib

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import CasemixCase

MODULE_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Kata kunci payload/enumerasi E-Klaim. Kemunculannya di dalam KODE (bukan di
# dalam teks penjelasan) berarti seseorang mulai menebak.
FORBIDDEN_TOKENS = [
    "set_claim_data", "new_claim", "reedit_claim", "send_claim",
    "ws.php", "AES-256", "aes_256", "grouper_stage",
]


@tagged("post_install", "-at_install", "hms")
class TestEklaimPlaceholdersAreEmpty(CasemixCase):
    def test_the_code_master_ships_empty(self):
        """Master yang diimpor, bukan master yang dikarang."""
        self.assertEqual(
            self.env["hms.eklaim.code"].search_count([]), 0,
            "Master kode E-Klaim harus kosong sampai manual resmi diimpor.",
        )

    def test_the_config_ships_without_guessed_values(self):
        config = self.env["hms.eklaim.config"].get_config()
        self.assertFalse(config.base_url)
        self.assertFalse(config.kode_tarif)
        self.assertFalse(config.payor_id)
        self.assertFalse(config.default_coder_nik)

    def test_the_config_says_out_loud_that_it_is_not_ready(self):
        config = self.env["hms.eklaim.config"].get_config()
        self.assertIn("Belum siap", config.readiness_note)
        self.assertIn("manual resmi", config.readiness_note)

    def test_the_grouper_mode_is_read_from_hospital_settings(self):
        settings = self.env["hms.settings"].get_settings()
        settings.grouper_mode = "idrg"
        config = self.env["hms.eklaim.config"].get_config()
        config.invalidate_recordset()
        self.assertIn("iDRG", config.grouper_mode)

    def test_the_category_field_is_free_text_not_a_guessed_selection(self):
        """Selection dengan kunci tebakan akan menuntut migrasi data klaim."""
        field = self.env["hms.eklaim.code"]._fields["category"]
        self.assertEqual(field.type, "char")
        code_field = self.env["hms.eklaim.code"]._fields["code"]
        self.assertEqual(code_field.type, "char")

    def test_no_claim_field_carries_a_guessed_eklaim_enumeration(self):
        """Tidak ada Selection di hms.claim yang berisi kunci E-Klaim.

        Enumerasi yang dilarang ditebak: jenis_rawat, cara_masuk,
        discharge_status, kode_tarif, payor_id. `care_type` di hms.claim
        memakai kunci Inggris (outpatient/inpatient) justru supaya tidak
        tertukar dengan `jenis_rawat` milik E-Klaim.
        """
        forbidden_keys = {"1", "2", "3", "rj", "ri", "rawat_jalan", "rawat_inap"}
        claim_fields = self.env["hms.claim"]._fields
        for name in ("care_type", "kind"):
            keys = {k for k, _ in claim_fields[name].selection}
            self.assertFalse(
                keys & forbidden_keys,
                f"{name} memakai kunci yang menyerupai enumerasi E-Klaim: {keys}",
            )

    def test_the_module_contains_no_eklaim_payload_code(self):
        """Pemindaian sumber: kata kunci payload hanya boleh ada di penjelasan."""
        offenders = []
        for path in MODULE_ROOT.rglob("*.py"):
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith("*"):
                    continue
                for token in FORBIDDEN_TOKENS:
                    if token in line and not _inside_prose(text, line):
                        offenders.append(f"{path.name}:{line_no}: {stripped[:80]}")
        self.assertFalse(
            offenders,
            "Modul ini tidak boleh memuat payload/enkripsi E-Klaim:\n"
            + "\n".join(offenders),
        )

    def test_nik_length_is_still_validated(self):
        config = self.env["hms.eklaim.config"].get_config()
        with self.assertRaises(ValidationError):
            config.write({"default_coder_nik": "123"})


def _inside_prose(text, line):
    """True bila baris ini berada di dalam docstring penjelasan.

    Penjelasan tentang apa yang SENGAJA tidak dibangun harus boleh menyebut
    nama fungsinya; yang dilarang adalah kodenya. Pendekatannya kasar dan
    cukup: hitung tanda kutip tiga sebelum baris tersebut.
    """
    index = text.find(line)
    if index < 0:
        return False
    return text.count('"""', 0, index) % 2 == 1
