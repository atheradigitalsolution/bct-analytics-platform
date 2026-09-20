# -*- coding: utf-8 -*-
"""Login, refresh, logout, profile."""
from odoo import _, http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .base import (API_ROOT, access_ttl, error_response, hms_route, json_response,
                   make_access_token, user_groups, _client_ip)


class HmsAuthController(http.Controller):

    @http.route(f"{API_ROOT}/auth/login", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/auth/login", auth_required=False)
    def login(self, body=None, **kw):
        login = (body or {}).get("login")
        password = (body or {}).get("password")
        if not (login and password):
            return error_response("validation_error", _("Login dan kata sandi wajib diisi."), 422)
        credential = {"login": login, "password": password, "type": "password"}
        try:
            # Verify through Odoo itself so password policy, 2FA hooks and
            # login throttling all still apply; the HTTP session it would
            # create is discarded immediately afterwards.
            uid = request.session.authenticate(request.env, credential)["uid"]
        except AccessDenied:
            return error_response("invalid_credentials", _("Login atau kata sandi salah."), 401)
        request.session.logout(keep_db=True)
        request.update_env(user=uid)
        user = request.env["res.users"].browse(uid)
        refresh_raw, _record = request.env["hms.api.token"].issue(
            user,
            user_agent=request.httprequest.headers.get("User-Agent"),
            ip=_client_ip(),
        )
        return {
            "access_token": make_access_token(user),
            "refresh_token": refresh_raw,
            "token_type": "Bearer",
            "expires_in": access_ttl(),
            "user": _user_payload(user),
        }

    @http.route(f"{API_ROOT}/auth/refresh", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/auth/refresh", auth_required=False)
    def refresh(self, body=None, **kw):
        raw = (body or {}).get("refresh_token")
        if not raw:
            return error_response("validation_error", _("Refresh token wajib dikirim."), 422)
        try:
            record = request.env["hms.api.token"].verify(raw)
        except AccessDenied:
            return error_response("invalid_token", _("Refresh token tidak berlaku."), 401)
        new_raw, _successor = record.rotate(
            user_agent=request.httprequest.headers.get("User-Agent"), ip=_client_ip()
        )
        request.update_env(user=record.user_id.id)
        user = record.user_id
        return {
            "access_token": make_access_token(user),
            "refresh_token": new_raw,
            "token_type": "Bearer",
            "expires_in": access_ttl(),
        }

    @http.route(f"{API_ROOT}/auth/logout", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/auth/logout", auth_required=False)
    def logout(self, body=None, **kw):
        raw = (body or {}).get("refresh_token")
        if raw:
            try:
                request.env["hms.api.token"].verify(raw).revoke()
            except AccessDenied:
                pass  # Already invalid: logging out is idempotent by nature.
        return {"ok": True}

    @http.route(f"{API_ROOT}/me", type="http", auth="public", methods=["GET"],
                csrf=False, save_session=False)
    @hms_route(f"{API_ROOT}/me")
    def me(self, body=None, **kw):
        return {"user": _user_payload(request.env.user)}


def _user_payload(user):
    practitioner = request.env["hms.practitioner"].sudo().search(
        [("user_id", "=", user.id)], limit=1
    )
    session = request.env["hms.cashier.session"].sudo().search([
        ("user_id", "=", user.id), ("state", "in", ("open", "closing")),
    ], limit=1)
    return {
        "id": user.id,
        "name": user.name,
        "login": user.login,
        "practitioner": {
            "id": practitioner.id,
            "name": practitioner.display_name,
            "type": practitioner.type,
            "units": practitioner.unit_ids.ids,
        } if practitioner else None,
        # Ejaan pendek, dari daftar tunggal di base.HMS_GROUPS — inilah yang
        # dipakai menu Next.js untuk menyembunyikan layar yang tak berguna.
        "groups": user_groups(user, short=True),
        "cashier_session_id": session.id or None,
    }
