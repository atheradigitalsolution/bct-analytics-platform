# -*- coding: utf-8 -*-
"""Material request: what the floor asked for, who approved it, what it cost the job."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"


class CustomSpkMaterialRequest(models.Model):
    _name = "custom.spk.material.request"
    _description = "Permintaan Material"
    _inherit = ["pdp.audited.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one(
        "custom.spk", string="SPK", required=True, index=True, ondelete="restrict",
        help="Required, not optional. A request with no job is material that leaves the "
        "store and lands nowhere.",
    )
    analytic_account_id = fields.Many2one(
        related="spk_id.analytic_account_id", store=True, groups=COST_GROUP)
    work_item = fields.Char(string="Item Pekerjaan")
    requested_by = fields.Many2one(
        "hr.employee", string="Diminta oleh", required=True,
        help="The worker, not the login. They may not have one.",
    )
    supervisor_id = fields.Many2one("res.users", string="Approver", tracking=True)
    approval_date = fields.Datetime(readonly=True)
    escalated_to_id = fields.Many2one(
        "res.users", string="Eskalasi ke", readonly=True, tracking=True)
    escalation_reason = fields.Text(
        string="Alasan Melebihi Estimasi",
        help="Required once a request pushes the job past what was estimated. The point "
        "is not to block the material; it is that nobody quietly approves the third "
        "extra sheet.",
    )
    over_estimate = fields.Boolean(
        compute="_compute_over_estimate", store=True,
        help="True when this request would take the job's cumulative quantity for some "
        "product past the estimate.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("to_approve", "Menunggu Approval"),
            ("approved", "Approved"),
            ("issued", "Dikeluarkan"),
            ("done", "Done"),
            ("rejected", "Ditolak"),
        ],
        default="draft", required=True, tracking=True, index=True,
    )
    line_ids = fields.One2many("custom.spk.material.request.line", "request_id")
    picking_id = fields.Many2one("stock.picking", readonly=True, copy=False)
    total_cost = fields.Monetary(
        compute="_compute_total_cost", store=True, currency_field="currency_id", groups=COST_GROUP)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "custom.spk.material.request") or _("New")
        return super().create(vals_list)

    @api.depends("line_ids.qty_requested", "line_ids.qty_estimated", "line_ids.qty_taken_before")
    def _compute_over_estimate(self):
        for rec in self:
            rec.over_estimate = any(
                line.qty_estimated > 0
                and (line.qty_taken_before + line.qty_requested) > line.qty_estimated
                for line in rec.line_ids
            )

    @api.depends("line_ids.subtotal")
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = sum(rec.line_ids.mapped("subtotal"))

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("%(name)s asks for nothing.", name=rec.name))
            rec.state = "to_approve"
        return True

    def action_approve(self):
        """The supervisor approves material. Going past the estimate escalates.

        Not blocks — escalates. Production does not stop because a sheet was cut
        wrong; but the third extra sheet has to be someone's decision on the record,
        and that someone is the project manager rather than the person who needs the
        material to finish today.
        """
        for rec in self:
            if rec.over_estimate:
                if not rec.escalation_reason:
                    raise UserError(
                        _("%(name)s takes %(spk)s past its estimate. Say why before "
                          "approving — this is the control that keeps material overrun "
                          "visible instead of absorbed.",
                          name=rec.name, spk=rec.spk_id.name)
                    )
                if not self.env.user.has_group("custom_spk.group_spk_pm"):
                    rec.state = "to_approve"
                    rec.escalated_to_id = rec.spk_id.user_id
                    rec.activity_schedule(
                        "mail.mail_activity_data_todo",
                        user_id=rec.spk_id.user_id.id or self.env.user.id,
                        summary=_("Permintaan material melebihi estimasi"),
                        note=rec.escalation_reason,
                    )
                    raise UserError(
                        _("%(name)s exceeds the estimate, so it needs a project manager. "
                          "It has been escalated.", name=rec.name)
                    )
            rec.write({
                "state": "approved",
                "supervisor_id": self.env.user.id,
                "approval_date": fields.Datetime.now(),
            })
            for line in rec.line_ids:
                if not line.qty_approved:
                    line.qty_approved = line.qty_requested
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True

    def action_issue(self):
        """Move the goods and let stock valuation carry the cost to the job.

        The analytic distribution rides on the move rather than being posted here, so
        that one mechanism books material cost and there is no second number to
        reconcile.
        """
        Picking = self.env["stock.picking"]
        for rec in self:
            if rec.state != "approved":
                raise UserError(_("Approve %(name)s before issuing it.", name=rec.name))
            if not rec.spk_id.analytic_account_id:
                raise UserError(
                    _("%(spk)s has no analytic account, so issued material would have "
                      "nowhere to land.", spk=rec.spk_id.name)
                )
            picking_type = self.env.ref("stock.picking_type_internal", raise_if_not_found=False)
            if not picking_type:
                raise UserError(_("No internal transfer type is configured."))
            moves = []
            for line in rec.line_ids.filtered(lambda l: l.qty_approved > 0):
                moves.append((0, 0, {
                    "name": line.product_id.display_name,
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.qty_approved,
                    "product_uom": line.uom_id.id or line.product_id.uom_id.id,
                    "location_id": picking_type.default_location_src_id.id,
                    "location_dest_id": picking_type.default_location_dest_id.id,
                    "analytic_distribution": {str(rec.spk_id.analytic_account_id.id): 100.0},
                }))
            rec.picking_id = Picking.create({
                "picking_type_id": picking_type.id,
                "origin": "%s / %s" % (rec.name, rec.spk_id.name),
                "location_id": picking_type.default_location_src_id.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
                "move_ids": moves,
            })
            for line in rec.line_ids:
                line.qty_issued = line.qty_approved
            rec.state = "issued"
        return True


class CustomSpkMaterialRequestLine(models.Model):
    _name = "custom.spk.material.request.line"
    _description = "Baris Permintaan Material"
    _order = "request_id, id"

    request_id = fields.Many2one(
        "custom.spk.material.request", required=True, ondelete="cascade", index=True)
    spk_id = fields.Many2one(related="request_id.spk_id", store=True, index=True)
    currency_id = fields.Many2one(related="request_id.currency_id", groups=COST_GROUP)
    product_id = fields.Many2one("product.product", required=True)
    uom_id = fields.Many2one("uom.uom", string="Satuan")
    qty_requested = fields.Float(string="Diminta", required=True, default=1.0)
    qty_approved = fields.Float(string="Disetujui")
    qty_issued = fields.Float(string="Dikeluarkan", readonly=True)

    # The comparison that makes overrun visible while it is still happening.
    qty_estimated = fields.Float(
        string="Estimasi", compute="_compute_against_estimate", store=True,
        help="What the approved bill of quantity allowed for this product on this job.",
    )
    qty_taken_before = fields.Float(
        string="Sudah Diambil", compute="_compute_against_estimate", store=True,
        help="Cumulative issued quantity on this job before this request.",
    )
    subtotal = fields.Monetary(
        compute="_compute_subtotal", store=True, currency_field="currency_id", groups=COST_GROUP)

    @api.depends("product_id", "request_id.spk_id")
    def _compute_against_estimate(self):
        EstLine = self.env["custom.spk.estimation.line"].sudo()
        ReqLine = self.env["custom.spk.material.request.line"].sudo()
        for rec in self:
            spk = rec.request_id.spk_id
            if not spk or not rec.product_id:
                rec.qty_estimated = 0.0
                rec.qty_taken_before = 0.0
                continue
            est_lines = EstLine.search([
                ("estimation_id.spk_id", "=", spk.id),
                ("estimation_id.state", "=", "approved"),
                ("product_id", "=", rec.product_id.id),
            ])
            rec.qty_estimated = sum(est_lines.mapped("quantity"))
            taken = ReqLine.search([
                ("spk_id", "=", spk.id),
                ("product_id", "=", rec.product_id.id),
                ("request_id.state", "in", ("issued", "done")),
                ("id", "!=", rec.id or 0),
            ])
            rec.qty_taken_before = sum(taken.mapped("qty_issued"))

    @api.depends("qty_approved", "qty_requested", "product_id.standard_price")
    def _compute_subtotal(self):
        for rec in self:
            qty = rec.qty_approved or rec.qty_requested or 0.0
            rec.subtotal = qty * (rec.product_id.sudo().standard_price or 0.0)

    @api.constrains("qty_requested", "qty_approved")
    def _check_quantities(self):
        for rec in self:
            if rec.qty_requested <= 0:
                raise ValidationError(_("A request line for nothing is not a request."))
            if rec.qty_approved and rec.qty_approved > rec.qty_requested:
                raise ValidationError(
                    _("Approving more than was asked for (%(approved)s > %(requested)s) "
                      "is how material leaves the store without anybody asking.",
                      approved=rec.qty_approved, requested=rec.qty_requested)
                )
