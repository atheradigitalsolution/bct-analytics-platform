# -*- coding: utf-8 -*-
"""Bucket coordinates, and the two secrets a bucket needs.

``custom.adapter.config`` gives one ``credential_ref``, which is enough for an HMAC or
bearer adapter and one short of what S3 needs: an access key id and a secret. The id is
not a secret -- it appears in every signed URL in plain sight -- so it lives on the
config, and only the secret goes through ``ir.config_parameter``.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CustomAdapterConfig(models.Model):
    _inherit = "custom.adapter.config"

    x_s3_bucket = fields.Char(string="Bucket")
    x_s3_region = fields.Char(
        string="Region",
        default="auto",
        help="Cloudflare R2 signs with the literal region 'auto'. Other S3 providers "
        "want a real one, which is why this is not hard-coded.",
    )
    x_s3_access_key_id = fields.Char(
        string="Access Key ID",
        help="Not a secret: it is visible in every signed URL this produces. The secret "
        "half goes in credential_ref, which is read from ir.config_parameter.",
    )
    x_s3_public_base_url = fields.Char(
        string="Public Base URL",
        help="Optional. Set only for objects that are genuinely public; leaving it empty "
        "means every read goes through a short-lived signed URL, which is the safer "
        "default and the one this module is built around.",
    )
    x_s3_default_expiry_s = fields.Integer(
        string="URL Expiry (s)",
        default=900,
        help="Fifteen minutes. Long enough for a slow upload on a workshop connection, "
        "short enough that a leaked URL is not a standing grant.",
    )

    @api.constrains("adapter_type", "x_s3_bucket", "x_s3_access_key_id", "base_url",
                    "x_s3_default_expiry_s")
    def _check_s3_config(self):
        for rec in self:
            if rec.adapter_type != "s3_compatible":
                continue
            missing = [
                label for label, value in (
                    (_("bucket"), rec.x_s3_bucket),
                    (_("access key id"), rec.x_s3_access_key_id),
                    (_("endpoint (base_url)"), rec.base_url),
                    (_("credential reference"), rec.credential_ref),
                ) if not value
            ]
            if missing:
                raise ValidationError(
                    _("Object storage needs %(fields)s before it can sign anything.",
                      fields=", ".join(missing))
                )
            if rec.x_s3_default_expiry_s <= 0:
                raise ValidationError(
                    _("A URL that expires immediately, or never, is not a pre-signed URL."))
            if rec.x_s3_default_expiry_s > 7 * 24 * 3600:
                raise ValidationError(
                    _("S3 refuses a pre-signed URL valid for more than seven days, and a "
                      "week is already a standing grant rather than a link."))
