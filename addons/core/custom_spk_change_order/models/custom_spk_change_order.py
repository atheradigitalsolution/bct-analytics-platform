# -*- coding: utf-8 -*-
"""A scope change, priced and agreed before the workshop works differently."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"
PRICE_GROUP = "custom_spk.group_spk_price_viewer"


class CustomSpkChangeOrder(models.Model):
    _name = "custom.spk.change.order"
    _description = "Change Order"
    _inherit = ["pdp.audited.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "spk_id, sequence_no"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="cascade", tracking=True)
    sequence_no = fields.Integer(default=1)
    partner_id = fields.Many2one(related="spk_id.partner_id", store=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)

    description = fields.Text(string="Perubahan", required=True)
    origin = fields.Selection(
        [
            ("client_scope", "Permintaan klien"),
            ("internal_error", "Kesalahan internal"),
            ("technical", "Penyesuaian teknis"),
            ("venue", "Batasan venue"),
        ],
        string="Penyebab",
        required=True,
        default="client_scope",
        help="Kept because the answer changes who pays. A client's change of mind is "
        "billable; our own mistake is not, and recording it honestly is the only way "
        "the pattern ever gets fixed.",
    )
    cost_impact = fields.Monetary(
        string="Dampak Biaya", currency_field="currency_id", groups=COST_GROUP)
    price_impact = fields.Monetary(
        string="Dampak Harga", currency_field="currency_id", groups=PRICE_GROUP)
    schedule_impact_days = fields.Integer(
        string="Dampak Jadwal (hari)",
        help="The event date does not move, so a change costing three days may be "
        "impossible rather than merely expensive. Checked against the SPK's remaining "
        "time before approval.",
    )
    is_billable = fields.Boolean(
        compute="_compute_is_billable", store=True, readonly=False,
        help="Defaults from the cause and stays editable: sometimes a technical "
        "adjustment is billable and sometimes goodwill is the right answer.",
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("quoted", "Sudah Dihitung"),
            ("client_approved", "Disetujui Klien"),
            ("applied", "Diterapkan"),
            ("rejected", "Ditolak"),
        ],
        default="draft", required=True, tracking=True, index=True,
    )
    client_approved_on = fields.Date(readonly=True, tracking=True)
    client_approved_by = fields.Char(string="Disetujui oleh (nama)", tracking=True)
    applied_on = fields.Datetime(readonly=True)

    _uniq_spk_sequence = models.Constraint(
        "unique(spk_id, sequence_no)", "Two change orders cannot share a number on a job.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                spk = self.env["custom.spk"].browse(vals.get("spk_id"))
                existing = self.search_count([("spk_id", "=", spk.id)])
                seq = vals.get("sequence_no") or (existing + 1)
                vals["sequence_no"] = seq
                vals["name"] = "CO/%s/%02d" % (spk.name or _("SPK"), seq)
        return super().create(vals_list)

    @api.depends("origin")
    def _compute_is_billable(self):
        for rec in self:
            # Our own mistake is not the client's to pay for. Recorded either way,
            # because a pattern of internal errors only gets fixed once it is countable.
            rec.is_billable = rec.origin in ("client_scope", "venue")

    @api.constrains("schedule_impact_days")
    def _check_schedule(self):
        for rec in self:
            if rec.schedule_impact_days < 0:
                raise ValidationError(
                    _("A change order that shortens the schedule is not a change order."))

    def action_quote(self):
        for rec in self:
            if rec.is_billable and not rec.price_impact:
                raise UserError(
                    _("%(name)s is billable but carries no price. Agreeing scope without "
                      "a number is how the argument starts.", name=rec.name)
                )
            rec.state = "quoted"
        return True

    def action_client_approve(self, approved_by=None):
        """Client agreement, captured. This is what the workshop waits for.

        The event date is checked here rather than at apply time, because refusing a
        change the client has already been told is fine is a much worse conversation.
        """
        for rec in self:
            if rec.state != "quoted":
                raise UserError(
                    _("Price %(name)s before asking the client to agree to it.",
                      name=rec.name)
                )
            if rec.schedule_impact_days and rec.spk_id.event_date_start:
                remaining = rec.spk_id.days_to_event
                if rec.schedule_impact_days > remaining:
                    raise UserError(
                        _("%(name)s needs %(needed)s extra days and %(spk)s has %(left)s "
                          "before the event. The event date does not move, so this is "
                          "not a price question.",
                          name=rec.name, needed=rec.schedule_impact_days,
                          spk=rec.spk_id.name, left=remaining)
                    )
            rec.write({
                "state": "client_approved",
                "client_approved_on": fields.Date.context_today(rec),
                "client_approved_by": approved_by or rec.client_approved_by or "",
            })
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True

    def action_apply(self):
        """Only now may the workshop work differently.

        The gate is the point of the whole model: work done on a verbal request is work
        that gets argued about when the invoice arrives.
        """
        for rec in self:
            if rec.state != "client_approved":
                raise UserError(
                    _("%(name)s has no recorded client approval. Changing the build on a "
                      "verbal request is exactly what this document exists to prevent.",
                      name=rec.name)
                )
            if rec.schedule_impact_days and rec.spk_id.event_date_start:
                rec.spk_id.message_post(body=_(
                    "%(name)s applied: schedule impact %(days)s day(s).",
                    name=rec.name, days=rec.schedule_impact_days))
            rec.write({"state": "applied", "applied_on": fields.Datetime.now()})
        return True


class CustomSpkDesignRevision(models.Model):
    """Design revisions, counted, so the free allowance is enforceable.

    Two are included. The third caused by the client changing their mind is a change
    order rather than goodwill -- without that line revisions are unbounded, and they
    consume margin and the schedule at the same time.
    """

    _name = "custom.spk.design.revision"
    _description = "Revisi Design"
    _inherit = ["custom.object.storage.mixin"]
    _order = "spk_id, revision_no"

    spk_id = fields.Many2one("custom.spk", required=True, index=True, ondelete="cascade")
    revision_no = fields.Integer(required=True, default=1)
    reason = fields.Selection(
        [
            ("client_scope", "Perubahan permintaan klien"),
            ("internal_error", "Kesalahan internal"),
            ("technical", "Penyesuaian teknis"),
        ],
        required=True,
        default="client_scope",
    )
    note = fields.Text()
    # The drawing goes to object storage; the client's approval is captured on the
    # change order, not here, because agreement is a decision and a file is not.

    def _storage_key_parts(self):
        self.ensure_one()
        return ["spk", self.spk_id.name or "unassigned", "design",
                "D%s" % (self.revision_no or 0)]
    date = fields.Date(default=fields.Date.context_today, required=True)
    is_chargeable = fields.Boolean(
        compute="_compute_is_chargeable", store=True,
        help="True once the free allowance is used up AND the cause is the client. Our "
        "own mistakes never become chargeable however many there are.",
    )
    change_order_id = fields.Many2one("custom.spk.change.order", readonly=True)

    _uniq_revision = models.Constraint(
        "unique(spk_id, revision_no)", "Revision numbers are unique per job.")

    FREE_REVISIONS = 2

    @api.depends("revision_no", "reason")
    def _compute_is_chargeable(self):
        for rec in self:
            rec.is_chargeable = bool(
                rec.reason == "client_scope" and rec.revision_no > self.FREE_REVISIONS)

    @api.constrains("revision_no")
    def _check_revision_no(self):
        for rec in self:
            if rec.revision_no < 1:
                raise ValidationError(_("Revisions start at 1."))
