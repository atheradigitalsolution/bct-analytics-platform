# -*- coding: utf-8 -*-
"""What the venue will and will not allow, recorded before the price is fixed."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"


class CustomSpkSurvey(models.Model):
    _name = "custom.spk.survey"
    _description = "Survey Lokasi"
    _inherit = ["pdp.audited.mixin", "mail.thread", "custom.object.storage.mixin"]
    _order = "survey_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="cascade", tracking=True)
    venue_name = fields.Char(string="Venue", required=True)
    survey_date = fields.Date(default=fields.Date.context_today, required=True)
    surveyed_by = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True)
    # storage_key / storage_url come from custom.object.storage.mixin. There is no
    # pasted-link field: a pasted link is the thing that rots, and it rots at the moment
    # a dispute needs it.

    def _storage_key_parts(self):
        """Readable in the bucket without the database to explain it."""
        self.ensure_one()
        return ["spk", self.spk_id.name or "unassigned", "survey", self.venue_name or ""]

    # ---- what the space actually is ----
    ceiling_height_m = fields.Float(
        string="Tinggi Plafon (m)",
        help="The number that most often contradicts the drawing. A booth designed at "
        "2.5 m does not fit under a 2.4 m soffit, and finding out on the night costs a "
        "rebuild.",
    )
    floor_area_m2 = fields.Float(string="Luas Aktual (m2)")
    access_width_m = fields.Float(
        string="Lebar Akses (m)",
        help="Door, lift or dock, whichever is narrowest. Panels are cut to this.",
    )
    has_loading_dock = fields.Boolean(string="Ada Loading Dock")
    lift_required = fields.Boolean(string="Perlu Lift / Tangga")
    max_panel_length_m = fields.Float(
        string="Panjang Panel Maks (m)",
        help="Derived from access in practice, and the single most useful number to hand "
        "the designer: it decides how the booth is broken up.",
    )

    # ---- what the venue permits ----
    work_hours_from = fields.Float(string="Jam Kerja Dari", help="24h decimal, 22.0 = 22:00")
    work_hours_to = fields.Float(string="Jam Kerja Sampai")
    night_work_only = fields.Boolean(
        string="Hanya Boleh Malam",
        help="Turns a one-day install into two nights, with crew premiums to match. "
        "The shift multiplier is where that lands.",
    )
    permit_required = fields.Boolean(string="Perlu Izin Gedung")

    # ---- power ----
    power_available_kw = fields.Float(string="Daya Tersedia (kW)")
    power_points = fields.Integer(string="Jumlah Titik Daya")
    power_by_venue = fields.Boolean(
        string="Daya Disediakan Venue",
        help="If false, a generator is part of the estimate.",
    )

    # ---- what the venue charges ----
    venue_cost_power = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    venue_cost_permit = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    venue_cost_security = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    venue_cost_other = fields.Monetary(currency_field="currency_id", groups=COST_GROUP)
    venue_cost_total = fields.Monetary(
        compute="_compute_venue_cost", store=True,
        currency_field="currency_id", groups=COST_GROUP,
        help="Goes into the estimate as the venue category, instead of being discovered "
        "when the venue invoices.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)

    risk_note = fields.Text(
        string="Risiko Teridentifikasi",
        help="Only for what the checklist does not already ask. Not a substitute for it.",
    )
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Selesai")], default="draft", required=True, tracking=True)

    @api.depends("spk_id", "venue_name", "survey_date")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s — %s" % (rec.spk_id.name or "?", rec.venue_name or "?")

    @api.depends("venue_cost_power", "venue_cost_permit",
                 "venue_cost_security", "venue_cost_other")
    def _compute_venue_cost(self):
        for rec in self:
            rec.venue_cost_total = (
                (rec.venue_cost_power or 0.0) + (rec.venue_cost_permit or 0.0)
                + (rec.venue_cost_security or 0.0) + (rec.venue_cost_other or 0.0)
            )

    @api.constrains("work_hours_from", "work_hours_to", "ceiling_height_m", "access_width_m")
    def _check_values(self):
        for rec in self:
            for label, value in (("Jam Kerja Dari", rec.work_hours_from),
                                 ("Jam Kerja Sampai", rec.work_hours_to)):
                if value and not 0.0 <= value < 24.0:
                    raise ValidationError(
                        _("%(label)s must be within a day; got %(value)s.",
                          label=label, value=value)
                    )
            if rec.ceiling_height_m < 0 or rec.access_width_m < 0:
                raise ValidationError(_("Dimensions cannot be negative."))

    def action_done(self):
        """Mark surveyed. The numbers are now the estimate's to use."""
        for rec in self:
            missing = [
                label for label, value in (
                    (_("tinggi plafon"), rec.ceiling_height_m),
                    (_("lebar akses"), rec.access_width_m),
                ) if not value
            ]
            if missing:
                raise ValidationError(
                    _("A survey without %(fields)s is not a survey: those are the two "
                      "numbers that contradict the drawing and cost a rebuild on the "
                      "night.", fields=", ".join(missing))
                )
            rec.state = "done"
        return True
