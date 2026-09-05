# -*- coding: utf-8 -*-
"""Local mirror of master-DB ``tenant_registry.tenants`` — refreshed by cron.

Source of truth is the orchestrator (master DB). This model exists so:
  1. We can use Odoo views/actions over it (Odoo can't easily list rows
     from a different Postgres DB in the same model).
  2. CSMs can search/filter/sort + open per-tenant dashboards.

The model is **never written to** by the UI directly — write paths go
through ``custom.super.admin.orchestrator.client`` which calls the
orchestrator API; the cron then refreshes this mirror.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class TenantRegistry(models.Model):
    _name = "tenant.registry"
    _description = "Tenant Registry (mirror of master DB tenant_registry.tenants)"
    _inherit = ["mail.thread"]
    _order = "state, slug"

    slug = fields.Char(required=True, index=True, copy=False)
    # `display_name` is a reserved magic field on models.Model (computed,
    # non-stored). A bare override inherits compute/store=False, so the column
    # is never created and search_read order='display_name' fails in SQL.
    # Force a real stored column — required for the CSM list sort/filter and
    # the hub-portal BFF (/api/tenants orders by display_name).
    display_name = fields.Char(required=True, store=True, compute=False)
    db_name = fields.Char(required=True)
    state = fields.Selection(
        [
            ("provisioning", "Provisioning"),
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("archived", "Archived"),
            ("failed", "Failed"),
        ],
        required=True,
        default="provisioning",
        index=True,
    )
    #: `plan_code`, matching the registry column and the orchestrator's JSON.
    #: It was `plan_tier` here, and the orchestrator has never returned a key by
    #: that name -- `TENANT_COLUMNS` publishes `plan_code`. `r.get("plan_tier")`
    #: therefore evaluated to None on every sync since this mirror was written,
    #: so the console's Plan column was blank for every tenant and its
    #: "Group by Plan" put all of them in one nameless bucket. Measured
    #: 2026-09-05: three tenants, three empty values, three real plan codes
    #: sitting in the registry the whole time.
    plan_code = fields.Char(string="Paket")
    contact_email = fields.Char()
    contact_phone = fields.Char()
    csm_user_id = fields.Many2one("res.users", string="CSM")

    activated_at = fields.Datetime()
    suspended_at = fields.Datetime()
    archived_at = fields.Datetime()
    purge_after = fields.Datetime()
    last_seen_at = fields.Datetime()

    last_backup_at = fields.Datetime()
    last_backup_size_bytes = fields.Integer()
    last_backup_id = fields.Char()

    features = fields.Json()
    notes = fields.Text()
    sync_error = fields.Text(help="Last error returned by the orchestrator for an action on this tenant")

    # Backup scheduling / replication (Track D)
    backup_schedule = fields.Char(
        default="0 2 * * *",
        help="Standard 5-field cron expression for scheduled backups (UTC). Default: daily at 02:00 UTC.",
    )
    backup_retention_days = fields.Integer(
        default=30,
        help="How many days to retain backups before they are eligible for pruning.",
    )
    pitr_enabled = fields.Boolean(
        default=False,
        help="Point-in-time-recovery toggle (uses WAL archiving when enabled).",
    )
    last_scheduled_backup_at = fields.Datetime(
        readonly=True,
        help="Timestamp of the most recent backup triggered by the scheduler.",
    )

    _slug_uniq = models.Constraint(
        "unique(slug)",
        "Tenant slug must be unique.",
    )

    # --------------------------------------------------------------
    # Cron + sync
    # --------------------------------------------------------------

    @api.model
    def _cron_sync_from_orchestrator(self) -> None:
        try:
            rows = self.env["custom.super.admin.orchestrator.client"].sudo().list_tenants()
        except Exception as e:
            _logger.warning("tenant.registry.sync_failed: %s", e)
            return
        self._upsert_many(rows)

    @api.model
    def _upsert_many(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        existing = {r.slug: r for r in self.sudo().search([])}
        seen: set[str] = set()
        for r in rows:
            slug = r["slug"]
            seen.add(slug)
            vals = {
                "slug": slug,
                "display_name": r["display_name"],
                "db_name": r["db_name"],
                "state": r["state"],
                "plan_code": r.get("plan_code"),
                "contact_email": r.get("contact_email"),
                "last_backup_at": self._to_dt(r.get("last_backup_at")),
                "activated_at": self._to_dt(r.get("activated_at")),
                "suspended_at": self._to_dt(r.get("suspended_at")),
                "archived_at": self._to_dt(r.get("archived_at")),
                "features": r.get("features") or {},
            }
            if slug in existing:
                existing[slug].sudo().write(vals)
            else:
                self.sudo().create(vals)

        # Slugs that disappeared from orchestrator → mark as archived locally.
        # (Hard-delete only if registry row gone for > 30d; left as future work.)
        stale = set(existing) - seen
        if stale:
            self.sudo().search([("slug", "in", list(stale))]).write({"state": "archived"})

    @staticmethod
    def _to_dt(value: Any) -> datetime | bool:
        if not value:
            return False
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        # ISO string from JSON
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return dt.replace(tzinfo=None)
        except ValueError:
            return False

    # --------------------------------------------------------------
    # Action buttons (called from form view)
    # --------------------------------------------------------------

    def action_open_provision_wizard(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Provision New Tenant"),
            "res_model": "tenant.provision.wizard",
            "view_mode": "form",
            "target": "new",
        }

    def action_suspend(self):
        self.ensure_one()
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            client.suspend(self.slug, reason="Manual suspend from super-admin UI")
        except Exception as e:
            raise UserError(_("Suspend failed: %s") % e) from e
        self._cron_sync_from_orchestrator()
        return self._notify("Suspended", f"Tenant '{self.slug}' suspended.")

    def action_resume(self):
        self.ensure_one()
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            client.resume(self.slug)
        except Exception as e:
            raise UserError(_("Resume failed: %s") % e) from e
        self._cron_sync_from_orchestrator()
        return self._notify("Resumed", f"Tenant '{self.slug}' resumed.")

    def action_archive(self):
        self.ensure_one()
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            client.archive(self.slug, retention_days=30)
        except Exception as e:
            raise UserError(_("Archive failed: %s") % e) from e
        self._cron_sync_from_orchestrator()
        return self._notify("Archived", f"Tenant '{self.slug}' archived (purge in 30d).")

    def action_trigger_backup(self):
        """Refuses here rather than after a signed round trip.

        `run_backup` POSTs to a route that answers 501 by design: the
        orchestrator has neither pg_dump nor the filestore, both deliberately.
        The operator used to see "Backup failed: Orchestrator POST ... 501",
        which reads like an outage rather than an answer.

        Backups are real. They run on the host, where the filestore is, and
        since 2026-09-05 the script records each one in
        `tenant_registry.backups`, so the list on this form fills in on the next
        mirror sync.
        """
        self.ensure_one()
        raise UserError(_(
            "Backups do not run from the console.\n\n"
            "A backup is pg_dump plus the filestore, and this platform's API "
            "service has neither -- on purpose: a service that could dump any "
            "client's database on request is a target, not a convenience.\n\n"
            "Run on the host:\n"
            "    make tenant-backup TENANT=%(slug)s\n\n"
            "It takes the database AND the filestore, writes a manifest and "
            "SHA256SUMS, and records the result here. The list on this form "
            "fills in at the next mirror sync (hourly)."
        ) % {"slug": self.slug or "<slug>"})

    def _action_trigger_backup_unreachable(self):
        # See tenant.restore.wizard._action_restore_unreachable: kept so the
        # shape of the call that WOULD be made stays visible.
        self.ensure_one()
        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            result = client.run_backup(self.slug, kind="manual")
        except Exception as e:
            raise UserError(_("Backup failed: %s") % e) from e
        self._cron_sync_from_orchestrator()
        self.env["tenant.backup"].sudo()._cron_sync_for(self.slug)
        return self._notify(
            "Backup OK",
            f"Backup completed: {result.get('path')} ({result.get('size_bytes')} bytes)",
        )

    def action_open_restore_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Restore Backup"),
            "res_model": "tenant.restore.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_tenant_id": self.id, "default_slug": self.slug},
        }

    def action_open_replicate_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Replicate to Staging"),
            "res_model": "tenant.replicate.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_source_tenant_id": self.id,
                "default_target_tenant_id": self.id,
            },
        }

    def action_open_grafana(self):
        self.ensure_one()
        base = self.env["ir.config_parameter"].sudo().get_param("custom_super_admin.grafana_base_url", "")
        if not base:
            raise UserError(_("Configure Grafana base URL under Settings."))
        url = f"{base.rstrip('/')}/d/tenant?var-db={self.db_name}"
        return {"type": "ir.actions.act_url", "url": url, "target": "new"}

    def action_view_backups(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Backups: %s") % self.slug,
            "res_model": "tenant.backup",
            "view_mode": "list,form",
            "domain": [("tenant_slug", "=", self.slug)],
        }

    def action_view_action_log(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Action Log: %s") % self.slug,
            "res_model": "tenant.action.log",
            "view_mode": "list",
            "domain": [("tenant_slug", "=", self.slug)],
        }

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------

    def _notify(self, title: str, message: str):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": "success",
                "sticky": False,
            },
        }
