# -*- coding: utf-8 -*-
"""Refresh tokens and idempotency records."""
import hashlib
import os
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied

ACCESS_TTL_DEFAULT = 900        # 15 minutes
REFRESH_TTL_DEFAULT = 28800     # 8 hours


class HmsApiToken(models.Model):
    """Opaque refresh tokens, stored hashed.

    Only the hash is kept: a database dump must not hand out live sessions.
    Access tokens are JWTs and are never stored at all.
    """
    _name = "hms.api.token"
    _description = "Refresh Token API"
    _order = "id desc"
    _log_access = False

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    token_hash = fields.Char(required=True, index=True)
    jti = fields.Char("ID Token", required=True, index=True)
    issued_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime(required=True, index=True)
    revoked = fields.Boolean(default=False, index=True)
    rotated_to_id = fields.Many2one("hms.api.token", "Digantikan Oleh", ondelete="set null")
    user_agent = fields.Char()
    ip_address = fields.Char()

    _hash_uniq = models.Constraint("unique(token_hash)", "Token sudah dipakai.")

    @api.model
    def _hash(self, raw):
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @api.model
    def issue(self, user, ttl=None, user_agent=None, ip=None):
        raw = secrets.token_urlsafe(48)
        ttl = ttl or int(os.environ.get("HMS_JWT_REFRESH_TTL", REFRESH_TTL_DEFAULT))
        record = self.sudo().create({
            "user_id": user.id,
            "token_hash": self._hash(raw),
            "jti": secrets.token_hex(8),
            "expires_at": fields.Datetime.add(fields.Datetime.now(), seconds=ttl),
            "user_agent": (user_agent or "")[:200],
            "ip_address": ip,
        })
        return raw, record

    @api.model
    def verify(self, raw):
        record = self.sudo().search([
            ("token_hash", "=", self._hash(raw)),
            ("revoked", "=", False),
            ("expires_at", ">", fields.Datetime.now()),
        ], limit=1)
        if not record:
            raise AccessDenied(_("Refresh token tidak berlaku."))
        return record

    def rotate(self, user_agent=None, ip=None):
        """Issue a successor and retire this one.

        Rotation on every refresh means a stolen refresh token is usable at
        most once before the legitimate client's next refresh invalidates it —
        and the resulting failure is visible.
        """
        self.ensure_one()
        raw, successor = self.issue(self.user_id, user_agent=user_agent, ip=ip)
        self.sudo().write({"revoked": True, "rotated_to_id": successor.id})
        return raw, successor

    def revoke(self):
        self.sudo().write({"revoked": True})
        return True

    @api.model
    def _gc(self):
        expired = self.sudo().search([("expires_at", "<", fields.Datetime.now())])
        count = len(expired)
        expired.unlink()
        return count


class HmsApiIdempotency(models.Model):
    _name = "hms.api.idempotency"
    _description = "Kunci Idempotency API"
    _order = "id desc"
    _log_access = False

    key = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    endpoint = fields.Char(required=True, index=True)
    request_hash = fields.Char(required=True)
    response_body = fields.Text()
    status_code = fields.Integer(default=200)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    expires_at = fields.Datetime(required=True, index=True)

    _key_uniq = models.Constraint(
        "unique(key, user_id, endpoint)",
        "Kunci idempotency sudah dipakai untuk endpoint ini.",
    )

    @api.model
    def lookup(self, key, endpoint, request_hash):
        """Return a stored response, or explain why the key cannot be reused."""
        if not key:
            return None
        record = self.sudo().search([
            ("key", "=", key), ("user_id", "=", self.env.uid), ("endpoint", "=", endpoint),
            ("expires_at", ">", fields.Datetime.now()),
        ], limit=1)
        if not record:
            return None
        if record.request_hash != request_hash:
            # Same key, different body: the client has a bug, and silently
            # returning the old answer would hide it.
            return {"conflict": True}
        return {"body": record.response_body, "status": record.status_code}

    @api.model
    def remember(self, key, endpoint, request_hash, body, status=200, ttl_hours=24):
        if not key:
            return False
        return self.sudo().create({
            "key": key,
            "user_id": self.env.uid,
            "endpoint": endpoint,
            "request_hash": request_hash,
            "response_body": body,
            "status_code": status,
            "expires_at": fields.Datetime.add(fields.Datetime.now(), hours=ttl_hours),
        })

    @api.model
    def _gc(self):
        expired = self.sudo().search([("expires_at", "<", fields.Datetime.now())])
        count = len(expired)
        expired.unlink()
        return count
