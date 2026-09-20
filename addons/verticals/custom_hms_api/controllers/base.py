# -*- coding: utf-8 -*-
"""Shared plumbing for every /api/v1 endpoint."""
import functools
import hashlib
import json
import logging
import os
import time

import jwt
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


def payload():
    """Parsed JSON body, or {} for bodies that carry none."""
    raw = request.httprequest.get_data(as_text=True)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise UserError(_("Badan permintaan bukan JSON yang sah.")) from None


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
            try:
                if auth_required:
                    claims = _decode_bearer()
                    if not claims:
                        return error_response(
                            "unauthenticated", _("Token akses tidak ditemukan."), 401
                        )
                    uid = int(claims["sub"])
                    limit_key = f"u{uid}"
                    if _rate_limited(limit_key, RATE_LIMIT_PER_MINUTE):
                        return error_response(
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
                        return error_response(
                            "rate_limited", _("Terlalu banyak permintaan."), 429
                        )

                body = payload() if request.httprequest.method in ("POST", "PATCH", "PUT") else {}
                idem_key = request.httprequest.headers.get("Idempotency-Key")
                request_hash = hashlib.sha256(
                    json.dumps(body, sort_keys=True, default=str).encode()
                ).hexdigest()
                if idempotent and idem_key and auth_required:
                    stored = request.env["hms.api.idempotency"].lookup(
                        idem_key, endpoint, request_hash
                    )
                    if stored and stored.get("conflict"):
                        return error_response(
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
                if isinstance(result, Response):
                    response = result
                else:
                    response = json_response(result)

                if idempotent and idem_key and auth_required and response.status_code < 400:
                    request.env["hms.api.idempotency"].remember(
                        idem_key, endpoint, request_hash,
                        response.get_data(as_text=True), response.status_code,
                    )
                return response
            except AccessDenied as exc:
                return error_response("unauthenticated", str(exc) or _("Akses ditolak."), 401)
            except AccessError as exc:
                return error_response("forbidden", str(exc), 403)
            except MissingError:
                return error_response("not_found", _("Data tidak ditemukan."), 404)
            except ValidationError as exc:
                return error_response("validation_error", str(exc), 422)
            except UserError as exc:
                return error_response("business_rule", str(exc), 400)
            except werkzeug.exceptions.HTTPException:
                raise
            except Exception:  # noqa: BLE001 — the boundary must not leak tracebacks
                _logger.exception("SIMRS API gagal pada %s", endpoint)
                return error_response(
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
