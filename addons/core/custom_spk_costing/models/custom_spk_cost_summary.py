# -*- coding: utf-8 -*-
"""Estimate versus actual, one record per job.

Not on custom.spk, because that model is required to hold no money -- the rule that
makes it safe to show an Account Executive. The constraint forced this into its own
model, which is where it belonged anyway: different readers, different refresh
behaviour, and a fence that no longer depends on remembering to hide a field.
"""

from __future__ import annotations

from odoo import _, api, fields, models

COST_GROUP = "custom_spk.group_spk_cost_viewer"
PRICE_GROUP = "custom_spk.group_spk_price_viewer"

class CustomSpkCostSummary(models.Model):
    _name = "custom.spk.cost.summary"
    _description = "Estimasi vs Realisasi per SPK"
    _order = "spk_id desc"
    _rec_name = "spk_id"

    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="cascade")
    partner_id = fields.Many2one(related="spk_id.partner_id", store=True)
    event_name = fields.Char(related="spk_id.event_name", store=True)
    state = fields.Selection(related="spk_id.state", store=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)
    refreshed_on = fields.Datetime(readonly=True)

    estimation_id = fields.Many2one(
        "custom.spk.estimation", compute="_compute_all", store=True,
        help="The approved estimate this job is measured against. The latest approved "
        "one, so a revision supersedes cleanly.",
    )

    # ---- estimate ----
    est_material = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_labor = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_subcon = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_delivery = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_overhead = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_total = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    est_waste = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)

    # ---- actual, read from analytic lines ----
    act_material = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    act_labor = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    act_subcon = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    act_delivery = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    act_other = fields.Monetary(
        compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP,
        help="Analytic cost whose source is not one of the known models. Kept visible "
        "rather than dropped: an unexplained figure is better than a missing one.",
    )
    act_total = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)

    # ---- variance ----
    var_material = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    var_labor = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP)
    var_total = fields.Monetary(
        compute="_compute_all", store=True, currency_field="currency_id", groups=COST_GROUP,
        help="Positive means the job came in under its estimate.",
    )
    var_total_pct = fields.Float(compute="_compute_all", store=True, groups=COST_GROUP)

    # ---- margin: owner and finance only ----
    quoted_price = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=PRICE_GROUP)
    margin_actual = fields.Monetary(compute="_compute_all", store=True, currency_field="currency_id", groups=PRICE_GROUP)
    margin_actual_pct = fields.Float(compute="_compute_all", store=True, groups=PRICE_GROUP)
    margin_estimated_pct = fields.Float(compute="_compute_all", store=True, groups=PRICE_GROUP)
    margin_slipped = fields.Boolean(
        compute="_compute_all", store=True, groups=PRICE_GROUP,
        help="The realised margin fell short of what was quoted. This is the line the "
        "post-mortem starts from.",
    )

    _uniq_spk = models.Constraint(
        "unique(spk_id)", "One cost summary per job; a second would disagree with the first.")

    @api.depends("spk_id")
    def _compute_all(self):
        Est = self.env["custom.spk.estimation"].sudo()
        Line = self.env["account.analytic.line"].sudo()
        for rec in self:
            est = Est.search(
                [("spk_id", "=", rec.spk_id.id), ("state", "=", "approved")],
                order="revision desc, id desc", limit=1,
            )
            rec.estimation_id = est
            rec.est_material = est.material_cost if est else 0.0
            rec.est_labor = est.labor_cost if est else 0.0
            rec.est_subcon = est.subcon_cost if est else 0.0
            rec.est_delivery = (est.delivery_cost + est.venue_cost) if est else 0.0
            rec.est_overhead = est.overhead_amount if est else 0.0
            rec.est_total = est.total_cost if est else 0.0
            rec.est_waste = est.waste_allowance if est else 0.0
            rec.quoted_price = est.quoted_price if est else 0.0

            buckets = dict.fromkeys(("material", "labor", "subcon", "delivery", "other"), 0.0)
            if rec.spk_id.analytic_account_id:
                lines = Line.search(
                    [("account_id", "=", rec.spk_id.analytic_account_id.id)])
                for line in lines:
                    # Stamped at creation, never inferred here. Analytic cost is held
                    # negative, so a cost is reported by flipping the sign; a credit
                    # (a returned remnant) is positive and correctly reduces the bucket.
                    bucket = line.x_spk_cost_category or "other"
                    buckets[bucket] -= line.amount
            rec.act_material = buckets["material"]
            rec.act_labor = buckets["labor"]
            rec.act_subcon = buckets["subcon"]
            rec.act_delivery = buckets["delivery"]
            rec.act_other = buckets["other"]
            rec.act_total = sum(buckets.values())

            rec.var_material = rec.est_material - rec.act_material
            rec.var_labor = rec.est_labor - rec.act_labor
            rec.var_total = rec.est_total - rec.act_total
            rec.var_total_pct = (
                (rec.var_total / rec.est_total * 100.0) if rec.est_total else 0.0)

            rec.margin_actual = rec.quoted_price - rec.act_total
            rec.margin_actual_pct = (
                (rec.margin_actual / rec.quoted_price * 100.0) if rec.quoted_price else 0.0)
            est_margin = (est.margin_amount if est else 0.0)
            rec.margin_estimated_pct = (
                (est_margin / rec.quoted_price * 100.0) if rec.quoted_price else 0.0)
            rec.margin_slipped = bool(
                rec.quoted_price and rec.margin_actual_pct < rec.margin_estimated_pct - 0.01)
            rec.refreshed_on = fields.Datetime.now()

    def action_refresh(self):
        """Recompute on demand. Nothing recomputes itself on every analytic write.

        A stored compute that depended on analytic lines would rewrite this table on
        every material issue and every shift log, which on a busy month is thousands
        of writes for a report nobody is reading at the time.
        """
        self.invalidate_recordset()
        self._compute_all()
        return True

    @api.model
    def refresh_all(self):
        """Create a summary for every job that has one missing, then recompute."""
        Spk = self.env["custom.spk"].sudo()
        existing = set(self.search([]).mapped("spk_id").ids)
        missing = Spk.search([("analytic_account_id", "!=", False)]).filtered(
            lambda s: s.id not in existing)
        self.create([{"spk_id": spk.id} for spk in missing])
        self.search([]).action_refresh()
        return True
