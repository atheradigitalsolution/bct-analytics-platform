# -*- coding: utf-8 -*-
"""The adapter Odoo code actually calls."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.custom_adapter_framework.models.adapter_base import AdapterResponse, BaseAdapter
from odoo.addons.custom_adapter_framework.models.adapter_registry import register_adapter

from .s3_presign import expiry_of, presign

_logger = logging.getLogger(__name__)


@register_adapter("s3_compatible")
class S3CompatibleAdapter(BaseAdapter):
    """Pre-signs URLs. Deliberately does not move bytes.

    The framework's ``call()`` is left alone: an adapter that proxied uploads would put
    every photograph through the application server, which is the one thing this design
    exists to avoid.
    """

    def health_check(self) -> AdapterResponse:
        """Can this configuration sign at all.

        Checks the coordinates and the secret, and produces a signature for a throwaway
        key. It does NOT reach the network: a health check that needs the internet fails
        for reasons that have nothing to do with the configuration being wrong, and then
        gets ignored.
        """
        cfg = self.config
        secret = self._get_secret()
        if not secret:
            return AdapterResponse(ok=False, status_code=0, data={},
                                   error="no secret at %s" % (cfg.credential_ref or "-"))
        try:
            self.presign_get("__healthcheck__", expires=60)
        except Exception as exc:  # noqa: BLE001
            return AdapterResponse(ok=False, status_code=0, data={}, error=str(exc))
        return AdapterResponse(ok=True, status_code=200, data={"bucket": cfg.x_s3_bucket})

    # ------------------------------------------------------------------

    def _host_and_prefix(self) -> tuple[str, str]:
        """R2 addresses the bucket in the path; some providers use a subdomain.

        Derived from the configured endpoint rather than assumed, because getting this
        wrong produces a signature that verifies against a URL nobody serves.
        """
        cfg = self.config
        parsed = urlparse(cfg.base_url or "")
        host = parsed.netloc or parsed.path
        if not host:
            raise UserError(_("Object storage endpoint is not a URL: %s", cfg.base_url))
        bucket = (cfg.x_s3_bucket or "").strip("/")
        if host.startswith(f"{bucket}."):
            return host, ""
        return host, bucket

    def _sign(self, method: str, key: str, expires: int | None = None) -> dict:
        cfg = self.config
        host, prefix = self._host_and_prefix()
        expires = expires or cfg.x_s3_default_expiry_s or 900
        full_key = f"{prefix}/{key.lstrip('/')}" if prefix else key.lstrip("/")
        now = fields.Datetime.now().replace(tzinfo=None)
        from datetime import timezone as _tz
        now = now.replace(tzinfo=_tz.utc)
        url = presign(
            method=method,
            host=host,
            key=full_key,
            access_key=cfg.x_s3_access_key_id or "",
            secret_key=self._get_secret(),
            region=cfg.x_s3_region or "auto",
            expires=expires,
            now=now,
        )
        return {
            "url": url,
            "key": key.lstrip("/"),
            "method": method.upper(),
            "expires_in": expires,
            # Returned explicitly, not implied. An offline queue has to be able to ask
            # "is this URL still worth spending an upload on" before it tries.
            "expires_at": expiry_of(expires, now).isoformat(),
        }

    def presign_put(self, key: str, expires: int | None = None) -> dict:
        """A URL the device uploads to. Request it at flush time, never at enqueue time."""
        return self._sign("PUT", key, expires)

    def presign_get(self, key: str, expires: int | None = None) -> dict:
        """A URL the browser reads from, valid for minutes rather than forever."""
        return self._sign("GET", key, expires)


class CustomObjectStorage(models.AbstractModel):
    """The entry point the rest of the platform uses.

    An abstract model rather than a mixin on every document: callers want a URL for a
    key, not an object-storage concern woven through their own model.
    """

    _name = "custom.object.storage"
    _description = "Object Storage Service"

    @api.model
    def _config(self, company=None):
        company = company or self.env.company
        cfg = company.x_object_storage_config_id
        if not cfg:
            cfg = self.env["custom.adapter.config"].sudo().search(
                [("adapter_type", "=", "s3_compatible"), ("status", "=", "active")], limit=1)
        if not cfg:
            raise UserError(
                _("No object storage is configured. Photographs are held outside the "
                  "filestore here, so there is nowhere to put one until it is."))
        return cfg

    @api.model
    def _adapter(self, company=None):
        from odoo.addons.custom_adapter_framework.models.adapter_registry import get_adapter_class
        cfg = self._config(company)
        klass = get_adapter_class(cfg.adapter_type)
        if not klass:
            raise UserError(_("Adapter %s is not registered.", cfg.adapter_type))
        return klass(cfg)

    @api.model
    def presign_put(self, key: str, expires: int | None = None, company=None) -> dict:
        return self._adapter(company).presign_put(key, expires)

    @api.model
    def presign_get(self, key: str, expires: int | None = None, company=None) -> dict:
        return self._adapter(company).presign_get(key, expires)

    @api.model
    def build_key(self, *parts) -> str:
        """A key that says what the object is without needing the database to explain it.

        Keys are flat strings in a bucket, so the only structure they ever have is the
        one put in them deliberately. A key like ``spk/SPK-2026-0001/survey/front.jpg``
        survives an export, a migration and somebody browsing the bucket by hand.
        """
        cleaned = []
        for part in parts:
            text = str(part or "").strip().strip("/").replace(" ", "_")
            # Slashes inside a part would invent directory levels nobody intended.
            cleaned.append(text.replace("/", "-"))
        return "/".join(p for p in cleaned if p)
