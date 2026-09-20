# -*- coding: utf-8 -*-
"""Pendaftaran perangkat: tukar sesi menjadi kunci API sekali pakai-seumur-perangkat.

ALUR, DAN KENAPA BEGINI
-----------------------
PWA tidak boleh meminta pengemudi menempelkan kunci 40 karakter. Jadi:

  1. Perangkat mengirim login + kata sandi ke server Next.js (bukan ke Odoo).
  2. Server Next.js menukarnya ke Odoo `/web/session/authenticate` → sesi.
  3. Server Next.js memanggil endpoint INI dengan sesi itu → menerima kunci API.
  4. Kunci disimpan di cookie httpOnly di sisi server. Ia tidak pernah sampai
     ke JavaScript browser, jadi XSS di salah satu layar tidak menyerahkan
     kunci yang bekerja kepada penyerang.
  5. Seluruh panggilan `/json/2` berikutnya memakai kunci itu.

Endpoint ini `auth='user'`: ia hanya bisa dipanggil oleh sesi yang sudah
terautentikasi. Ia tidak menerima kata sandi dan tidak melakukan autentikasi
sendiri — menumpuk dua jalur autentikasi di satu tempat adalah cara salah
satunya lupa diperbarui.
"""
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)

ALLOWED_KINDS = ("driver", "scanner")


class LgxDeviceController(http.Controller):

    @http.route("/lgx/api/device/register", type="json", auth="user", methods=["POST"],
                csrf=False, save_session=False)
    def register_device(self, kind=None, device_name=None, **kwargs):
        """Terbitkan kunci API untuk perangkat milik pengguna yang sedang login."""
        if kind not in ALLOWED_KINDS:
            return {"error": {"code": "bad_kind",
                              "message": _("Jenis perangkat '%s' tidak dikenal.", kind)}}
        user = request.env.user
        group = ("custom_lgx_base.group_lgx_driver" if kind == "driver"
                 else "custom_lgx_base.group_lgx_wh_operator")
        if not user.has_group(group):
            # Pesan yang sama untuk "tidak berhak" apa pun jenisnya. Membedakan
            # "kamu bukan pengemudi" dari "kamu bukan operator gudang" memberi
            # tahu penebak peran apa yang sedang ia dekati.
            return {"error": {"code": "forbidden",
                              "message": _("Pengguna ini tidak berhak mendaftarkan perangkat.")}}
        device_name = (device_name or "").strip()[:64] or _("Perangkat tanpa nama")
        remote = request.httprequest.headers.get(
            "X-Forwarded-For", request.httprequest.remote_addr)
        device, raw_key = request.env["lgx.api.device"].sudo().lgx_issue_key(
            user, kind, device_name, remote_addr=remote)
        _logger.info("Perangkat %s (%s) didaftarkan untuk %s", device_name, kind, user.login)
        return {
            "device_id": device.id,
            "device_name": device.name,
            "kind": device.kind,
            "user": user.name,
            # Satu-satunya tempat kunci mentah pernah muncul.
            "api_key": raw_key,
        }

    @http.route("/lgx/api/device/ping", type="json", auth="bearer", methods=["POST"],
                csrf=False, save_session=False)
    def ping_device(self, device_id=None, **kwargs):
        """Tandai perangkat masih hidup. Dipakai PWA untuk memeriksa kunci masih sah."""
        device = request.env["lgx.api.device"].sudo().browse(int(device_id or 0)).exists()
        if device and device.user_id == request.env.user and device.state == "active":
            device.lgx_touch(request.httprequest.headers.get(
                "X-Forwarded-For", request.httprequest.remote_addr))
            return {"ok": True, "user": request.env.user.name, "device": device.name}
        return {"ok": False}
