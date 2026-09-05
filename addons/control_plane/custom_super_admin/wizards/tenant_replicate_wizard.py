# -*- coding: utf-8 -*-
"""Wizard: replicate a tenant DB into another environment (staging/dev).

Pulls the latest (or selected) backup of ``source_tenant`` and restores it
into the ``target_tenant`` DB on ``target_env_type``. Backed by the
orchestrator endpoint ``POST /v1/backups/{backup_id}/replicate``.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError


ENV_TYPES = [("prod", "Production"), ("staging", "Staging"), ("dev", "Development")]


class TenantReplicateWizard(models.TransientModel):
    _name = "tenant.replicate.wizard"
    _description = "Replicate a tenant DB to another environment"

    source_tenant_id = fields.Many2one(
        "tenant.registry",
        string="Source Tenant",
        required=True,
        ondelete="cascade",
    )
    source_env_type = fields.Selection(
        ENV_TYPES,
        string="Source Env",
        required=True,
        default="prod",
    )
    target_tenant_id = fields.Many2one(
        "tenant.registry",
        string="Target Tenant",
        required=True,
        ondelete="cascade",
        help="Usually the same slug as source — only the env_type differs.",
    )
    target_env_type = fields.Selection(
        ENV_TYPES,
        string="Target Env",
        required=True,
        default="staging",
    )
    latest_backup_only = fields.Boolean(
        default=True,
        help="If set, replicate the most recent successful backup of source.",
    )
    backup_id = fields.Many2one(
        "tenant.backup",
        string="Specific Backup",
        domain="[('tenant_id', '=', source_tenant_id), ('outcome', '=', 'success')]",
        help="Required if 'latest backup only' is unchecked.",
    )
    notes = fields.Text()

    @api.constrains("source_tenant_id", "target_tenant_id", "source_env_type", "target_env_type")
    def _check_distinct(self):
        for rec in self:
            if rec.source_tenant_id == rec.target_tenant_id and rec.source_env_type == rec.target_env_type:
                raise UserError(_("Source and target cannot be the exact same tenant + environment."))

    def _resolve_backup(self):
        self.ensure_one()
        if self.latest_backup_only:
            backup = (
                self.env["tenant.backup"]
                .sudo()
                .search(
                    [
                        ("tenant_id", "=", self.source_tenant_id.id),
                        ("outcome", "=", "success"),
                    ],
                    order="started_at desc",
                    limit=1,
                )
            )
            if not backup:
                raise UserError(_("No successful backup found for source tenant %s.") % self.source_tenant_id.slug)
            return backup
        if not self.backup_id:
            raise UserError(_("Pick a specific backup or tick 'latest backup only'."))
        return self.backup_id

    def action_replicate(self):
        """Same refusal as restore, for the same reason.

        `replicate_backup` POSTs to `/v1/backups/<id>/replicate`, a route that
        did not exist and answered 404. Replication IS a restore into a different
        database, so it needs everything restore needs and can no more run from
        here than restore can.
        """
        self.ensure_one()
        raise UserError(_(
            "Replicating a backup into another tenant does not run from the "
            "console.\n\n"
            "It is a restore into a different database, so it needs the dump and "
            "the filestore on the host.\n\n"
            "Run on the host:\n"
            "    scripts/tenant-restore.sh %(target)s <backup-directory>\n\n"
            "against the target tenant's database."
        ) % {"target": (self.target_tenant_id.slug if self.target_tenant_id else "<target-slug>")})

    def _action_replicate_unreachable(self):
        # See the note on tenant.restore.wizard._action_restore_unreachable.
        self.ensure_one()
        backup = self._resolve_backup()
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            result = client.replicate_backup(
                backup_id=backup.master_id,
                target_tenant_slug=self.target_tenant_id.slug,
                target_env=self.target_env_type,
            )
        except Exception as e:
            raise UserError(_("Replicate failed: %s") % e) from e

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Replication complete"),
                "message": _("Restored backup %s into '%s' (%s env).")
                % (
                    backup.path or backup.master_id,
                    (result or {}).get("restored_to_db") or self.target_tenant_id.slug,
                    self.target_env_type,
                ),
                "type": "success",
                "sticky": True,
            },
        }
