# -*- coding: utf-8 -*-
"""Jebakan Odoo 19 yang ditegakkan, bukan sekadar didokumentasikan.

Dokumen jebakan di MODULE_KNOWLEDGE.md tidak berada di jalur yang dilewati saat
kesalahan hendak dibuat. Saya sudah membaca catatan `stock.move.name` di sana
dan tetap membayarnya lagi — karena saya membacanya saat MENCATAT, bukan saat
MENULIS FIXTURE.

Yang berada di jalur itu adalah suite tes. Karena itu setiap jebakan yang dapat
dideteksi secara statis diubah menjadi tes yang gagal dengan pesan yang MENUNJUK
ke dokumennya. Gagasan ini datang dari sesi SIMRS, dan berlaku untuk seluruh
temuan kami hari ini: yang mengajari bukan catatannya, melainkan kegagalan yang
datang tepat pada saat kesalahan dibuat.

Tes ini memindai SELURUH vertikal LGX, bukan hanya modul ini — jebakannya tidak
mengenal batas modul.
"""
import io
import os
import re
from glob import glob

from odoo.modules.module import get_module_path
from odoo.tests import TransactionCase, tagged

DOK = "addons/verticals/custom_lgx_base/MODULE_KNOWLEDGE.md, bagian 'Jebakan Odoo 19'"


def _akar():
    return os.path.dirname(get_module_path("custom_lgx_base"))


def _berkas(pola):
    """Seluruh berkas vertikal LGX KECUALI berkas ini sendiri.

    Pemindai yang memuat pola-polanya sebagai literal akan menemukan dirinya
    sendiri dan melaporkan pelanggaran yang justru merupakan definisinya.
    """
    ini = os.path.abspath(__file__).replace(".pyc", ".py")
    return [p for p in sorted(glob(os.path.join(_akar(), "custom_lgx_*", "**", pola),
                                   recursive=True))
            if os.path.abspath(p) != ini]


def _baca(path):
    return io.open(path, encoding="utf-8").read()


def _ringkas(path):
    return path.replace(_akar() + os.sep, "")


@tagged("post_install", "-at_install")
class TestOdoo19Traps(TransactionCase):

    # --- constraint ---------------------------------------------------------
    def test_no_legacy_sql_constraints(self):
        """`_sql_constraints` diterima tanpa keluhan dan tidak membuat apa pun."""
        temuan = [_ringkas(p) for p in _berkas("*.py") if "_sql_constraints" in _baca(p)]
        self.assertFalse(temuan, (
            "Odoo 19 hanya menulis WARNING untuk `_sql_constraints` lalu jalan terus; "
            "constraint-nya TIDAK PERNAH dibuat, dan modul terpasang 'sukses' "
            "sementara yang Anda kira dijaga tidak dijaga. Pakai `models.Constraint`. "
            "Berkas: %s. Lihat %s." % (", ".join(temuan), DOK)))

    def test_every_declared_constraint_exists_in_postgres(self):
        """Rekonsiliasi dua arah, dijalankan tiap suite — bukan sekali lalu dilupakan.

        Inilah pemeriksaan yang paling berharga untuk diotomatiskan: constraint
        yang gagal dibuat saat upgrade tidak menghasilkan galat apa pun, dan
        satu-satunya cara mengetahuinya adalah bertanya ke basis datanya.
        """
        diharapkan = self._constraint_dideklarasikan()
        self.assertTrue(diharapkan, "Parser tidak menemukan satu pun constraint — "
                                    "itu sendiri sudah salah.")
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
            WHERE contype IN ('c', 'u')
        """)
        ada = {r[0] for r in self.env.cr.fetchall()}

        hilang = sorted(n for n in diharapkan if n not in ada)
        self.assertFalse(hilang, (
            "Constraint ini dideklarasikan di kode tetapi TIDAK ADA di Postgres: %s.\n"
            "Ia gagal dibuat tanpa galat apa pun. Lihat %s." % (", ".join(hilang), DOK)))

    def test_no_orphan_lgx_constraints_in_postgres(self):
        """Arah sebaliknya: ada di Postgres, tidak lagi dideklarasikan.

        Tidak berbahaya seperti yang hilang, tetapi ia satu-satunya petunjuk
        bahwa sesuatu dulu dijaga dan sekarang tidak, tanpa ada yang memutuskan
        begitu.
        """
        diharapkan = self._constraint_dideklarasikan()
        self.env.cr.execute("""
            SELECT conname FROM pg_constraint
            WHERE contype IN ('c', 'u')
              AND conrelid::regclass::text LIKE 'lgx\\_%'
        """)
        ada = {r[0] for r in self.env.cr.fetchall()}
        yatim = sorted(n for n in ada if n not in diharapkan)
        self.assertFalse(yatim, (
            "Constraint ini ada di Postgres tetapi tidak lagi dideklarasikan: %s.\n"
            "Kemungkinan sisa dari model yang di-rename atau dihapus. Lihat %s."
            % (", ".join(yatim), DOK)))

    def _constraint_dideklarasikan(self):
        """Nama yang SEHARUSNYA ada: <tabel>_<atribut tanpa garis bawah awal>."""
        kelas = re.compile(r'^class\s+\w+\(models\.(?:Model|TransientModel|AbstractModel)\):', re.M)
        hasil = set()
        for path in _berkas("*.py"):
            if os.sep + "tests" + os.sep in path:
                continue
            src = _baca(path)
            batas = [m.start() for m in kelas.finditer(src)] + [len(src)]
            for i in range(len(batas) - 1):
                blok = src[batas[i]:batas[i + 1]]
                if "_auto = False" in blok:
                    continue
                m = re.search(r'_name\s*=\s*"([^"]+)"', blok) or \
                    re.search(r'_inherit\s*=\s*"([^"]+)"', blok)
                if not m:
                    continue
                tabel = m.group(1).replace(".", "_")
                for c in re.finditer(r'^\s+_([a-z0-9_]+)\s*=\s*models\.Constraint\(', blok, re.M):
                    hasil.add("%s_%s" % (tabel, c.group(1)))
        return hasil

    # --- field & API yang dihapus -------------------------------------------
    def test_no_removed_field_names(self):
        """Field yang dihapus Odoo 19, yang galatnya terbaca seperti salah fixture."""
        # Pola dipersempit ke PEMAKAIAN, bukan penyebutan. Docstring yang
        # menjelaskan jebakan ini justru harus ada di kode — menandainya sebagai
        # pelanggaran akan membuat orang menghapus penjelasan yang benar.
        dihapus = {
            r'env\[[\'"]product\.packaging[\'"]\]':
                "product.packaging dihapus di Odoo 19",
            r'env\[[\'"]stock\.valuation\.layer[\'"]\]':
                "stock.valuation.layer dihapus -> pakai account.move.line",
            r'env\[[\'"]uom\.category[\'"]\]':
                "uom.category dihapus -> UoM berjenjang lewat relative_factor",
            r'[\'"]property_valuation[\'"]\s*:\s*[\'"]manual_periodic[\'"]':
                "property_valuation memakai 'periodic', bukan 'manual_periodic'",
            r'[\'"]groups_id[\'"]\s*:':
                "res.users.groups_id -> group_ids",
            r'[\'"]name[\'"]\s*:\s*[^,\n]+,?\s*#?\s*$':
                None,  # tidak dipakai; stock.move ditangani terpisah di bawah
        }
        temuan = []
        for path in _berkas("*.py"):
            src = _baca(path)
            for nomor, baris_teks in enumerate(src.splitlines(), start=1):
                if baris_teks.lstrip().startswith("#"):
                    continue
                for pola, pesan in dihapus.items():
                    if pesan is None:
                        continue
                    if re.search(pola, baris_teks):
                        temuan.append("%s:%s — %s" % (_ringkas(path), nomor, pesan))
        self.assertFalse(temuan, (
            "Nama yang sudah dihapus di Odoo 19:\n  %s\nLihat %s."
            % ("\n  ".join(temuan), DOK)))

    # --- view ---------------------------------------------------------------
    def test_no_legacy_view_syntax(self):
        """`<tree>`, `<group>` di dalam `<search>`, `create` pada `<pivot>`."""
        temuan = []
        for path in _berkas("*.xml"):
            src = _baca(path)
            if re.search(r'<tree\b', src):
                temuan.append("%s — <tree> menjadi <list>" % _ringkas(path))
            for cari in re.finditer(r'<search\b.*?</search>', src, re.S):
                if re.search(r'<group\b', cari.group(0)):
                    temuan.append("%s — <group> tidak sah di dalam <search>; "
                                  "pakai <separator/> dan filter datar" % _ringkas(path))
            for cari in re.finditer(r'<pivot\b[^>]*>', src):
                if "create=" in cari.group(0):
                    temuan.append("%s — atribut create tidak sah pada <pivot>" % _ringkas(path))
        self.assertFalse(temuan, (
            "Sintaks view yang tidak lagi sah di Odoo 19:\n  %s\nLihat %s."
            % ("\n  ".join(sorted(set(temuan))), DOK)))

    # --- terjemahan ---------------------------------------------------------
    def test_no_unescaped_percent_in_translated_strings(self):
        """`%` literal di string ber-argumen melempar ValueError menggantikan pesannya.

        Ditemukan dengan cara paling mahal: validasi ekspor jasa 0% melempar
        traceback alih-alih panduan, dan hanya terlihat karena ada tes yang
        menyentuh jalur itu.
        """
        import ast
        sah = set("diouxXeEfFgGcrsa%")
        spec = re.compile(r'%(?:\([^)]*\))?[-+ #0]*[0-9*]*(?:\.[0-9*]+)?[hlL]?(.)', re.S)
        temuan = []
        for path in _berkas("*.py"):
            try:
                pohon = ast.parse(_baca(path))
            except SyntaxError:
                continue
            for node in ast.walk(pohon):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "_"):
                    continue
                if len(node.args) < 2 and not node.keywords:
                    continue
                arg = node.args[0] if node.args else None
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    continue
                for ch in spec.findall(arg.value):
                    if ch not in sah:
                        temuan.append("%s:%s — '%%%s' bukan spesifier sah"
                                      % (_ringkas(path), node.lineno, ch))
                        break
        self.assertFalse(temuan, (
            "String ber-argumen dengan %% literal yang tidak di-escape:\n  %s\n"
            "Tulis %%%% untuk persen literal. Lihat %s." % ("\n  ".join(temuan), DOK)))

    # --- direktori tes yang kosong -------------------------------------------
    def test_every_test_file_is_imported(self):
        """Berkas tes yang ada tetapi tidak diimpor tidak pernah berjalan.

        Bentuk yang bertahan di git dari jebakan "tampak diuji, menjalankan nol".
        Direktori tests/ yang benar-benar KOSONG tidak diuji di sini: git tidak
        melacak direktori kosong, jadi ia hanya ada di mesin yang membuatnya —
        tes yang menggagalkannya akan merah di satu tempat dan hijau di tempat
        lain, dan pemeriksaan yang hasilnya bergantung mesin lebih buruk
        daripada tidak ada.
        """
        temuan = []
        for modul in sorted(glob(os.path.join(_akar(), "custom_lgx_*"))):
            tests = os.path.join(modul, "tests")
            init = os.path.join(tests, "__init__.py")
            if not os.path.exists(init):
                continue
            diimpor = _baca(init)
            for berkas in sorted(glob(os.path.join(tests, "test_*.py"))):
                nama = os.path.basename(berkas)[:-3]
                if ("import %s" % nama) not in diimpor:
                    temuan.append("%s tidak diimpor di %s"
                                  % (_ringkas(berkas), _ringkas(init)))
        self.assertFalse(temuan, (
            "Berkas tes yang tidak pernah dijalankan karena tidak diimpor:\n  %s\n"
            "Lihat %s." % ("\n  ".join(temuan), DOK)))
