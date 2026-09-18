# -*- coding: utf-8 -*-
"""What a document inherits to hold a file it does not store.

The document keeps a key. The URL is computed, short-lived, and never written down --
which is the whole difference between a reference and a standing grant. A pasted link
cannot be stored here at all, and that is deliberate: a pasted link is exactly what
rots, and it rots at the moment a dispute needs it.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ObjectStorageMixin(models.AbstractModel):
    _name = "custom.object.storage.mixin"
    _description = "Object Storage Reference"

    storage_key = fields.Char(
        string="Object Key",
        copy=False,
        help="Where the file lives in the bucket. The record keeps this; it never keeps "
        "a URL, because a URL that outlives the record's access rules is a hole in them.",
    )
    storage_url = fields.Char(
        string="Link",
        compute="_compute_storage_url",
        help="Signed on read and valid for minutes. Refreshing the page issues a new one; "
        "copying it out gains nothing for long.",
    )
    has_storage_file = fields.Boolean(compute="_compute_storage_url")

    def _storage_key_parts(self) -> list:
        """What the key should say. Overridden by whoever inherits this.

        A default of model and id would work and would tell nobody anything when read
        out of the bucket, so subclasses are expected to do better.
        """
        self.ensure_one()
        return [self._name.replace(".", "_"), self.id]

    @api.depends("storage_key")
    def _compute_storage_url(self):
        Storage = self.env["custom.object.storage"]
        for rec in self:
            rec.has_storage_file = bool(rec.storage_key)
            if not rec.storage_key:
                rec.storage_url = False
                continue
            try:
                rec.storage_url = Storage.presign_get(rec.storage_key)["url"]
            except Exception:  # noqa: BLE001
                # A missing configuration must not make every record unreadable; the
                # field simply has nothing to offer until storage is set up.
                rec.storage_url = False

    def action_request_upload(self, filename=None):
        """Issue a URL the caller uploads to, and remember where it will land.

        Called at the moment of upload, never earlier. A device that queued this while
        offline and asked for the URL then would come back to an expired one two hours
        later and fail without saying why.
        """
        self.ensure_one()
        Storage = self.env["custom.object.storage"]
        key = Storage.build_key(*self._storage_key_parts(), filename or "file")
        out = Storage.presign_put(key)
        self.storage_key = out["key"]
        return out

    def action_clear_storage(self):
        """Forget the reference. Does not delete the object.

        Deleting from the bucket is not this method's business: the file may be evidence,
        and a record being tidied is not a reason to destroy it. Bucket lifecycle rules
        are the right tool, applied deliberately.
        """
        for rec in self:
            if not rec.storage_key:
                raise UserError(_("Nothing is attached to %s.", rec.display_name))
            rec.storage_key = False
        return True
