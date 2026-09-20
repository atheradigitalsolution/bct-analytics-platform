# -*- coding: utf-8 -*-
"""BPJS connection settings, read from the environment."""
import os

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsBpjsConfig(models.Model):
    _name = "hms.bpjs.config"
    _description = "Konfigurasi BPJS"

    name = fields.Char(default="BPJS Kesehatan", required=True)
    mode = fields.Selection(
        [("mock", "Mock (demo)"), ("sandbox", "Sandbox"), ("prod", "Produksi")],
        compute="_compute_from_env", string="Mode",
    )
    vclaim_base_url = fields.Char(compute="_compute_from_env", string="URL VClaim")
    antrol_base_url = fields.Char(compute="_compute_from_env", string="URL Antrean")
    cons_id_set = fields.Boolean(compute="_compute_from_env", string="Cons ID terisi")
    secret_set = fields.Boolean(compute="_compute_from_env", string="Secret Key terisi")
    user_key_vclaim_set = fields.Boolean(compute="_compute_from_env")
    user_key_antrol_set = fields.Boolean(compute="_compute_from_env")
    ppk_code = fields.Char(compute="_compute_from_env", string="Kode PPK")

    def _compute_from_env(self):
        """Secrets live in the process environment, never in the database.

        The form shows only whether each value is present. A settings screen
        that displays a consumer secret is a settings screen that leaks one
        through a screenshot.
        """
        for rec in self:
            rec.mode = os.environ.get("BPJS_MODE", "mock")
            rec.vclaim_base_url = os.environ.get(
                "BPJS_BASE_URL", "http://mock-bridging:4010/bpjs"
            )
            rec.antrol_base_url = os.environ.get(
                "BPJS_ANTROL_BASE_URL", rec.vclaim_base_url.replace("/bpjs", "/bpjs/antrean")
            )
            rec.cons_id_set = bool(os.environ.get("BPJS_CONS_ID"))
            rec.secret_set = bool(os.environ.get("BPJS_SECRET_KEY"))
            rec.user_key_vclaim_set = bool(os.environ.get("BPJS_USER_KEY_VCLAIM"))
            rec.user_key_antrol_set = bool(os.environ.get("BPJS_USER_KEY_ANTROL"))
            rec.ppk_code = os.environ.get("BPJS_PPK_CODE", "0000000000")

    @api.model
    def credentials(self, service="vclaim"):
        """Return the credentials for one service, or explain what is missing."""
        mode = os.environ.get("BPJS_MODE", "mock")
        cons_id = os.environ.get("BPJS_CONS_ID", "")
        secret = os.environ.get("BPJS_SECRET_KEY", "")
        user_key = os.environ.get(
            "BPJS_USER_KEY_ANTROL" if service == "antrol" else "BPJS_USER_KEY_VCLAIM", ""
        )
        if mode != "mock" and not all((cons_id, secret, user_key)):
            raise UserError(
                _("Kredensial BPJS untuk layanan %(s)s belum lengkap. Isi BPJS_CONS_ID, "
                  "BPJS_SECRET_KEY dan user key di environment, atau jalankan dengan "
                  "BPJS_MODE=mock untuk demo.") % {"s": service}
            )
        # Mock mode still needs non-empty values so the signature code path is
        # exercised exactly as it will be in production.
        return {
            "mode": mode,
            "cons_id": cons_id or "DEMO-CONS",
            "secret_key": secret or "DEMO-SECRET",
            "user_key": user_key or "DEMO-USERKEY",
            "ppk_code": os.environ.get("BPJS_PPK_CODE", "0000000000"),
            "base_url": (
                os.environ.get("BPJS_ANTROL_BASE_URL")
                if service == "antrol"
                else os.environ.get("BPJS_BASE_URL")
            ) or "http://mock-bridging:4010/bpjs",
        }

    @api.model
    def action_open_settings(self):
        config = self.search([], limit=1) or self.create({})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": config.id,
            "view_mode": "form",
            "target": "new",
        }
