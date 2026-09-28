# -*- coding: utf-8 -*-
"""Shared plumbing for every /api/v1 endpoint."""
import functools
import hashlib
import json
import linecache
import logging
import os
import re
import time

import jwt
import psycopg2
import werkzeug.exceptions

from odoo import _, fields
from odoo.exceptions import AccessDenied, AccessError, MissingError, UserError, ValidationError
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

API_ROOT = "/api/v1"
SCHEMA_VERSION = "1"
ALGORITHM = "HS256"
ACCESS_TTL_DEFAULT = 900
RATE_LIMIT_PER_MINUTE = 600
PUBLIC_RATE_LIMIT_PER_MINUTE = 60

# Pelanggaran kunci asing. SATU-SATUNYA kode yang boleh dibaca sebagai "klien
# menyebut id yang tidak ada". Constraint bisnis kita sendiri
# (``models.Constraint(...)``) naik lewat jalur psycopg2 yang persis sama
# dengan kode LAIN — 23505 unique, 23514 check, 23502 not-null — dan
# menyebutnya kesalahan klien akan melaporkan "NIK sudah terdaftar" sebagai
# "data tidak ada": salah tentang data yang justru ada.
PG_FOREIGN_KEY_VIOLATION = "23503"

# Direktori controller modul ini. Dipakai sebagai pembeda struktural antara
# ``ValueError`` yang lahir dari konversi nilai payload (yang HANYA terjadi di
# sini) dan ``ValueError`` dari logika bisnis (yang tinggal di ``models/``).
_CONTROLLERS_DIR = os.path.dirname(os.path.abspath(__file__))

# ``body["x"]`` dan ``body.get("x")`` pada baris sumber yang melempar.
_BODY_SUBSCRIPT = re.compile(r"""body(?:\.get)?[\[(]\s*["']([A-Za-z_][A-Za-z0-9_]*)["']""")

# ``DETAIL:  Key (station_id)=(999999) is not present in table "..."``.
# Bentuk INI khusus untuk INSERT/UPDATE yang menyebut baris yang tidak ada.
# 23503 yang lain berbunyi "is still referenced from table ..." — itu
# penghapusan record yang masih dipakai, bukan id hantu, dan pesannya harus
# berbeda.
_FK_ROW_ABSENT = "is not present in table"

# Process-local rate-limit buckets. Deliberately not Redis-backed: with a
# handful of Odoo workers this is close enough to keep a runaway client in
# check, and a shared store would put a network round-trip in front of every
# request. The real protection against abuse is authentication.
_BUCKETS = {}

# Resolved once per worker; an installed language does not disappear at runtime.
_LANG_CHECKED = False
_LANG_AVAILABLE = False


# =============================================================================
# SATU-SATUNYA DAFTAR GRUP
# =============================================================================
# Daftar ini pernah ada dua kali — sekali di `make_access_token` (payload
# token) dan sekali di `auth._user_payload` (respons /me) — dan keduanya
# mengunci prefiks "custom_hms_base.". Akibatnya setiap grup yang lahir di
# modul lain (casemix, rekam medis, keselamatan pasien) tidak pernah muncul
# di token maupun di /me, sehingga menu frontend tidak bisa menyaringnya:
# sebuah kegagalan yang tidak melempar apa pun, hanya menyembunyikan layar.
#
# Bentuknya tuple (modul, nama grup, label pendek) karena kedua konsumen
# memang memakai ejaan yang berbeda dan harus tetap begitu:
#   * token  -> nama grup ("group_hms_coder")     — kontrak yang sudah beredar
#   * /me    -> label pendek ("coder")            — yang dibaca menu Next.js
# Menambah baris di sini menambah nilai pada kedua array sekaligus; konsumen
# yang ada memakai `.includes()` sehingga nilai baru diabaikan dengan aman.
HMS_GROUPS = (
    ("custom_hms_base", "group_hms_registration_user", "registration_user"),
    ("custom_hms_base", "group_hms_registration_manager", "registration_manager"),
    ("custom_hms_base", "group_hms_emr_reader", "emr_reader"),
    ("custom_hms_base", "group_hms_emr_clinician", "emr_clinician"),
    ("custom_hms_base", "group_hms_emr_full", "emr_full"),
    ("custom_hms_base", "group_hms_pharmacy_tech", "pharmacy_tech"),
    ("custom_hms_base", "group_hms_pharmacist", "pharmacist"),
    ("custom_hms_base", "group_hms_diagnostic_user", "diagnostic_user"),
    ("custom_hms_base", "group_hms_diagnostic_verifier", "diagnostic_verifier"),
    ("custom_hms_base", "group_hms_nurse", "nurse"),
    ("custom_hms_base", "group_hms_charge_nurse", "charge_nurse"),
    ("custom_hms_base", "group_hms_cashier", "cashier"),
    ("custom_hms_base", "group_hms_billing_supervisor", "billing_supervisor"),
    ("custom_hms_base", "group_hms_manager", "manager"),
    ("custom_hms_base", "group_hms_admin", "admin"),
    ("custom_hms_casemix", "group_hms_coder", "coder"),
    ("custom_hms_casemix", "group_hms_casemix_verifier", "casemix_verifier"),
    ("custom_hms_medrec", "group_hms_medrec", "medrec"),
    ("custom_hms_medrec", "group_hms_medrec_manager", "medrec_manager"),
    ("custom_hms_safety", "group_hms_patient_safety", "patient_safety"),
)


def user_groups(user, short=False):
    """Grup SIMRS yang dimiliki `user`, dalam ejaan yang diminta pemanggil."""
    return [
        label if short else name
        for module, name, label in HMS_GROUPS
        if user.has_group(f"{module}.{name}")
    ]


def jwt_secret():
    secret = os.environ.get("HMS_JWT_SECRET")
    if not secret:
        raise UserError(
            _("HMS_JWT_SECRET belum disetel. API tidak boleh berjalan tanpa kunci "
              "tanda tangan token.")
        )
    return secret


def access_ttl():
    return int(os.environ.get("HMS_JWT_ACCESS_TTL", ACCESS_TTL_DEFAULT))


# =============================================================================
# PENANDA KREDENSIAL — pembatal token saat sandi/login/akun berubah
# =============================================================================
# JWT berumur pendek tetapi tidak dapat dicabut: mengganti sandi tidak
# menyentuh token yang sudah beredar, jadi token curian tetap sah sampai
# kedaluwarsa. Ganti-sandi adalah tindakan pertama seseorang yang curiga
# akunnya diambil orang, dan sampai sekarang tindakan itu tidak melakukan
# apa-apa terhadap penyerangnya.
#
# Penandanya memakai mekanisme Odoo sendiri, bukan skema karangan:
#   res_users.py:829  _get_session_token_fields() -> {'id','login','password','active'}
#   res_users.py:852  @tools.ormcache('sid')  _compute_session_token(sid)
#
# Kumpulan field itu tepat: hash berubah saat sandi diganti, saat login
# diubah, dan saat akun dinonaktifkan — tiga peristiwa yang memang harus
# membatalkan sesi — dan TIDAK berubah saat nama atau surel disunting, yang
# berarti menyunting profil seorang dokter tidak melogout rumah sakit.
#
# KETERGANTUNGAN API PRIVAT. `_get_session_token_fields` dan
# `_compute_session_token` bukan API publik Odoo. Kalau Odoo 20 mengubah
# kumpulan fieldnya, pembatalan ini berhenti bekerja secara diam-diam —
# tidak ada yang melempar, token lama hanya tetap berlaku. Karena itu
# `test_session_token_fields_still_cover_credentials` mengunci perilakunya
# dan harus gagal keras, bukan diam. Lihat MODULE_KNOWLEDGE.md.
#
# TIDAK di-cache, dan itu keputusan korektness, bukan kelalaian.
#
# `_compute_session_token` di-dekorasi `@tools.ormcache('sid')`. Cache itu
# per proses, dan proses lain hanya tahu harus membuangnya kalau penulisnya
# memanggil `registry.signal_changes()`. Diukur di mesin ini lewat pencacah
# `orm_signaling_default`:
#
#     ganti sandi lewat RPC/UI Odoo   -> 2 -> 3   worker lain DIKABARI
#     ganti sandi lewat `odoo shell`  -> 2 -> 2   worker lain TIDAK dikabari
#
# `signal_changes()` hanya dipanggil di jalur dispatch RPC
# (service/model.py:134,240). Skrip, cron, dan `odoo shell` melewatinya, jadi
# worker HTTP menyimpan penanda basi sampai restart — dan token yang
# seharusnya dicabut tetap berlaku. Pencabutan yang bekerja atau tidak
# tergantung CARA sandinya diganti adalah jaminan yang berubah tanpa
# mengubah namanya.
#
# Jadi penandanya dihitung ulang setiap permintaan, memakai dua primitif
# Odoo yang TIDAK di-cache dan yang menyusun `_compute_session_token`:
# `_session_token_get_values()` + `_session_token_hash_compute()`.
# Diverifikasi menghasilkan hash yang identik. Biayanya 0,309 ms per
# permintaan (1,3 % dari p95 23,2 ms) — dibayar untuk korektness.
#
# KETERGANTUNGAN API PRIVAT, kini tiga nama. Lihat MODULE_KNOWLEDGE.md §10;
# `test_session_token_internals_still_exist` menguncinya.
SESSION_SID_PREFIX = "hms-api-v1"


def credential_marker(user):
    """Hash pendek atas kredensial pengguna, dihitung segar tiap permintaan."""
    account = user.sudo()
    # sid tetap membawa id pengguna: hash-nya harus berbeda antar pengguna
    # walau nilai fieldnya kebetulan mirip.
    sid = "%s:%s" % (SESSION_SID_PREFIX, account.id)
    values = account._session_token_get_values()
    if not values:
        # Pengguna hilang di antara dua kueri: tidak ada kredensial untuk
        # dicocokkan, jadi tidak ada token yang boleh lolos.
        return None
    token = account._session_token_hash_compute(sid, values)
    return hashlib.sha256((token or "").encode()).hexdigest()[:32]


def make_access_token(user):
    """Mint a short-lived access token carrying just enough for UI gating."""
    now = int(time.time())
    groups = user_groups(user)
    practitioner = request.env["hms.practitioner"].sudo().search(
        [("user_id", "=", user.id)], limit=1
    )
    payload = {
        # RFC 7519 requires `sub` to be a string, and PyJWT 2.13 enforces it on
        # decode: an integer here produces a token that encodes fine and can
        # never be verified.
        "sub": str(user.id),
        "name": user.name,
        "iat": now,
        "exp": now + access_ttl(),
        "db": request.env.cr.dbname,
        "groups": groups,
        "practitioner_id": practitioner.id or None,
        "units": practitioner.unit_ids.ids if practitioner else [],
        "stk": credential_marker(user),
    }
    return jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)


def json_response(data, status=200, headers=None):
    payload = json.dumps(data, default=str, ensure_ascii=False)
    all_headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("X-HMS-Schema", SCHEMA_VERSION),
        ("Cache-Control", "no-store"),
    ]
    all_headers.extend(headers or [])
    return Response(payload, status=status, headers=all_headers)


def error_response(code, message, status=400, fields_=None):
    return json_response(
        {"error": {"code": code, "message": message, "fields": fields_ or {}}}, status=status
    )


def rejected(code, message, status=400, fields_=None):
    """Batalkan transaksinya, LALU jawab bahwa permintaannya ditolak.

    KENAPA INI ADA
    --------------
    Handler yang **mengembalikan** sebuah ``Response`` terbaca oleh dispatcher
    Odoo sebagai handler yang sukses: ``service.model.retrying`` menjalankan
    ``cr.flush()`` lalu ``cr.commit()`` sesudahnya. Blok ``except`` di
    ``hms_route`` mengembalikan Response untuk setiap galat bisnis, jadi
    seluruh 123 route menyimpan apa pun yang sempat ter-INSERT sebelum
    exception naik — sambil memberi tahu klien bahwa operasinya ditolak.

    Reproduksinya: ``POST /nursing/requests`` dengan ``diet_type_id`` ke unit
    farmasi menjawab 422 "Jenis diet hanya berlaku untuk permintaan ke unit
    gizi" dan **menyimpan** baris yang melanggar constraint itu.

    ``cr.rollback()`` di sini membatalkan transaksinya sebelum Response
    dikembalikan; ``retrying`` masih akan commit sesudahnya, tetapi yang
    di-commit adalah transaksi kosong.

    CACHE ORM SESUDAH ROLLBACK — kenapa TIDAK ada ``invalidate_all()``
    -----------------------------------------------------------------
    ``BaseCursor.rollback()`` sudah memanggil ``clear()``, dan ``clear()``
    memanggil ``transaction.clear()`` yang membuang seluruh cache field,
    penanda dirty dan antrian ``tocompute``. Menambahkan
    ``env.invalidate_all()`` sesudahnya justru berbahaya: default-nya
    ``flush=True``, jadi ia akan mencoba MENULIS ulang sebelum membuang cache
    — persis kebalikan dari yang diinginkan di sini.

    YANG SENGAJA IKUT HILANG
    ------------------------
    * ``hms.event`` (outbox) — barisnya hilang dan callback ``cr.postcommit``
      ikut dibuang oleh ``rollback()``. Itu memang kontrak outbox
      (DECISIONS §3): tidak ada pengumuman untuk transaksi yang batal.
    * ``hms.access.log`` — ditulis pada cursor yang sama, jadi ikut hilang.
      Diukur pada tumpukan bayangan: enam permintaan gagal lewat API
      menghasilkan **nol** baris audit (mixin hanya menimpa ``read()``,
      sementara akses field ORM lewat ``fetch()``; tabelnya tidak punya satu
      pun baris ``action='read'``). Yang bisa hilang hanyalah baris audit atas
      mutasi yang juga di-rollback — mencatatnya justru akan mengarang
      perubahan yang tidak pernah terjadi.
    """
    _rollback()
    return error_response(code, message, status=status, fields_=fields_)


def _rollback():
    """``cr.rollback()`` yang tidak pernah bisa menutupi galat aslinya."""
    try:
        request.env.cr.rollback()
    except Exception:  # noqa: BLE001
        # Rollback yang gagal tidak boleh menutupi galat yang sedang dilaporkan:
        # klien harus tetap menerima sebabnya, bukan exception kedua.
        _logger.exception("SIMRS API: rollback gagal saat menolak permintaan")


def _payload_value_origin(exc, body):
    """Apakah ``exc`` lahir dari konversi sebuah nilai DI BADAN PERMINTAAN?

    Mengembalikan ``(dari_payload, nama_field)``. ``nama_field`` boleh
    ``None``: kita tahu asalnya klien tetapi tidak bisa menyebut fieldnya,
    dan menebak nama field lebih buruk daripada diam.

    PEMBEDAAN YANG DIPAKAI, DAN KENAPA
    ----------------------------------
    Empat puluh satu ``int()``/``float()`` atas nilai body tinggal di sepuluh
    berkas ``controllers/``; logika bisnis tinggal di ``models/``. Karena
    ``int`` dan ``float`` adalah builtin C, mereka tidak menambah frame Python
    sendiri: **bingkai terdalam traceback adalah baris controller yang
    melakukan konversi itu**. Jadi syarat pertama bersifat struktural, bukan
    tebakan atas isi pesan: bingkai terdalam harus berada di direktori ini.

    Syarat kedua mengikat galatnya ke data klien: nilai yang gagal muncul apa
    adanya di pesan Python (``invalid literal for int() with base 10: 'dua'``),
    jadi ``repr(nilai)`` salah satu isi body harus ada di dalam pesan itu.
    Baris sumbernya dipakai sebagai bukti ketiga dan sebagai pemutus ketika
    dua field kebetulan bernilai sama.

    HARGA YANG TERSISA — BACA INI SEBELUM PERCAYA ANGKA 422
    -------------------------------------------------------
    Pembedaan ini menyempitkan, tetapi TIDAK menghapus, satu risiko: sebuah
    ``ValueError`` yang lahir dari **cacat kita sendiri** pada baris controller
    yang kebetulan juga menyentuh nilai body akan tetap dilaporkan sebagai
    kesalahan klien. Bug seperti itu bisa hidup lama justru karena setiap
    kemunculannya terbaca menenangkan.

    Karena itu 422 dari jalur ini **tidak selalu berarti klien yang salah**,
    dan karena itu pula ``hms_route`` mencatatnya sebagai ``WARNING`` dengan
    traceback penuh: cukup untuk ditemukan oleh siapa pun yang mencarinya,
    tidak cukup untuk mengubur log seperti ``ERROR`` pernah melakukannya.
    Lonjakan 422 pada satu endpoint adalah sinyal untuk membuka log, bukan
    untuk menyalahkan klien.
    """
    tb, filename, lineno = exc.__traceback__, None, None
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        lineno = tb.tb_lineno
        tb = tb.tb_next
    if not filename:
        return (False, None)
    if os.path.dirname(os.path.abspath(filename)) != _CONTROLLERS_DIR:
        # Lahir di ``models/``, di ORM, atau di pustaka: itu logika, bukan
        # payload. Jawabannya tetap 500, persis seperti sebelum perubahan ini.
        return (False, None)
    text = str(exc)
    by_value = {k for k, v in body.items() if isinstance(v, str) and repr(v) in text}
    linecache.checkcache(filename)
    named = set(_BODY_SUBSCRIPT.findall(linecache.getline(filename, lineno) or ""))
    named &= set(body)
    for candidates in (by_value & named, named, by_value):
        if len(candidates) == 1:
            return (True, next(iter(candidates)))
    if by_value or named:
        return (True, None)
    return (False, None)


def _constraint_columns(diag):
    """Kolom yang dijaga sebuah constraint — dari katalog, bukan dari tebakan.

    ``diag.column_name`` kosong untuk pelanggaran kunci asing, jadi namanya
    harus dicari. Sumber yang sahih adalah ``pg_constraint`` itu sendiri;
    kueri ini menyalin bentuk yang dipakai Odoo di
    ``get_columns_from_sql_diagnostics``. Harus dipanggil SESUDAH rollback:
    transaksi yang baru saja ditolak Postgres sudah abort dan menolak kueri
    apa pun.

    Cadangannya baru pola nama ``<tabel>_<kolom>_fkey``, dan pola itu hanya
    dipakai ketika nama tabelnya diketahui — tanpa itu pemenggalan
    ``hms_unit_request_station_id`` menjadi tebakan (``id``?
    ``request_station_id``?), dan menebak nama field lebih buruk daripada
    pesan umum.
    """
    if diag.column_name:
        return [diag.column_name]
    if diag.constraint_name and diag.table_name:
        try:
            request.env.cr.execute(
                """
                SELECT ARRAY(
                    SELECT attname FROM pg_attribute
                    WHERE attrelid = conrelid AND attnum = ANY(conkey)
                )
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE c.conname = %s
                  AND t.relname = %s
                  AND t.relnamespace = current_schema::regnamespace
                """,
                (diag.constraint_name, diag.table_name),
            )
            row = request.env.cr.fetchone()
            if row and row[0]:
                return list(row[0])
        except Exception:  # noqa: BLE001
            _logger.warning(
                "SIMRS API: katalog constraint %r tidak terbaca; memakai pola nama.",
                diag.constraint_name, exc_info=True,
            )
        suffix = "_fkey"
        prefix = diag.table_name + "_"
        name = diag.constraint_name
        if name.startswith(prefix) and name.endswith(suffix):
            return [name[len(prefix):-len(suffix)]]
    return []


def _foreign_key_rejection(exc):
    """Pesan 422 untuk pelanggaran kunci asing, atau ``None`` bila bukan.

    ``None`` berarti "ini bukan kesalahan klien" dan pemanggil harus
    memperlakukannya persis seperti exception tak terduga lain: 500.

    DISKRIMINASINYA HANYA ``pgcode``
    --------------------------------
    Menangkap ``IntegrityError`` apa adanya akan menyeret constraint bisnis
    kita sendiri ke dalam kantong yang sama. ``models.Constraint("unique(nik)")``
    naik sebagai 23505 lewat ``create()`` yang sama; melaporkannya sebagai
    "data yang dirujuk tidak ada" salah dua kali — salah tentang sebabnya, dan
    salah tentang ada-tidaknya data.

    BAHKAN 23503 TIDAK SELALU BERARTI ID HANTU
    -------------------------------------------
    Kode yang sama terbit saat MENGHAPUS baris yang masih dirujuk
    (``... is still referenced from table ...``). Itu tetap kesalahan klien,
    tetapi bukan id hantu, dan pesannya tidak boleh mengatakan datanya tidak
    ada. Pembedanya ada di ``message_detail``; bila bentuknya tidak dikenali
    sama sekali, jawabannya tetap 422 tetapi umum — tanpa menyebut field.
    """
    if getattr(exc, "pgcode", None) != PG_FOREIGN_KEY_VIOLATION:
        return None
    diag = exc.diag
    detail = diag.message_detail or ""
    columns = _constraint_columns(diag)
    if len(columns) == 1 and _FK_ROW_ABSENT in detail:
        field = columns[0]
        return (
            _("Field '%s' merujuk data yang tidak ada.") % field,
            {field: _("Data yang dirujuk tidak ada.")},
        )
    if _FK_ROW_ABSENT in detail:
        return (_("Permintaan merujuk data yang tidak ada."), {})
    return (
        _("Referensi data pada permintaan tidak dapat dipenuhi (%s).")
        % (diag.constraint_name or "-"),
        {},
    )


def _indonesian_installed():
    """Cached lookup of whether id_ID is available in this database."""
    global _LANG_CHECKED, _LANG_AVAILABLE
    if _LANG_CHECKED:
        return _LANG_AVAILABLE
    _LANG_AVAILABLE = bool(request.env["res.lang"].sudo().search_count([
        ("code", "=", "id_ID"), ("active", "=", True),
    ]))
    _LANG_CHECKED = True
    return _LANG_AVAILABLE


def _client_ip():
    return request.httprequest.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
        or request.httprequest.remote_addr


def _rate_limited(key, limit):
    """Fixed-window counter. Coarse on purpose; see the note on _BUCKETS."""
    window = int(time.time() // 60)
    bucket = _BUCKETS.get(key)
    if not bucket or bucket[0] != window:
        _BUCKETS[key] = [window, 1]
        return False
    bucket[1] += 1
    if len(_BUCKETS) > 10000:
        # Bound the dictionary; stale windows are worthless anyway.
        for stale_key in [k for k, v in _BUCKETS.items() if v[0] < window - 1]:
            _BUCKETS.pop(stale_key, None)
    return bucket[1] > limit


def _decode_bearer():
    header = request.httprequest.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[7:].strip()
    try:
        return jwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AccessDenied(_("Token kedaluwarsa.")) from None
    except jwt.InvalidTokenError:
        raise AccessDenied(_("Token tidak sah.")) from None


class MissingPayloadField(KeyError):
    """Kunci wajib tidak ada DI BADAN PERMINTAAN — bukan ``KeyError`` sembarang.

    Tipe tersendiri, bukan ``KeyError`` polos, karena itulah satu-satunya hal
    yang membuat penangkapnya di ``hms_route`` aman. Lihat ``PayloadDict``.
    """

    def __init__(self, field):
        self.field = field
        super().__init__(field)

    def __str__(self):
        # ``KeyError.__str__`` mengembalikan ``repr(args[0])`` ("'station_id'"),
        # yang ikut terbawa ke pesan untuk pengguna lengkap dengan tanda kutip
        # ganda. Nama fieldnya saja sudah cukup.
        return self.field


class PayloadDict(dict):
    """Badan permintaan JSON, dengan satu perilaku tambahan.

    KENAPA SUBCLASS, BUKAN ``except KeyError`` DI DEKORATOR
    -------------------------------------------------------
    Ada 47 pemanggilan ``body["..."]`` tanpa penjaga di sepuluh controller.
    Yang hilang satu kunci melempar ``KeyError`` mentah dan jatuh ke cabang
    ``except Exception``: klien yang salah kirim dijawab 500 "Hubungi
    administrator" atas kesalahannya sendiri, dan tiap payload cacat menulis
    baris ``ERROR`` + traceback penuh sehingga galat sungguhan tenggelam.

    Menambal 47 tempat berarti 47 kesempatan untuk lupa, dan endpoint ke-48
    lahir tanpa penjaga. Perbaikannya karena itu ada di batas.

    Menangkap ``except KeyError`` di ``hms_route`` adalah jawaban yang SALAH:
    ``KeyError`` juga lahir dari dalam logika bisnis — dict internal, cache,
    peta kode — dan menyamarkannya jadi "field wajib hilang" menyembunyikan
    bug nyata di balik 422 yang menenangkan.

    ``dict.__getitem__`` memanggil ``__missing__`` **hanya** bila kuncinya
    tidak ada pada dict ITU. ``KeyError`` dari dict mana pun yang lain bukan
    ``MissingPayloadField`` dan tetap jatuh ke 500. Pembedaannya struktural,
    bukan tebakan atas nama kunci — dibuktikan oleh
    ``test_business_key_error_is_still_an_internal_error``, yang memaksa
    ``KeyError("station_id")`` dari dict milik logika bisnis dan tetap menuntut
    500.

    ``.get()``, ``in``, ``pop()`` dan ``setdefault()`` TIDAK memanggil
    ``__missing__`` (hanya ``__getitem__`` yang memanggilnya), jadi setiap
    field opsional tetap berperilaku persis seperti sebelumnya.

    NESTING: SENGAJA TIDAK REKURSIF
    -------------------------------
    Hanya dict teratas yang dibungkus; ``body["a"]["b"]`` pada dict dalam tetap
    memberi ``KeyError`` biasa, artinya 500. Itu keputusan sadar, dengan dua
    alasan:

    * **Tidak ada satu pun** rantai ``body["a"]["b"]`` di sepuluh controller
      hari ini (diukur); sub-dict payload selalu dibaca dengan ``.get()``
      (mis. ``body["referral"].get("no")`` di ``registrations``).
    * Sub-dict payload **diserahkan utuh ke logika bisnis** — 
      ``Patient.create(body["new_patient"])``. Pembungkus yang ikut masuk ke
      dalam ORM membuat ``KeyError`` internal ORM atas dict itu menjelma jadi
      "field wajib hilang": persis misatribusi yang seluruh desain ini ada
      untuk mencegah. Jangkauan pembungkus sengaja berhenti di tempat yang
      masih bisa dijamin.

    Batasnya: payload bersarang yang kurang kunci tetap dijawab 500. Bila kelak
    ada handler yang benar-benar mensubskrip dict dalam, bungkus dict itu di
    tempatnya (``PayloadDict(body["referral"])``) — keputusan lokal, di tempat
    yang tahu dict itu memang datang dari klien.
    """

    def __missing__(self, key):
        raise MissingPayloadField(key)

    def __bool__(self):
        """Badan permintaan selalu "ada", meski kosong.

        Tiga puluh sembilan handler membuka dengan ``body = body or {}``. Tanpa
        ini, badan kosong (``{}``) — justru payload yang paling mungkin kurang
        field wajib — akan diganti ``dict`` biasa dan kehilangan penjaganya
        tepat pada kasus yang paling sering terjadi. Tidak ada satu pun
        pemanggil yang memakai ``if body:`` untuk menanyakan "apakah berisi";
        yang dipakai selalu ``body.get(...)``.
        """
        return True


def payload():
    """Badan JSON yang sudah di-parse, sebagai ``PayloadDict``."""
    raw = request.httprequest.get_data(as_text=True)
    if not raw:
        return PayloadDict()
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise UserError(_("Badan permintaan bukan JSON yang sah.")) from None
    if not isinstance(parsed, dict):
        # JSON sah yang bukan objek (list, angka, ``null``) dulu lolos ke
        # handler dan mati di ``body.get`` sebagai AttributeError -> 500.
        # Tidak ada endpoint yang menerima badan non-objek; ini kesalahan
        # klien dan dijawab seperti kesalahan klien.
        raise ValidationError(_("Badan permintaan harus berupa objek JSON."))
    return PayloadDict(parsed)


def hms_route(path, methods=("GET",), auth_required=True, idempotent=False):
    """Route decorator: auth, errors, rate limit and idempotency in one place.

    Everything the spec calls for happens here rather than in each handler, so
    a new endpoint cannot accidentally skip the parts that matter.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            started = time.time()
            endpoint = f"{request.httprequest.method} {path}"
            # Diinisialisasi SEBELUM `try` karena cabang `except ValueError`
            # membacanya: sebuah ValueError yang naik sebelum badan permintaan
            # sempat di-parse (mis. `int(claims["sub"])` pada token cacat)
            # akan menabrak NameError di dalam handler galatnya sendiri —
            # kegagalan yang menutupi sebab aslinya.
            body = PayloadDict()
            try:
                if auth_required:
                    claims = _decode_bearer()
                    if not claims:
                        return rejected(
                            "unauthenticated", _("Token akses tidak ditemukan."), 401
                        )
                    uid = int(claims["sub"])
                    # Penanda diperiksa pada SETIAP permintaan, bukan sesekali:
                    # "sesekali" mengubah jaminannya tanpa mengubah namanya.
                    # Klaim yang hilang ditolak, tidak dianggap lolos — token
                    # lama yang terbit sebelum fitur ini ada harus gagal
                    # tertutup, bukan diterima diam-diam.
                    holder = request.env["res.users"].sudo().browse(uid).exists()
                    marker = credential_marker(holder) if holder else None
                    presented = claims.get("stk")
                    # `marker is None` ditolak, bukan dicocokkan: token tanpa
                    # klaim `stk` juga menghasilkan None, dan membandingkan
                    # None dengan None akan MELOLOSKAN keduanya sekaligus.
                    if marker is None or presented != marker:
                        return rejected(
                            "unauthenticated",
                            _("Sesi tidak berlaku lagi karena kredensial akun "
                              "berubah. Silakan masuk kembali."),
                            401,
                        )
                    limit_key = f"u{uid}"
                    if _rate_limited(limit_key, RATE_LIMIT_PER_MINUTE):
                        return rejected(
                            "rate_limited", _("Terlalu banyak permintaan."), 429
                        )
                    # Odoo 19 made Environment.context read-only; the context
                    # is passed to update_env instead of assigned afterwards.
                    context = dict(
                        request.env.context,
                        tz="Asia/Jakarta",
                        hms_request_meta={
                            "ip": _client_ip(),
                            "user_agent": request.httprequest.headers.get("User-Agent"),
                        },
                    )
                    # Force Indonesian only when the language is actually
                    # installed. Setting an absent code makes every ORM call
                    # raise, which looks like a business-rule failure to the
                    # caller and hides the real (trivial) cause.
                    if _indonesian_installed():
                        context["lang"] = "id_ID"
                    request.update_env(user=uid, context=context)
                else:
                    if _rate_limited(f"ip{_client_ip()}", PUBLIC_RATE_LIMIT_PER_MINUTE):
                        return rejected(
                            "rate_limited", _("Terlalu banyak permintaan."), 429
                        )

                if request.httprequest.method in ("POST", "PATCH", "PUT"):
                    body = payload()
                idem_key = request.httprequest.headers.get("Idempotency-Key")
                request_hash = hashlib.sha256(
                    json.dumps(body, sort_keys=True, default=str).encode()
                ).hexdigest()
                if idempotent and idem_key and auth_required:
                    stored = request.env["hms.api.idempotency"].lookup(
                        idem_key, endpoint, request_hash
                    )
                    if stored and stored.get("conflict"):
                        return rejected(
                            "idempotency_conflict",
                            _("Idempotency-Key sudah dipakai untuk permintaan dengan isi berbeda."),
                            409,
                        )
                    if stored:
                        return Response(
                            stored["body"], status=stored["status"],
                            headers=[("Content-Type", "application/json; charset=utf-8"),
                                     ("X-HMS-Idempotent-Replay", "1")],
                        )

                result = func(self, body=body, **kwargs)
                # Tulisan yang masih tertunda harus meledak DI DALAM batas ini.
                # ``write()`` pada Many2one tidak menyentuh basis data sampai
                # ada yang memaksanya; tanpa baris ini `service.model.retrying`
                # yang melakukannya — SESUDAH dekorator mengembalikan 200 —
                # dan galatnya keluar sebagai halaman 500 Odoo, di luar amplop
                # {"error": ...} yang dijanjikan kontrak. Kalau flush gagal,
                # exception-nya jatuh ke cabang `except` di bawah dan
                # permintaannya dijawab seperti penolakan lain.
                request.env.flush_all()
                if isinstance(result, Response):
                    response = result
                else:
                    response = json_response(result)

                # Handler yang MENOLAK sendiri, tanpa exception. Dua di
                # antaranya benar-benar menulis lebih dulu:
                #   * `inpatient.discharge` menyimpan `discharge_disposition`
                #     lalu menjawab 409 "Pasien belum dapat dipulangkan";
                #   * `casemix.claim_codes_write` sudah meng-unlink dan
                #     menulis sebagian kode klaim ketika menjawab 422 "Kode ini
                #     bukan milik klaim tersebut" di tengah loop — separuh
                #     pengkodean klaim BPJS tersimpan atas jawaban "ditolak".
                # Manifest modul ini menjanjikan "satu use-case, satu endpoint,
                # satu transaksi; frontend tidak pernah memegang setengah
                # keadaan". Aturannya karena itu satu untuk semua: apa pun yang
                # keluar dari dekorator ini dengan status >= 400 berarti tidak
                # ada yang tersimpan.
                if response.status_code >= 400:
                    _rollback()
                    return response

                if idempotent and idem_key and auth_required and response.status_code < 400:
                    request.env["hms.api.idempotency"].remember(
                        idem_key, endpoint, request_hash,
                        response.get_data(as_text=True), response.status_code,
                    )
                return response
            # Setiap cabang di bawah memakai `rejected`, yang me-rollback lebih
            # dulu. Alasan per cabang, karena menyeragamkan tanpa memeriksa
            # adalah cara lain untuk salah:
            #
            # * AccessDenied — biasanya naik dari `_decode_bearer()`, sebelum
            #   ada tulisan apa pun, jadi rollback-nya no-op. Tetap dipasang
            #   karena AccessDenied juga bisa naik dari dalam handler. Yang
            #   TIDAK ikut terbuang: pencacah login gagal Odoo hidup di memori
            #   registry (`registry._login_failures`), bukan di basis data, dan
            #   `/auth/login` menangkap AccessDenied-nya sendiri sehingga
            #   jawabannya tidak pernah lewat sini.
            # * AccessError / MissingError — umumnya jalur baca, tetapi bisa
            #   naik setelah tulisan pada handler campuran (`check_access`
            #   dipanggil di tengah). Rollback wajib justru untuk kasus itu.
            # * ValidationError / UserError — inti cacatnya; lihat `rejected`.
            # URUTAN: `MissingPayloadField` diletakkan PALING ATAS dengan
            # sengaja. Ia subclass `KeyError` -> `LookupError` -> `Exception`,
            # dan tidak satu pun dari AccessDenied/AccessError/MissingError/
            # ValidationError/UserError/HTTPException ada di MRO-nya, jadi
            # secara teknis ia tidak bisa tertelan cabang mana pun. Yang HARUS
            # dijaga hanyalah ia mendahului `except Exception` di bawah — dan
            # menaruhnya di posisi pertama membuat syarat itu mustahil dirusak
            # oleh suntingan berikutnya. `KeyError` biasa tetap lewat sini
            # tanpa tersentuh dan jatuh ke `except Exception`: 500, sesuai
            # maksudnya.
            #
            # Dua cabang Gelombang 11 (`psycopg2.IntegrityError`, `ValueError`)
            # duduk di bawah cabang-cabang Odoo dan DI ATAS `except Exception`.
            # Keduanya tidak punya hubungan MRO dengan cabang mana pun di
            # atasnya, jadi satu-satunya syarat yang harus dijaga tetap sama:
            # mereka mendahului `except Exception`. Keduanya juga bisa
            # mengembalikan 500 sendiri — lihat masing-masing — karena "galat
            # bertipe ini" tidak sama dengan "kesalahan klien".
            except MissingPayloadField as exc:
                # INFO, bukan ERROR, dan tanpa `_logger.exception`: payload
                # cacat adalah kesalahan klien, bukan insiden sistem. Sebelum
                # ini tiap payload cacat menulis satu baris ERROR + traceback
                # penuh, dan galat sungguhan tenggelam di antaranya.
                _logger.info(
                    "SIMRS API: payload kurang field wajib pada %s — '%s'",
                    endpoint, exc.field,
                )
                return rejected(
                    "validation_error",
                    _("Field wajib '%s' tidak ada pada badan permintaan.") % exc.field,
                    422,
                    fields_={exc.field: _("Field wajib tidak ada.")},
                )
            except AccessDenied as exc:
                return rejected("unauthenticated", str(exc) or _("Akses ditolak."), 401)
            except AccessError as exc:
                return rejected("forbidden", str(exc), 403)
            except MissingError:
                return rejected("not_found", _("Data tidak ditemukan."), 404)
            except ValidationError as exc:
                return rejected("validation_error", str(exc), 422)
            except UserError as exc:
                return rejected("business_rule", str(exc), 400)
            except psycopg2.IntegrityError as exc:
                # Rollback DULU: transaksinya sudah di-abort Postgres, dan
                # `_constraint_columns` perlu cursor yang bisa dipakai lagi.
                # `rejected()` akan me-rollback sekali lagi; rollback kedua
                # atas transaksi bersih adalah no-op.
                _rollback()
                verdict = _foreign_key_rejection(exc)
                if verdict is None:
                    # Constraint bisnis kita sendiri (unique/check/not-null)
                    # dan galat integritas lain: tidak boleh menyamar jadi
                    # kesalahan klien. Perlakuannya sama dengan exception tak
                    # terduga mana pun.
                    _logger.exception("SIMRS API gagal pada %s", endpoint)
                    return rejected(
                        "internal_error",
                        _("Terjadi kesalahan sistem. Hubungi administrator dengan "
                          "waktu kejadian."),
                        500,
                    )
                message, fields_ = verdict
                # WARNING, bukan ERROR: id yang tidak ada adalah kesalahan
                # klien, bukan insiden sistem. Tanpa traceback — nama
                # constraint sudah menunjuk tepat ke tempatnya, dan traceback
                # penuh untuk tiap id salah ketik adalah persis kebisingan
                # yang membuat galat sungguhan tenggelam.
                _logger.warning(
                    "SIMRS API: referensi ke data yang tidak ada pada %s — %s",
                    endpoint, exc.diag.constraint_name,
                )
                return rejected("validation_error", message, 422, fields_=fields_)
            except ValueError as exc:
                from_payload, field = _payload_value_origin(exc, body)
                if not from_payload:
                    _logger.exception("SIMRS API gagal pada %s", endpoint)
                    return rejected(
                        "internal_error",
                        _("Terjadi kesalahan sistem. Hubungi administrator dengan "
                          "waktu kejadian."),
                        500,
                    )
                # WARNING **dengan traceback**. Lihat `_payload_value_origin`:
                # cabang ini tidak bisa menjamin 100% bahwa sebabnya klien,
                # jadi baris lognya harus cukup untuk membuktikan sebaliknya
                # ketika seseorang datang mencarinya. ERROR akan mengubur log
                # (satu baris per payload cacat); INFO akan membuang
                # traceback-nya justru pada cabang yang paling membutuhkannya.
                _logger.warning(
                    "SIMRS API: nilai payload tidak dapat dikonversi pada %s — field %s",
                    endpoint, field or "(tidak teridentifikasi)", exc_info=True,
                )
                if field:
                    return rejected(
                        "validation_error",
                        _("Nilai untuk field '%s' tidak dapat diproses.") % field,
                        422,
                        fields_={field: _("Nilai tidak dapat dikonversi.")},
                    )
                return rejected(
                    "validation_error",
                    _("Ada nilai pada badan permintaan yang tidak dapat diproses."),
                    422,
                )
            except werkzeug.exceptions.HTTPException:
                # SENGAJA tanpa rollback. Exception ini dilempar ulang, jadi
                # `service.model.retrying` tidak pernah sampai ke `cr.commit()`
                # dan `Request._serve_db` menutup cursornya di blok `finally`;
                # `Cursor.close()` me-rollback (`_close(True)`). Transaksinya
                # milik Odoo di jalur ini — menambahkan rollback di sini hanya
                # mengaburkan siapa pemiliknya, tanpa mengubah hasilnya.
                raise
            except Exception:  # noqa: BLE001 — the boundary must not leak tracebacks
                _logger.exception("SIMRS API gagal pada %s", endpoint)
                return rejected(
                    "internal_error",
                    _("Terjadi kesalahan sistem. Hubungi administrator dengan waktu kejadian."),
                    500,
                )
            finally:
                elapsed = int((time.time() - started) * 1000)
                if elapsed > 1000:
                    _logger.warning("SIMRS API lambat: %s %sms", endpoint, elapsed)

        return wrapper
    return decorator


def paginate(records, page=1, page_size=25, max_size=50):
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 25), 1), max_size)
    total = len(records)
    start = (page - 1) * page_size
    return {
        "items": records[start:start + page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
