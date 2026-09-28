# -*- coding: utf-8 -*-
"""Membaca `ir.config_parameter` tanpa mempercayai isinya.

Lewat `get_param` yang publik hanya ada TIGA keadaan yang dapat diamati:

    yang teramati              contoh                    hasil
    bawaan dikembalikan        kunci tidak ada, ATAU     default
                               ada tapi berisi ''
    nilai ada & terbaca        "12.5"                    12.5
    nilai ada & TIDAK terbaca  "lima"                    ValueError

Baris pertama menggabungkan dua hal yang berbeda, dan penggabungan itu
terjadi di luar jangkauan kita. `ir_config_parameter.py:69` berbunyi:

    return self._get_param(key) or default

`_get_param` memang membedakan `''` dari `None`, tetapi `or default`
menghapus pembedaan itu sebelum nilainya sampai ke pemanggil. JANGAN
memanggil `_get_param` langsung demi mendapatkan pembedaan itu kembali: ia
API privat, dan `check_access('read')` justru berada pada `get_param` yang
publik -- melewatinya berarti membaca parameter sistem tanpa pemeriksaan
hak akses.

Versi pertama docstring ini mencantumkan "ada tapi kosong" sebagai mode
tersendiri, membandingkannya dengan `os.environ.get` yang memang
membedakannya. Perbandingan itu benar untuk environment dan menyesatkan di
sini: ia menjanjikan pembedaan yang kode ini tidak akan pernah lihat.

IMPLIKASI PRAKTIS: mengosongkan parameter TIDAK mematikan apa pun. Parameter
yang di-set ke string kosong terbaca sebagai bawaannya. Untuk mematikan
sesuatu, pakai nilai eksplisit ("0", "false") atau hapus recordnya --
jangan kosongkan isinya lalu berharap.

Bahaya yang tersisa adalah baris ketiga. `get_param(key) or 0` menangani dua
baris pertama dan melewatkan yang ketiga: nilainya diserahkan ke `float()`,
yang melempar ValueError -- dan di batas API itu jatuh ke `except Exception`
lalu menjadi 500 "kesalahan sistem, hubungi administrator". Administratornya
disuruh menghubungi dirinya sendiri tentang nilai yang ia ketik.

Parameter ini dapat disunting tangan di Pengaturan > Teknis > Parameter
Sistem, jadi salah ketik manusia adalah jalur nyata bagi siapa pun di
`base.group_system`, bukan hipotesis.

Nilai buruk jatuh ke bawaan, dan mengatakannya. Peringatannya menyebut kunci
DAN nilai yang ditemukan, karena "ada parameter yang salah di suatu tempat"
tidak dapat ditindaklanjuti siapa pun. Diam akan lebih buruk daripada crash
yang digantikannya: crash setidaknya menunjuk ke suatu arah.
"""
import logging

_logger = logging.getLogger(__name__)


def config_float(env, key, default=0.0):
    """Return a float parameter, falling back when it cannot be read.

    The fallback is the caller's `default` and nothing cleverer. For staleness
    checks that means 0.0 -- "treat the cache as expired" -- which fails
    toward doing the work again rather than toward serving something stale
    forever.
    """
    raw = env["ir.config_parameter"].sudo().get_param(key)
    # `get_param` returns False for a missing key, not None -- and float(False)
    # is 0.0, which sails through every guard and every conversion without a
    # word. Checking `is False` explicitly rather than falsiness, because the
    # string "0" is a perfectly good value.
    if raw is None or raw is False or not str(raw).strip():
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        _logger.warning(
            "Parameter sistem %s berisi nilai yang tidak dapat dibaca sebagai "
            "angka: %r. Nilai bawaan %r dipakai. Perbaiki di Pengaturan > "
            "Teknis > Parameter Sistem.",
            key, raw, default,
        )
        return default
