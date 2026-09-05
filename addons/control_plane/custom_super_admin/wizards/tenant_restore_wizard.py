# -*- coding: utf-8 -*-
"""Wizard: restore a tenant backup to a (typically staging) DB."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class TenantRestoreWizard(models.TransientModel):
    _name = "tenant.restore.wizard"
    _description = "Restore a backup"

    tenant_id = fields.Many2one("tenant.registry", required=True, ondelete="cascade")
    slug = fields.Char(related="tenant_id.slug", readonly=True)
    backup_id = fields.Many2one(
        "tenant.backup",
        domain="[('tenant_id', '=', tenant_id), ('outcome', '=', 'success')]",
        required=True,
    )
    path = fields.Char(related="backup_id.path", readonly=True, string="Lokasi")
    target_db = fields.Char(
        help="Target DB name. Defaults to '<slug>_staging' which is safe (non-destructive against live tenant).",
    )

    confirm_destructive = fields.Boolean(
        string="I understand this is destructive",
        help="Required if target_db equals the live tenant db_name.",
    )

    @api.onchange("tenant_id")
    def _onchange_default_target(self):
        for rec in self:
            if rec.tenant_id and not rec.target_db:
                rec.target_db = f"{rec.tenant_id.slug}_staging"

    def action_restore(self):
        """Refuses here, on the form, instead of after a round trip.

        THIS BUTTON CALLED A ROUTE THAT DID NOT EXIST. `restore_backup` POSTs to
        `/v1/tenants/<slug>/backups/restore`, and the orchestrator had no such
        route: the call came back 404 and the operator was shown "Restore
        failed: Orchestrator POST ... 404", which reads like an outage and sends
        the next hour into a routing investigation.

        The route now answers 501 and names the host script, which is honest --
        but making the operator sign an HTTP request to be told the feature does
        not exist is still the wrong shape. The refusal belongs where the button
        is, before anything is sent, with the command that actually works.

        Restore is deliberately not an unattended HTTP operation in any case: it
        replaces a live database, and it needs the dump, the filestore and the
        SHA256SUMS, all of which live on the host and none of which this service
        can see. Delete this guard when restore genuinely runs from here.
        """
        self.ensure_one()
        raise UserError(_(
            "Restore does not run from the console.\n\n"
            "It needs the dump, the filestore and the SHA256SUMS, which are on "
            "the host; and it replaces a live database, which is not something "
            "to trigger from a form and walk away from.\n\n"
            "Run on the host:\n"
            "    scripts/tenant-restore.sh %(slug)s <backup-directory>\n\n"
            "The backup directory is the one named in the console listing, and "
            "the script verifies SHA256SUMS before it touches anything."
        ) % {"slug": self.slug or "<slug>"})

    def _action_restore_unreachable(self):
        # Kept, unreferenced, so the shape of the call that WOULD be made is
        # still visible to whoever wires this up for real. Deleting it would
        # mean rediscovering the argument names from the client module.
        self.ensure_one()
        if not self.backup_id:
            raise UserError(_("Pick a backup to restore."))
        target = (self.target_db or f"{self.slug}_staging").strip()
        if target == self.tenant_id.db_name and not self.confirm_destructive:
            raise UserError(
                _(
                    "Target DB equals the live tenant DB — tick the "
                    "destructive-action confirmation if this is intentional."
                )
            )
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            result = client.restore_backup(self.slug, s3_key=self.path, target_db=target)
        except Exception as e:
            raise UserError(_("Restore failed: %s") % e) from e
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Restore complete"),
                "message": _("Restored to DB '%s'.") % result.get("restored_to_db"),
                "type": "success",
                "sticky": True,
            },
        }
