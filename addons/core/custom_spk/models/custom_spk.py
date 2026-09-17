# -*- coding: utf-8 -*-
"""The SPK record: the one number every other document hangs off.

Deliberately carries no monetary field. The Account Executive works on this
model, and the requirement is not that prices are hidden from them but that
there is nothing here to hide. ``tests/test_price_fence.py`` asserts the absence
by introspection, so a Monetary field added later fails the suite instead of
quietly widening what the AE can read.
"""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Mirrors the lifecycle in the business process document. It is long because the
# job really does pass through these hands, and collapsing it would lose the
# distinction the shop floor actually reports against -- "in production" and
# "waiting for client sign-off" are not the same answer to "where is my booth".
SPK_STATES = [
    ("draft", "Draft Penawaran"),
    ("sent", "Penawaran Terkirim"),
    ("negotiation", "Negosiasi"),
    ("confirmed", "SPK Disetujui"),
    ("design", "Design In Progress"),
    ("design_review", "Menunggu Approval Klien"),
    ("design_approved", "Design Approved"),
    ("production", "Produksi"),
    ("qc", "QC & Packing"),
    ("ready", "Siap Kirim"),
    ("delivery", "Dalam Pengiriman"),
    ("installation", "Instalasi"),
    ("handover", "Terpasang / BAST"),
    ("invoiced", "Ditagih"),
    ("paid", "Lunas"),
    ("closed", "Closed"),
    ("lost", "Lost"),
]

# Past this point the job exists in the workshop, so the event data it was
# planned against stops being editable by the people who only read it.
LOCKED_FROM = "confirmed"


class CustomSpk(models.Model):
    _name = "custom.spk"
    _description = "Surat Perintah Kerja"
    _inherit = ["pdp.audited.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "event_date_start asc, id desc"
    _rec_name = "name"

    name = fields.Char(
        string="No. SPK",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    partner_id = fields.Many2one(
        "res.partner", string="Klien", required=True, tracking=True, index=True,
    )
    partner_contact_id = fields.Many2one(
        "res.partner", string="PIC Klien", domain="[('parent_id', '=', partner_id)]",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Account Executive",
        default=lambda self: self.env.user,
        tracking=True,
        index=True,
        help="The AE answerable for this job. Also what the AE record rule filters on: "
        "an AE sees the jobs they are named on and no others.",
    )
    project_id = fields.Many2one("project.project", string="Project", copy=False)
    analytic_account_id = fields.Many2one(
        "account.analytic.account",
        string="Analytic Account",
        copy=False,
        help="Where every cost booked against this job lands. Created with the SPK so "
        "that nothing downstream has to invent one.",
    )

    # ---- event, which is what makes the deadline immovable ----
    event_name = fields.Char(string="Nama Event", tracking=True)
    event_venue = fields.Char(string="Venue")
    event_date_start = fields.Date(string="Mulai Event", tracking=True)
    event_date_end = fields.Date(string="Selesai Event")
    booth_size = fields.Char(string="Ukuran Booth", help="e.g. 3x3, 6x9")
    booth_type = fields.Selection(
        [
            ("custom", "Custom Booth"),
            ("modular", "Modular"),
            ("mockup", "Mockup Produk"),
            ("display", "Display"),
        ],
        string="Jenis",
        default="custom",
    )
    source_type = fields.Selection(
        [
            ("direct", "Direct"),
            ("tender", "Tender"),
            ("referral", "Referral"),
            ("repeat", "Repeat Order"),
        ],
        string="Sumber",
        default="direct",
    )

    state = fields.Selection(SPK_STATES, default="draft", required=True, tracking=True, index=True)
    progress = fields.Float(
        string="Progres (%)",
        default=0.0,
        tracking=True,
        help="Reported by the supervisor, not derived. Deriving it from task counts "
        "would say the paperwork is done, not the booth.",
    )
    note = fields.Text(string="Catatan")
    active = fields.Boolean(default=True)

    # ---- risk, computed rather than remembered ----
    days_to_event = fields.Integer(
        string="Sisa Hari",
        compute="_compute_risk",
        store=True,
        help="Negative once the event has started.",
    )
    risk_level = fields.Selection(
        [("ok", "On Track"), ("watch", "Watch"), ("late", "At Risk")],
        string="Risiko",
        compute="_compute_risk",
        store=True,
    )

    _sql_constraints_name_uniq = models.Constraint(
        "unique(name)",
        "An SPK number is issued once.",
    )

    @api.depends("event_date_start", "progress", "state")
    def _compute_risk(self):
        """An event date does not move, so lateness is measurable rather than felt.

        The thresholds are the ones the business process document asks for: red
        when under a week remains and the job is not yet 70% done. Jobs already
        handed over or closed are not at risk of anything.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.event_date_start:
                rec.days_to_event = 0
                rec.risk_level = "ok"
                continue
            rec.days_to_event = (rec.event_date_start - today).days
            if rec.state in ("handover", "invoiced", "paid", "closed", "lost"):
                rec.risk_level = "ok"
            elif rec.days_to_event < 7 and rec.progress < 70.0:
                rec.risk_level = "late"
            elif rec.days_to_event < 14 and rec.progress < 50.0:
                rec.risk_level = "watch"
            else:
                rec.risk_level = "ok"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("custom.spk") or _("New")
        return super().create(vals_list)

    def action_confirm(self):
        """Issue the number's dependants: the project and the analytic account.

        Both are created here rather than by whoever needs them first, because
        the point of the SPK is that every cost has somewhere to land from the
        moment the job is approved -- not from the moment someone remembers.
        """
        for rec in self:
            if rec.state not in ("draft", "sent", "negotiation"):
                raise UserError(
                    _("%(spk)s is already past approval (%(state)s).",
                      spk=rec.name, state=rec.state)
                )
            if not rec.analytic_account_id:
                plan = self.env["account.analytic.plan"].sudo().search([], limit=1)
                rec.analytic_account_id = self.env["account.analytic.account"].sudo().create({
                    "name": rec.name,
                    "partner_id": rec.partner_id.id,
                    **({"plan_id": plan.id} if plan else {}),
                })
            if not rec.project_id:
                rec.project_id = self.env["project.project"].sudo().create({
                    "name": "%s — %s" % (rec.name, rec.event_name or rec.partner_id.name),
                    "partner_id": rec.partner_id.id,
                })
            rec.state = "confirmed"
        return True

    def action_set_state(self, new_state):
        """Single entry point for stage changes, so the audit trail has one shape."""
        valid = dict(SPK_STATES)
        if new_state not in valid:
            raise UserError(_("Unknown SPK state: %s", new_state))
        self.write({"state": new_state})
        return True
