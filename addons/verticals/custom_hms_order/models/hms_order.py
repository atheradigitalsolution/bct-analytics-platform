# -*- coding: utf-8 -*-
"""Computerised physician order entry."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

ORDER_TYPES = [
    ("medication", "Obat / Resep"),
    ("lab", "Laboratorium"),
    ("radiology", "Radiologi"),
    ("procedure", "Tindakan"),
    ("nursing", "Asuhan Keperawatan"),
    ("diet", "Diet / Gizi"),
    ("other", "Lainnya"),
]

LINE_STATES = [
    ("draft", "Draf"),
    ("ordered", "Dipesan"),
    ("in_progress", "Dikerjakan"),
    ("done", "Selesai"),
    ("cancelled", "Dibatalkan"),
]


class HmsOrder(models.Model):
    _name = "hms.order"
    _description = "Order Klinis"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "ordered_at desc, id desc"

    name = fields.Char("Nomor Order", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    order_type = fields.Selection(ORDER_TYPES, required=True, default="lab", index=True,
                                  tracking=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter Pemesan", required=True,
                                      default=lambda s: s._default_practitioner())
    target_unit_id = fields.Many2one(
        "hms.unit", "Unit Pelaksana",
        help="Unit yang mengerjakan dan yang dikreditkan pendapatannya.",
    )
    ordered_at = fields.Datetime("Waktu Order", default=fields.Datetime.now, required=True,
                                 index=True)
    priority = fields.Selection(
        [("routine", "Rutin"), ("urgent", "Segera"), ("cito", "CITO")],
        default="routine", required=True, tracking=True,
    )
    clinical_note = fields.Text("Keterangan Klinis",
                                help="Diagnosis kerja / alasan pemeriksaan untuk pelaksana.")
    line_ids = fields.One2many("hms.order.line", "order_id", "Baris Order")
    state = fields.Selection(
        [("draft", "Draf"), ("ordered", "Dipesan"), ("in_progress", "Dikerjakan"),
         ("done", "Selesai"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, compute="_compute_state", store=True, tracking=True,
        index=True,
    )
    line_count = fields.Integer(compute="_compute_state", store=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor order harus unik.")

    @api.model
    def _default_practitioner(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    @api.depends("line_ids.state")
    def _compute_state(self):
        """The header mirrors its lines; it is never set directly.

        A header that can disagree with its lines is how a lab worklist ends up
        showing an order as finished while one test is still on the bench.
        """
        for order in self:
            states = set(order.line_ids.mapped("state"))
            order.line_count = len(order.line_ids)
            if not states:
                order.state = "draft"
            elif states <= {"cancelled"}:
                order.state = "cancelled"
            elif states <= {"done", "cancelled"}:
                order.state = "done"
            elif states & {"in_progress"} or (states & {"done"} and states & {"ordered"}):
                order.state = "in_progress"
            elif states <= {"draft"}:
                order.state = "draft"
            else:
                order.state = "ordered"

    @api.constrains("practitioner_id", "order_type")
    def _check_privilege(self):
        """Clinical privileges are checked where the order is created.

        A UI that only hides the button is not a control: the same order can be
        posted through the API by anyone with write access.
        """
        privilege = {
            "medication": ("can_prescribe", _("meresepkan obat")),
            "lab": ("can_order_lab", _("meminta pemeriksaan laboratorium")),
            "radiology": ("can_order_rad", _("meminta pemeriksaan radiologi")),
        }
        for order in self:
            entry = privilege.get(order.order_type)
            if not entry:
                continue
            field_name, label = entry
            if not order.practitioner_id[field_name]:
                raise ValidationError(
                    _("%(name)s tidak memiliki kewenangan klinis untuk %(what)s.")
                    % {"name": order.practitioner_id.display_name, "what": label}
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.order") or "/"
        return super().create(vals_list)

    def action_submit(self):
        for order in self:
            if not order.line_ids:
                raise UserError(_("Order %s tidak memiliki baris.") % order.name)
            order.line_ids.filtered(lambda l: l.state == "draft").action_order()
            order.env["hms.event"].emit("order.created", {
                "order_id": order.id,
                "encounter_id": order.encounter_id.id,
                "type": order.order_type,
                "unit_id": order.target_unit_id.id,
                "priority": order.priority,
            })
        return True

    def action_cancel(self):
        for order in self:
            order.line_ids.filtered(lambda l: l.state != "done").action_cancel()
        return True


class HmsOrderLine(models.Model):
    _name = "hms.order.line"
    _description = "Baris Order Klinis"
    _order = "order_id, sequence, id"

    order_id = fields.Many2one("hms.order", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    encounter_id = fields.Many2one(related="order_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="order_id.patient_id", store=True, index=True)
    order_type = fields.Selection(related="order_id.order_type", store=True, index=True)
    tariff_id = fields.Many2one("hms.tariff", "Item Tarif", required=True)
    name = fields.Char("Deskripsi", compute="_compute_name", store=True, readonly=False)
    qty = fields.Float("Jumlah", default=1.0, required=True)
    unit_id = fields.Many2one(
        "hms.unit", "Unit Pelaksana", compute="_compute_unit_id", store=True, readonly=False,
    )
    state = fields.Selection(LINE_STATES, default="draft", required=True, index=True)
    note = fields.Char("Catatan")

    scheduled_at = fields.Datetime("Dijadwalkan")
    started_at = fields.Datetime("Mulai Dikerjakan", readonly=True)
    done_at = fields.Datetime("Selesai", readonly=True)
    performed_by_id = fields.Many2one("hms.practitioner", "Pelaksana")
    cancel_reason = fields.Char("Alasan Batal")

    # Price frozen at charge time. See the module docstring. The link to the
    # bill line itself is added by custom_hms_billing, which owns hms.bill.line.
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    unit_price = fields.Monetary("Harga Satuan", readonly=True)
    price_subtotal = fields.Monetary("Subtotal", readonly=True)

    _pending_idx = models.Index("(order_type, state) WHERE state IN ('ordered', 'in_progress')")

    @api.depends("tariff_id")
    def _compute_name(self):
        for line in self:
            if not line.name or line.tariff_id:
                line.name = line.tariff_id.name

    @api.depends("tariff_id", "order_id.target_unit_id")
    def _compute_unit_id(self):
        for line in self:
            line.unit_id = line.tariff_id.unit_id or line.order_id.target_unit_id

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_("Jumlah order harus lebih besar dari nol."))

    # --- state machine ----------------------------------------------------
    def _set_state(self, new_state, **vals):
        vals["state"] = new_state
        self.write(vals)
        for line in self:
            line.env["hms.event"].emit("order.changed", {
                "order_id": line.order_id.id,
                "line_id": line.id,
                "encounter_id": line.encounter_id.id,
                "type": line.order_type,
                "unit_id": line.unit_id.id,
                "state": new_state,
            })

    def action_order(self):
        for line in self:
            if line.state not in ("draft",):
                raise UserError(_("Baris '%s' sudah dipesan.") % line.name)
        self._set_state("ordered")
        # Categories configured as charge-on-order bill immediately: an
        # administration fee is earned when the visit opens, not when someone
        # remembers to tick it off.
        for line in self:
            if line.tariff_id.category_id.charge_on == "ordered":
                line._create_charge()
        return True

    def action_start(self):
        for line in self:
            if line.state != "ordered":
                raise UserError(_("Baris '%s' belum dipesan.") % line.name)
        self._set_state("in_progress", started_at=fields.Datetime.now())
        return True

    def action_done(self):
        for line in self:
            if line.state not in ("ordered", "in_progress"):
                raise UserError(
                    _("Baris '%(n)s' tidak dapat diselesaikan dari status %(s)s.")
                    % {"n": line.name, "s": line.state}
                )
        self._set_state("done", done_at=fields.Datetime.now())
        for line in self:
            if line.tariff_id.category_id.charge_on != "ordered":
                line._create_charge()
            line._on_done()
        return True

    def action_cancel(self):
        for line in self:
            if line.state == "done":
                raise UserError(
                    _("Baris '%s' sudah selesai dikerjakan dan tidak dapat dibatalkan.") % line.name
                )
            if line._fields.get("charge_id") and line.charge_id:
                line._reverse_charge()
        self._set_state("cancelled")
        return True

    # --- hooks for downstream modules ------------------------------------
    def _create_charge(self):
        """Hook. custom_hms_billing turns the line into a bill line."""
        return False

    def _reverse_charge(self):
        """Hook. custom_hms_billing voids the bill line."""
        return False

    def _on_done(self):
        """Hook for type-specific follow-up (lab result shells, dispensing)."""
        return False
