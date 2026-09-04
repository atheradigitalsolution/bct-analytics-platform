# -*- coding: utf-8 -*-
"""Wizard: provision a new tenant via the orchestrator API."""

from __future__ import annotations

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Keep this pattern byte-for-byte identical to the three layers downstream: the
# orchestrator's request validation, the ``athera.provisioner`` model, and the
# CHECK constraint on the tenant table. A looser pattern here does not buy
# flexibility -- it only defers the rejection. The operator fills in the wizard,
# the HTTP call goes out, and the slug is refused somewhere deep in the
# provisioning chain (or worse, by the database, after side effects have already
# started). The resulting error surfaces far from the field that caused it and
# reads like an orchestrator outage rather than a typo. Failing here, on the
# form, is the whole point of validating in the wizard.
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

# Subdomain labels the platform has already claimed in the edge configuration
# (each has its own Caddy site block). A tenant slug becomes a subdomain, so a
# tenant named after one of these would hijack an existing platform route and
# shadow a core service for every user. This is NOT about database name
# collisions -- those are guarded elsewhere. The same set is enforced by the
# orchestrator and by the ``athera.provisioner`` model; keep the three copies in
# sync, and keep this one as a plain literal so a diff between layers is easy.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "app",
        "auth",
        "insight",
        "mail",
        "odoo",
        "www",
    }
)

# Written into ``admin_password`` when the orchestrator reports success but does
# not hand back a password. Silently leaving the field blank is exactly the bug
# this wizard is being fixed for, so make the gap impossible to mistake for
# "nothing was generated".
NO_PASSWORD_SENTINEL = "!! NOT RETURNED BY ORCHESTRATOR - RESET MANUALLY BEFORE HANDOVER !!"


class TenantProvisionWizard(models.TransientModel):
    _name = "tenant.provision.wizard"
    _description = "Provision a new tenant"

    slug = fields.Char(
        required=True,
        help="Lowercase identifier 2-31 chars (letters/digits/underscore, "
        "must start with a letter). Will also be the DB name and the "
        "subdomain (e.g. acme → acme.platform.localhost).",
    )
    display_name = fields.Char(required=True)
    plan_tier = fields.Selection(
        [("trial", "Trial"), ("standard", "Standard"), ("enterprise", "Enterprise")],
        default="standard",
        required=True,
    )
    contact_email = fields.Char()
    contact_phone = fields.Char()
    csm_user_id = fields.Many2one("res.users", string="CSM", default=lambda self: self.env.user)
    backup_schedule_cron = fields.Char(default="0 2 * * *", help="Standard 5-field cron expression.")
    feature_pajakku = fields.Boolean(string="Enable Pajakku Coretax adapter", default=False)
    feature_marketplace = fields.Boolean(string="Enable marketplace vertical", default=False)
    install_modules_extra = fields.Char(
        string="Additional modules",
        help="Comma-separated list of extra module names to install beyond the default set.",
    )

    # Output (read-only after run)
    admin_password = fields.Char(readonly=True)
    fernet_key_dek = fields.Char(readonly=True)
    run_done = fields.Boolean(readonly=True)
    # Filled in when the post-provision refresh of the local registry mirror
    # failed. Provisioning itself has already succeeded by then, so this is a
    # warning and not an error: it exists so the failure reaches the operator's
    # screen instead of living only in the server log. Rendered as a banner on
    # the wizard form right under the credentials.
    sync_warning = fields.Text(readonly=True)

    @api.constrains("slug")
    def _check_slug(self):
        for rec in self:
            if not rec.slug:
                continue
            if not SLUG_RE.match(rec.slug):
                raise ValidationError(
                    _("Slug must match %s (lowercase letters/digits/underscore, start with a letter, length 2-31).")
                    % SLUG_RE.pattern
                )
            if rec.slug in RESERVED_SLUGS:
                raise UserError(
                    _(
                        "Slug '%(slug)s' is reserved by the platform. The slug becomes the "
                        "tenant's subdomain, and this label already has its own site block on "
                        "the edge proxy, so a tenant using it would hijack a platform route "
                        "and shadow a core service for everyone. Reserved labels: %(reserved)s. "
                        "Pick a different slug (this is not a database name conflict -- that is "
                        "checked separately)."
                    )
                    % {"slug": rec.slug, "reserved": ", ".join(sorted(RESERVED_SLUGS))}
                )

    def _merge_install_modules(self, modules, payload):
        """Hook for downstream modules to merge extra module sets into the
        provisioning install list. ``custom_hub_console`` overrides this to add
        the selected industry pack's modules. Base implementation is a no-op."""
        return modules

    def action_provision(self):
        self.ensure_one()
        payload = {
            "slug": self.slug,
            "display_name": self.display_name,
            "plan_tier": self.plan_tier,
            "contact_email": self.contact_email or None,
            "contact_phone": self.contact_phone or None,
            "csm_user_id": self.csm_user_id.id if self.csm_user_id else None,
            "features": {
                "pajakku": self.feature_pajakku,
                "marketplace": self.feature_marketplace,
            },
            "backup_schedule_cron": self.backup_schedule_cron or None,
        }

        # Default platform module set (mirrors DEFAULT_TENANT_MODULES on the
        # orchestrator). This list is a deliberate choice, not a placeholder, so
        # it is always sent -- previously it was only transmitted when a pack or
        # extra modules widened it, which meant the plain case silently fell
        # through to the orchestrator's own fallback set.
        from_defaults = [
            "custom_core",
            "custom_currency_nbsp",
            "custom_ai_bridge",
            "custom_pdp_taxonomy",
            "custom_pdp_audit",
            "custom_pdp_consent",
            "custom_pdp_dsar",
            "custom_pdp_masking",
            "custom_pdp_retention",
            "custom_coretax",
        ]
        modules = list(from_defaults)
        # Hook: custom_hub_console merges industry-pack modules here. Kept as a
        # hook so super_admin carries no dependency on custom_hub_console (which
        # depends on super_admin — the reverse would break registry load order).
        modules = self._merge_install_modules(modules, payload)
        extra = (self.install_modules_extra or "").strip()
        if extra:
            modules += [m.strip() for m in extra.split(",") if m.strip()]
        # De-dup, order-preserving (defaults first, then pack deps-first, then extras).
        # The API body key is "modules" -- that is what the orchestrator reads.
        # ``install_modules_extra`` / ``_merge_install_modules`` are internal
        # names and intentionally differ from the wire key.
        seen = set()
        payload["modules"] = [m for m in modules if not (m in seen or seen.add(m))]

        client = self.env["custom.super.admin.orchestrator.client"].sudo()
        try:
            result = client.provision(payload)
        except Exception as e:
            raise UserError(_("Provision failed: %s") % e) from e

        # Mirror result back so ops can capture credentials ONCE.
        #
        # The orchestrator generates the admin password when the request does not
        # carry one and returns it here; an empty value therefore means the
        # credential was lost, not that none exists. We do NOT raise in that case:
        # the tenant has already been created on the other side, and an exception
        # would roll back this transaction (losing the wizard result and skipping
        # the registry sync) without undoing the remote provisioning. Instead we
        # log loudly and park a sentinel in the field, so the operator sees that
        # something is wrong rather than an ambiguous blank box.
        #
        # ``fernet_key_dek`` is allowed to be absent by contract, so it gets no
        # sentinel -- only a normalised empty value.
        admin_password = result.get("admin_password") or ""
        if not admin_password:
            _logger.error(
                "provision.no_admin_password slug=%s: orchestrator reported success but "
                "returned no admin_password; response keys=%s",
                self.slug,
                sorted(result.keys()) if isinstance(result, dict) else type(result).__name__,
            )
            admin_password = NO_PASSWORD_SENTINEL

        self.write(
            {
                "admin_password": admin_password,
                "fernet_key_dek": result.get("fernet_key_dek") or False,
                "run_done": True,
            }
        )

        # Refresh the local registry mirror so the new tenant shows up in the
        # list right away instead of only after the next cron run.
        #
        # This runs AFTER the credentials have been written, and it must not be
        # able to destroy them -- the tenant already exists on the orchestrator,
        # so a local failure undoes nothing remotely while a rollback here would
        # blank out credentials that can never be read back. Two failure modes
        # matter, and they need different protection:
        #   * a plain Python error raised inside the sync -- ``_upsert_many``
        #     choking on a malformed row, a ValidationError, a KeyError on a
        #     field the orchestrator did not send;
        #   * a database error (unique-slug violation, deadlock, serialization
        #     failure), which additionally leaves the PostgreSQL transaction in
        #     the aborted state where every later statement fails.
        # A bare ``try/except`` only covers the first: after a DB error the
        # transaction is already poisoned, and the COMMIT at the end of the
        # request degrades into a ROLLBACK that takes the credentials with it.
        # A SAVEPOINT covers both -- rolling back to it discards whatever the
        # sync touched and hands back a usable connection, while everything
        # written before it survives.
        #
        # ``cr.savepoint()`` flushes pending ORM writes before issuing the
        # SAVEPOINT, so the credential ``write`` above is already in the
        # database by the time the savepoint is taken; the explicit
        # ``flush_all()`` only makes that ordering obvious to the next reader.
        # Rolling back also clears the ORM cache, which is why the warning is
        # written after the block rather than inside it.
        #
        # Deliberately NOT ``env.cr.commit()``. It would buy nothing here: the
        # request commits on its own way out, so with the savepoint in place the
        # credentials are durable either way. What it would cost is the
        # atomicity of the request -- any later failure would leave a
        # half-applied state the framework can no longer unwind, test cursors
        # and queue-job workers treat a manual commit as an error, and the
        # environment has to be treated as stale afterwards. The only extra
        # window a commit would close is the worker dying between the write and
        # the end of the request, and in that case the operator never receives
        # the response carrying the credentials anyway.
        sync_warning = False
        self.env.flush_all()
        try:
            with self.env.cr.savepoint():
                self.env["tenant.registry"].sudo()._cron_sync_from_orchestrator()
        except Exception as e:
            # Caught, never swallowed: the full traceback goes to the server log
            # and a summary goes on screen. The operator has to know the tenant
            # is real even though the list may not show it yet.
            _logger.exception(
                "provision.registry_sync_failed slug=%s: tenant was created on the "
                "orchestrator and its credentials were kept, but refreshing the "
                "local tenant.registry mirror failed",
                self.slug,
            )
            sync_warning = _(
                "The tenant was created and the credentials above are valid, but "
                "refreshing the local tenant list failed (%(error)s: %(message)s). "
                "The tenant may be missing from the list until the periodic "
                "registry sync cron runs again (every 15 minutes by default), "
                "which you can also trigger by hand. Do NOT provision it again -- "
                "it exists already and a second attempt will be rejected on the "
                "duplicate slug."
            ) % {"error": type(e).__name__, "message": e}

        if sync_warning:
            self.write({"sync_warning": sync_warning})

        # Re-open the same wizard form so admin_password is visible
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(self.env.context, form_view_initial_mode="readonly"),
        }
