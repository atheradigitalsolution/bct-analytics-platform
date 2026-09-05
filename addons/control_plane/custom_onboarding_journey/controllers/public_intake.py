# -*- coding: utf-8 -*-
"""Controller publik untuk intake onboarding + polling status.

Keduanya tanpa autentikasi. Itu memang tujuannya — pengunjung yang belum jadi
klien tidak punya kredensial apa pun — tetapi berarti setiap baris di berkas ini
menerima masukan dari orang yang tidak dikenal. Tiga sikap yang berlaku di sini:

1. **Gagal tertutup.** Verifikasi bot yang tidak bisa dijalankan berarti kiriman
   ditolak, bukan diterima. Versi sebelumnya melakukan yang sebaliknya di tiga
   tempat sekaligus, sehingga endpoint ini praktis tidak dijaga apa pun.
2. **Bentuk ditentukan di sini, bukan oleh pengirim.** Payload disaring dengan
   daftar-putih dan dibatasi ukurannya sebelum menyentuh basis data.
3. **Batas laju hidup di basis data**, bukan di memori proses, karena Odoo di sini
   berjalan dengan lebih dari satu worker dan di-restart setiap deploy.

Endpoint status hanya mengembalikan kolom yang tidak sensitif.
"""

from __future__ import annotations

import hashlib
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

#: Kunci yang boleh masuk dari endpoint PUBLIK, beserta batas panjang nilainya.
#:
#: Daftar ini sengaja lebih sempit daripada yang bisa dibaca `action_promote_to_journey`.
#: Yang DIKELUARKAN dan alasannya:
#:
#: * ``npwp``, ``bank_name``, ``bank_account`` — identitas pajak dan rekening dari
#:   pengirim yang belum diverifikasi siapa pun, masuk ke basis data kontrol dalam
#:   bentuk terbaca. Tidak ada konsumen yang memerlukannya pada tahap ini; data itu
#:   dikumpulkan setelah ada hubungan, lewat jalur internal.
#: * ``brd_file_base64s``, ``brd_filenames`` — unggahan berkas dari pihak anonim.
#:   Formulir kontak bukan tempat mengunggah berkas; BRD masuk lewat wizard internal
#:   yang tahu siapa yang mengunggah.
#:
#: Kunci di luar daftar DIBUANG, bukan ditolak: formulir yang menolak seluruh
#: kiriman karena satu kolom asing adalah formulir yang kehilangan calon klien.
PUBLIC_FIELD_LIMITS: dict[str, int] = {
    "company_name": 200,
    "partner_name": 120,
    "contact_email": 200,
    "partner_email": 200,
    "contact_phone": 40,
    "vertical_target": 100,
    "company_size": 60,
    "interest": 120,
    "current_system": 200,
    "message": 4000,
    "source": 120,
    "locale": 20,
    "consent_text": 500,
}

#: Kunci boolean. Dipisahkan supaya `False` tidak berubah menjadi string "False".
PUBLIC_BOOL_FIELDS = frozenset({"consent_given"})

#: Tanpa ini tidak ada yang bisa ditindaklanjuti, jadi kiriman tanpa nama perusahaan
#: bukan lead — ia baris kosong. Satu baris `{}` sudah pernah mendarat di produksi
#: lewat endpoint ini justru karena syarat ini tidak pernah diperiksa di sini.
REQUIRED_FIELDS = ("company_name",)

#: Batas ukuran payload tersimpan.
#:
#: NILAINYA HARUS DI ATAS LANGIT-LANGIT DAFTAR-PUTIH, TAPI TIDAK JAUH DI ATASNYA.
#: Jumlah seluruh batas di `PUBLIC_FIELD_LIMITS` sekitar 5,6 KB, jadi angka pertama
#: yang dipakai di sini — 64 KB — tidak akan pernah bisa tercapai: sebuah penjagaan
#: yang tampak ada di kode tetapi tidak pernah bisa menyala. Diukur: payload sah
#: terbesar yang bisa dibangun berhenti di 5.152 byte.
#:
#: 8 KB memberi ruang untuk pertumbuhan wajar sambil tetap berada dalam jangkauan,
#: sehingga menambahkan satu kolom besar tanpa berpikir akan menabraknya di uji —
#: bukan di produksi. Uji `test_size_cap_is_reachable` menjaga hubungan itu.
DEFAULT_MAX_PAYLOAD_BYTES = 8192


def _hash_ip(ip: str | None) -> str:
    if not ip:
        return ""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()


def _sanitize(payload: dict) -> dict:
    """Saring payload menjadi bentuk yang sudah dikenal."""
    clean: dict = {}
    for key, limit in PUBLIC_FIELD_LIMITS.items():
        value = payload.get(key)
        if value is None or isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            clean[key] = text[:limit]
    for key in PUBLIC_BOOL_FIELDS:
        if key in payload:
            clean[key] = bool(payload[key])
    return clean


def _verify_turnstile(secret: str, token: str, remote_ip: str | None, required: bool) -> bool:
    """Verifikasi Cloudflare Turnstile.

    GAGAL TERTUTUP KETIKA DIWAJIBKAN. Setiap jalan keluar di bawah — rahasia belum
    dipasang, pustaka HTTP tidak ada, panggilan ke Cloudflare gagal — dulu berakhir
    dengan `return True`. Tiga cara berbeda untuk membuat penjagaan ini menghilang
    tanpa satu pun tanda di antarmuka. Sekarang ketiganya menghormati `required`:
    kalau penjagaan diwajibkan dan tidak bisa dijalankan, kiriman ditolak.

    Ketika TIDAK diwajibkan, endpoint tetap terbuka — tetapi setiap kiriman
    meninggalkan WARNING, supaya keadaan sementara ini tidak bisa diam-diam menjadi
    keadaan tetap.
    """
    if not secret:
        if required:
            _logger.error(
                "turnstile: onboarding.turnstile.required aktif tetapi "
                "onboarding.turnstile.secret kosong; kiriman ditolak"
            )
            return False
        _logger.warning(
            "turnstile: tidak dikonfigurasi; intake publik berjalan TANPA verifikasi bot"
        )
        return True
    if not token:
        _logger.warning("turnstile: tidak ada token di payload; ditolak")
        return False
    try:
        import requests  # type: ignore
    except ImportError:
        _logger.error("turnstile: pustaka 'requests' tidak terpasang")
        return not required
    try:
        resp = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        return bool(resp.json().get("success"))
    except Exception as exc:
        _logger.error("turnstile: panggilan verifikasi gagal (%s)", exc)
        return not required


class OnboardingPublicIntake(http.Controller):
    @http.route(
        "/onboarding/public/intake",
        # `type="jsonrpc"`. Odoo 19 masih menerima `"json"` sebagai alias usang dan
        # menuliskan DeprecationWarning lengkap dengan jejak tumpukan pada setiap
        # boot, sehingga log start-up tampak seolah memuat kesalahan.
        type="jsonrpc",
        auth="public",
        csrf=False,
        methods=["POST"],
    )
    def public_intake(self, **payload):
        # JSON-RPC membuka `params` menjadi kwargs controller.
        ICP = request.env["ir.config_parameter"].sudo()
        per_hour = int(ICP.get_param("onboarding.rate_limit_per_ip_per_hour", "5") or "5")
        turnstile_secret = ICP.get_param("onboarding.turnstile.secret", "") or ""
        turnstile_required = (
            (ICP.get_param("onboarding.turnstile.required", "0") or "0").strip().lower()
            in ("1", "true", "yes", "on")
        )
        max_bytes = int(
            ICP.get_param("onboarding.max_payload_bytes", str(DEFAULT_MAX_PAYLOAD_BYTES))
            or DEFAULT_MAX_PAYLOAD_BYTES
        )

        remote_ip = request.httprequest.remote_addr if request.httprequest else None
        ip_hash = _hash_ip(remote_ip)

        # Batas laju DULU, sebelum apa pun yang mahal. Verifikasi Turnstile adalah
        # panggilan HTTP keluar; kalau ia berada di depan batas laju, endpoint ini
        # menjadi penguat lalu lintas menuju Cloudflare atas perintah siapa pun.
        throttle = request.env["onboarding.intake.throttle"].sudo()
        if throttle.check_and_count(ip_hash, per_hour):
            return {"error": "rate_limited", "retry_after_seconds": 3600}

        turnstile_token = payload.pop("turnstile_token", None)
        if not _verify_turnstile(turnstile_secret, turnstile_token, remote_ip, turnstile_required):
            return {"error": "turnstile_failed" if turnstile_secret else "turnstile_unavailable"}

        clean = _sanitize(payload)
        missing = [k for k in REQUIRED_FIELDS if not clean.get(k)]
        if missing:
            _logger.info("intake: kiriman ditolak, kolom wajib kosong: %s", ", ".join(missing))
            return {"error": "invalid_payload", "missing": missing}

        body = json.dumps(clean, ensure_ascii=False, default=str)
        size = len(body.encode("utf-8"))
        if size > max_bytes:
            _logger.warning("intake: payload %d byte melampaui batas %d byte", size, max_bytes)
            return {"error": "payload_too_large", "max_bytes": max_bytes}

        submission = (
            request.env["onboarding.public.submission"]
            .sudo()
            .create(
                {
                    "raw_payload_json": body,
                    "source_ip_hash": ip_hash or False,
                }
            )
        )
        _logger.info(
            "intake: kiriman %s diterima (%d byte, turnstile=%s)",
            submission.id,
            size,
            "verified" if turnstile_secret else "disabled",
        )

        base_url = ICP.get_param("web.base.url", "")
        return {
            "token": submission.public_token,
            "status_url": f"{base_url}/onboarding/public/status/{submission.public_token}",
        }

    @http.route(
        "/onboarding/public/status/<string:token>",
        type="http",
        auth="public",
        csrf=False,
        methods=["GET"],
    )
    def public_status(self, token, **_kwargs):
        Journey = request.env["onboarding.journey"].sudo()
        # Percobaan pertama: journey yang langsung memegang token ini.
        journey = Journey.search([("public_status_token", "=", token)], limit=1)
        # Cadangan: token milik sebuah submission yang sudah dipromosikan.
        if not journey:
            sub = (
                request.env["onboarding.public.submission"]
                .sudo()
                .search(
                    [("public_token", "=", token)],
                    limit=1,
                )
            )
            if sub and sub.journey_id:
                journey = sub.journey_id

        if not journey:
            body = json.dumps({"error": "not_found"})
            return request.make_response(body, headers=[("Content-Type", "application/json")], status=404)

        body = json.dumps(
            {
                "stage": journey.stage,
                "target_go_live": journey.target_go_live.isoformat() if journey.target_go_live else None,
                "progress_pct": journey.progress_pct,
                "last_update": journey.write_date.isoformat() if journey.write_date else None,
            }
        )
        return request.make_response(body, headers=[("Content-Type", "application/json")])
