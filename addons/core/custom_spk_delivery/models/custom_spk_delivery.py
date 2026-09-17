# -*- coding: utf-8 -*-
"""Delivery and installation per venue, with handover as the billing gate."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

COST_GROUP = "custom_spk.group_spk_cost_viewer"


class CustomSpkDelivery(models.Model):
    _name = "custom.spk.delivery"
    _description = "Jadwal Delivery & Instalasi"
    _inherit = ["pdp.audited.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "loading_in asc, id asc"

    name = fields.Char(required=True, default=lambda s: _("New"), copy=False, readonly=True)
    spk_id = fields.Many2one(
        "custom.spk", required=True, index=True, ondelete="cascade", tracking=True)
    sequence_no = fields.Integer(
        string="Pengiriman ke-", default=1,
        help="Forms the sub-number D1, D2 under the SPK. A job that ships three times "
        "has three of these, and the client quotes the sub-number back.",
    )
    partner_id = fields.Many2one(related="spk_id.partner_id", store=True)
    analytic_account_id = fields.Many2one(
        related="spk_id.analytic_account_id", store=True, groups=COST_GROUP)

    # ---- where ----
    venue_name = fields.Char(string="Venue", tracking=True)
    venue_address = fields.Text(string="Alamat")
    venue_contact = fields.Char(string="Kontak Venue")
    venue_partner_id = fields.Many2one(
        "res.partner", string="Alamat Pengiriman",
        help="Used when the venue is a known partner address. Free text is kept as well, "
        "because a hall and a gate number are rarely in the address book.",
    )

    # ---- when ----
    loading_in = fields.Datetime(
        string="Loading In",
        tracking=True,
        help="When the venue permits goods to enter, which is frequently overnight. Not "
        "a preference: a crew that arrives outside the window waits outside a locked dock.",
    )
    installation_start = fields.Datetime(string="Mulai Instalasi")
    installation_end = fields.Datetime(string="Selesai Instalasi")
    dismantle_at = fields.Datetime(
        string="Bongkar",
        help="Scheduled from the event end. It needs a crew, a truck and a venue slot, "
        "and is the line most often missing from the estimate.",
    )

    # ---- who and what ----
    crew_ids = fields.Many2many("hr.employee", string="Crew")
    driver_id = fields.Many2one("hr.employee", string="Driver")
    vehicle_note = fields.Char(
        string="Kendaraan",
        help="Free text rather than a fleet link: trucks here are usually hired per trip.",
    )
    picking_id = fields.Many2one("stock.picking", string="Delivery Order", copy=False)

    delivery_cost = fields.Monetary(
        string="Biaya Delivery", currency_field="currency_id", groups=COST_GROUP,
        help="Fuel, tolls, parking, hired truck, crew meals. Booked to the job when the "
        "shipment is marked installed.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, groups=COST_GROUP)
    cost_posted = fields.Boolean(readonly=True, copy=False)

    # ---- handover ----
    bast_id = fields.Many2one(
        "custom.bast.document", string="BAST", readonly=True, copy=False,
        help="Linked, not copied. custom_bast already does dual signature, GPS and "
        "timestamp; duplicating that would give two handover records to disagree.",
    )
    bast_signed = fields.Boolean(
        compute="_compute_bast_signed", store=True,
        help="True only once the client side has signed. This is what billing waits on.",
    )
    photo_url = fields.Char(
        string="Link Foto Instalasi",
        help="A link, because photographs are held outside the filestore here. The "
        "signature is NOT a link: it is captured as an attachment, because it is the "
        "part that has to survive a dispute months later.",
    )

    state = fields.Selection(
        [
            ("scheduled", "Dijadwalkan"),
            ("in_transit", "Dalam Pengiriman"),
            ("arrived", "Tiba di Venue"),
            ("installing", "Instalasi"),
            ("installed", "Terpasang"),
            ("bast_signed", "BAST Ditandatangani"),
            ("dismantled", "Dibongkar"),
        ],
        default="scheduled", required=True, tracking=True, index=True,
    )

    _uniq_spk_sequence = models.Constraint(
        "unique(spk_id, sequence_no)",
        "Two shipments cannot share a sub-number on the same job.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("New"):
                spk = self.env["custom.spk"].browse(vals.get("spk_id"))
                seq = vals.get("sequence_no") or 1
                # Derived from the SPK rather than a global sequence: the client asks
                # about "D2 of SPK 0001", not about the hundredth delivery this year.
                vals["name"] = "%s/D%s" % (spk.name or _("SPK"), seq)
        return super().create(vals_list)

    @api.depends("bast_id.state", "bast_id.party_to_signature")
    def _compute_bast_signed(self):
        for rec in self:
            rec.bast_signed = bool(rec.bast_id and rec.bast_id.party_to_signature)

    @api.constrains("loading_in", "venue_name", "installation_start", "installation_end")
    def _check_schedule(self):
        for rec in self:
            if rec.venue_name and not rec.loading_in:
                raise ValidationError(
                    _("%(name)s has a venue but no loading window. Venues dictate when "
                      "goods may enter, and a crew that arrives outside it waits outside "
                      "a locked dock.", name=rec.name)
                )
            if (rec.installation_start and rec.installation_end
                    and rec.installation_end < rec.installation_start):
                raise ValidationError(_("Installation cannot finish before it starts."))

    def action_create_bast(self):
        """Raise the handover document, or open the one already raised."""
        Bast = self.env["custom.bast.document"]
        for rec in self:
            if rec.bast_id:
                continue
            if not rec.spk_id.partner_id:
                raise UserError(_("%(name)s has no client to hand over to.", name=rec.name))
            rec.bast_id = Bast.create({
                # custom_bast offers installation as a kind; that is what this is.
                "kind": "installation",
                "reference": "%s,%s" % (rec._name, rec.id),
                "party_from_id": self.env.company.partner_id.id,
                "party_to_id": rec.spk_id.partner_id.id,
                "location_text": rec.venue_name or rec.venue_address or "",
                "note": _("Serah terima %(name)s — %(event)s",
                          name=rec.name, event=rec.spk_id.event_name or ""),
            })
        return True

    def action_mark_installed(self):
        """Installed, and the trip's cost lands on the job.

        Posted here rather than when the shipment was scheduled, because a scheduled
        trip that never happened should not cost anything, and posting twice is worse
        than posting late.
        """
        AnalyticLine = self.env["account.analytic.line"].sudo()
        for rec in self:
            if rec.state in ("installed", "bast_signed", "dismantled"):
                raise UserError(
                    _("%(name)s is already installed.", name=rec.name))
            if rec.delivery_cost and not rec.cost_posted:
                if not rec.spk_id.analytic_account_id:
                    raise UserError(
                        _("%(spk)s has no analytic account for the trip's cost.",
                          spk=rec.spk_id.name)
                    )
                vals = {
                    "name": _("Delivery & instalasi %(name)s", name=rec.name),
                    "date": fields.Date.context_today(rec),
                    "account_id": rec.spk_id.analytic_account_id.id,
                    "amount": -abs(rec.delivery_cost),
                }
                if "x_spk_cost_category" in AnalyticLine._fields:
                    vals["x_spk_cost_category"] = "delivery"
                AnalyticLine.create(vals)
                rec.cost_posted = True
            rec.state = "installed"
        return True

    def action_confirm_handover(self):
        """Only the client's signature closes this, because that is what billing needs."""
        for rec in self:
            if not rec.bast_signed:
                raise UserError(
                    _("%(name)s has no signed handover yet. Billing against an unsigned "
                      "BAST is what a client's finance department declines.",
                      name=rec.name)
                )
            rec.state = "bast_signed"
        return True

    def action_mark_dismantled(self):
        self.write({"state": "dismantled"})
        return True

    @api.model
    def _cron_schedule_dismantle(self):
        """Put a dismantle date on shipments whose event has ended without one.

        The work is always done; the schedule is what goes missing, and it goes missing
        in the week everybody has moved on to the next event.
        """
        today = fields.Date.context_today(self)
        pending = self.search([
            ("state", "in", ("installed", "bast_signed")),
            ("dismantle_at", "=", False),
            ("spk_id.event_date_end", "!=", False),
            ("spk_id.event_date_end", "<=", today),
        ])
        for rec in pending:
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Bongkar belum dijadwalkan"),
                note=_("Event %(event)s sudah selesai dan %(name)s belum punya jadwal bongkar.",
                       event=rec.spk_id.event_name or "?", name=rec.name),
            )
        return len(pending)
