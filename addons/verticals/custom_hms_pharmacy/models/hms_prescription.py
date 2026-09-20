# -*- coding: utf-8 -*-
"""Prescriptions, pharmacy queue and dispensing."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsPrescription(models.Model):
    _name = "hms.prescription"
    _description = "Resep"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "prescribed_at desc, id desc"

    name = fields.Char("Nomor Resep", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    order_id = fields.Many2one("hms.order", "Order Klinis", ondelete="set null")
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter Penulis", required=True,
                                      domain="[('can_prescribe', '=', True)]")
    depot_id = fields.Many2one("hms.depot", "Depo Pelayanan", required=True)
    prescribed_at = fields.Datetime("Waktu Resep", default=fields.Datetime.now, required=True,
                                    index=True)
    type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("inpatient", "Rawat Inap"), ("emergency", "IGD"),
         ("discharge", "Obat Pulang")],
        default="outpatient", required=True,
    )
    is_cito = fields.Boolean("CITO")
    line_ids = fields.One2many("hms.prescription.line", "prescription_id", "Baris Resep")
    state = fields.Selection(
        [("draft", "Draf"), ("submitted", "Masuk Antrian"), ("verified", "Terverifikasi"),
         ("preparing", "Disiapkan"), ("ready", "Siap Diserahkan"), ("dispensed", "Diserahkan"),
         ("rejected", "Ditolak"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, tracking=True, index=True,
    )

    verified_by_id = fields.Many2one("hms.practitioner", "Diverifikasi Apoteker", readonly=True)
    verified_at = fields.Datetime(readonly=True)
    prepared_by_id = fields.Many2one("hms.practitioner", "Disiapkan Oleh", readonly=True)
    dispensed_by_id = fields.Many2one("hms.practitioner", "Diserahkan Oleh", readonly=True)
    dispensed_at = fields.Datetime(readonly=True)
    witness_id = fields.Many2one(
        "hms.practitioner", "Saksi Double-Check",
        help="Wajib bila resep memuat obat high-alert.",
    )
    received_by = fields.Char("Diterima Oleh", help="Nama penerima obat di loket.")
    reject_reason = fields.Text("Alasan Penolakan")

    picking_id = fields.Many2one("stock.picking", "Transfer Stok", readonly=True, copy=False)
    allergy_warning = fields.Text("Peringatan Alergi", compute="_compute_allergy_warning")
    has_high_alert = fields.Boolean(compute="_compute_flags", store=True)
    has_narcotic = fields.Boolean(compute="_compute_flags", store=True)
    waiting_minutes = fields.Integer("Menunggu (menit)", compute="_compute_waiting")

    _name_uniq = models.Constraint("unique(name)", "Nomor resep harus unik.")
    _queue_idx = models.Index(
        "(depot_id, state) WHERE state IN ('submitted', 'verified', 'preparing', 'ready')"
    )

    @api.depends("line_ids.medicine_id.is_high_alert", "line_ids.medicine_id.is_narcotic")
    def _compute_flags(self):
        for rx in self:
            medicines = rx.line_ids.mapped("medicine_id")
            rx.has_high_alert = any(medicines.mapped("is_high_alert"))
            rx.has_narcotic = any(medicines.mapped("is_narcotic"))

    @api.depends("prescribed_at", "state")
    def _compute_waiting(self):
        now = fields.Datetime.now()
        for rx in self:
            if rx.state in ("dispensed", "rejected", "cancelled") or not rx.prescribed_at:
                rx.waiting_minutes = 0
            else:
                rx.waiting_minutes = int((now - rx.prescribed_at).total_seconds() // 60)

    @api.depends("line_ids.medicine_id", "patient_id")
    def _compute_allergy_warning(self):
        for rx in self:
            rx.allergy_warning = "\n".join(rx._screen_allergies())

    def _screen_allergies(self):
        """Match prescribed active ingredients against recorded allergies.

        Ingredient-level, not product-level: a patient allergic to amoxicillin
        must be flagged for every brand containing it, and brand-name matching
        would miss all of them.
        """
        self.ensure_one()
        allergies = self.patient_id.allergy_ids
        by_ingredient = {a.ingredient_id.id: a for a in allergies if a.ingredient_id}
        by_text = {(a.substance or "").strip().lower(): a for a in allergies}
        warnings = []
        for line in self.line_ids:
            medicine = line.medicine_id
            for ingredient in medicine.ingredient_ids_all():
                hit = by_ingredient.get(ingredient.id) or by_text.get(ingredient.name.lower())
                if hit:
                    warnings.append(
                        _("%(med)s mengandung %(ing)s — pasien alergi (%(sev)s, reaksi: %(re)s).")
                        % {
                            "med": medicine.display_name, "ing": ingredient.name,
                            "sev": dict(hit._fields["severity"].selection).get(hit.severity),
                            "re": hit.reaction or _("tidak dicatat"),
                        }
                    )
            direct = by_text.get((medicine.generic_name or "").strip().lower())
            if direct:
                warnings.append(
                    _("%(med)s tercatat langsung sebagai alergi pasien (%(sev)s).")
                    % {"med": medicine.display_name,
                       "sev": dict(direct._fields["severity"].selection).get(direct.severity)}
                )
        return warnings

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.prescription") or "/"
        return super().create(vals_list)

    # --- workflow ---------------------------------------------------------
    def action_submit(self):
        for rx in self:
            if rx.state != "draft":
                raise UserError(_("Resep %s sudah dikirim ke apotek.") % rx.name)
            if not rx.line_ids:
                raise UserError(_("Resep %s kosong.") % rx.name)
            rx.write({"state": "submitted"})
            rx.env["hms.event"].emit("pharmacy.queue", {
                "prescription_id": rx.id,
                "name": rx.name,
                "depot_id": rx.depot_id.id,
                "patient": rx.patient_id.name,
                "cito": rx.is_cito,
                "state": "submitted",
            })
        return True

    def action_verify(self):
        pharmacist = self._current_pharmacist()
        for rx in self:
            if rx.state != "submitted":
                raise UserError(_("Hanya resep di antrian yang dapat diverifikasi."))
            rx.write({
                "state": "verified",
                "verified_by_id": pharmacist.id,
                "verified_at": fields.Datetime.now(),
            })
            rx._emit_state()
        return True

    def action_prepare(self):
        pharmacist = self._current_pharmacist()
        for rx in self:
            if rx.state != "verified":
                raise UserError(_("Resep harus diverifikasi apoteker sebelum disiapkan."))
            rx.write({"state": "preparing", "prepared_by_id": pharmacist.id})
            rx._emit_state()
        return True

    def action_ready(self):
        for rx in self:
            if rx.state != "preparing":
                raise UserError(_("Resep belum dalam penyiapan."))
            rx.write({"state": "ready"})
            rx._emit_state()
        return True

    def action_dispense(self):
        """Hand the medicine over and move the stock."""
        pharmacist = self._current_pharmacist()
        for rx in self:
            if rx.state not in ("verified", "preparing", "ready"):
                raise UserError(
                    _("Resep %s belum siap diserahkan.") % rx.name
                )
            if rx.has_high_alert and not rx.witness_id:
                raise UserError(
                    _("Resep %s memuat obat high-alert. Saksi double-check wajib diisi "
                      "sebelum penyerahan.") % rx.name
                )
            if rx.witness_id and rx.witness_id == pharmacist:
                raise UserError(_("Saksi double-check harus petugas yang berbeda."))
            picking = rx._create_dispensing_picking()
            rx.write({
                "state": "dispensed",
                "dispensed_by_id": pharmacist.id,
                "dispensed_at": fields.Datetime.now(),
                "picking_id": picking.id if picking else False,
            })
            rx.line_ids.filtered(lambda l: l.state == "pending").write({"state": "dispensed"})
            if rx.order_id:
                rx.order_id.line_ids.filtered(
                    lambda l: l.state in ("ordered", "in_progress")
                ).action_done()
            rx._emit_state()
        return True

    def action_reject(self):
        for rx in self:
            if not rx.reject_reason:
                raise UserError(_("Alasan penolakan wajib diisi agar dokter dapat merevisi."))
            rx.write({"state": "rejected"})
            rx._emit_state()
        return True

    def action_cancel(self):
        for rx in self:
            if rx.state == "dispensed":
                raise UserError(
                    _("Resep sudah diserahkan. Gunakan retur untuk mengembalikan obat.")
                )
            rx.write({"state": "cancelled"})
            rx._emit_state()
        return True

    def _emit_state(self):
        for rx in self:
            rx.env["hms.event"].emit("pharmacy.queue", {
                "prescription_id": rx.id, "name": rx.name,
                "depot_id": rx.depot_id.id, "state": rx.state,
            })

    def _current_pharmacist(self):
        practitioner = self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        if not practitioner:
            raise UserError(
                _("Pengguna %s belum terhubung ke data praktisi, sehingga tindakan "
                  "farmasi tidak dapat dicatat atas namanya.") % self.env.user.name
            )
        return practitioner

    # --- stock ------------------------------------------------------------
    def _create_dispensing_picking(self):
        """Move the dispensed quantities out of the depot, FEFO by lot."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.state != "cancelled" and l.qty_dispense > 0)
        if not lines:
            return False
        depot = self.depot_id
        picking_type = depot._get_picking_type()
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": depot.location_id.id,
            "location_dest_id": depot._get_consumption_location().id,
            "partner_id": self.patient_id.partner_id.id,
            "origin": self.name,
            "move_ids": [
                (0, 0, {
                    # Odoo 19 dropped stock.move.name; the human-readable label
                    # on a move is description_picking.
                    "description_picking": line.medicine_id.display_name,
                    "product_id": line.product_id.id,
                    "product_uom_qty": line.qty_dispense,
                    "product_uom": line.product_id.uom_id.id,
                    "location_id": depot.location_id.id,
                    "location_dest_id": depot._get_consumption_location().id,
                })
                for line in lines
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        self._apply_fefo(picking)
        for move in picking.move_ids:
            for move_line in move.move_line_ids:
                move_line.quantity = move_line.quantity or move.product_uom_qty
        picking.button_validate()
        return picking

    def _apply_fefo(self, picking):
        """Re-point reservations at the earliest-expiring lots available.

        Odoo's own removal strategy can be set to FEFO on the location, but a
        hospital depot is often configured by someone else entirely. Doing it
        explicitly here means expiry ordering does not depend on a setting
        nobody remembers to check.
        """
        Quant = self.env["stock.quant"]
        for move in picking.move_ids:
            if move.product_id.tracking != "lot":
                continue
            quants = Quant.search([
                ("product_id", "=", move.product_id.id),
                ("location_id", "child_of", picking.location_id.id),
                ("quantity", ">", 0),
            ])
            # Lots without an expiry date sort last: an unknown expiry should
            # not jump ahead of a known, closer one. stock.quant carries the
            # expiry directly once product_expiry is installed, so no per-lot
            # read is needed here.
            never = fields.Datetime.now().replace(year=9999)
            ordered = quants.sorted(
                key=lambda q: (q.expiration_date or q.lot_id.expiration_date or never)
            )
            remaining = move.product_uom_qty
            move.move_line_ids.unlink()
            for quant in ordered:
                if remaining <= 0:
                    break
                take = min(quant.quantity, remaining)
                self.env["stock.move.line"].create({
                    "move_id": move.id,
                    "picking_id": picking.id,
                    "product_id": move.product_id.id,
                    "lot_id": quant.lot_id.id,
                    "quantity": take,
                    "product_uom_id": move.product_uom.id,
                    "location_id": quant.location_id.id,
                    "location_dest_id": move.location_dest_id.id,
                })
                remaining -= take
            if remaining > 0:
                raise UserError(
                    _("Stok %(p)s di depo %(d)s tidak mencukupi: kurang %(q).2f.")
                    % {"p": move.product_id.display_name, "d": self.depot_id.name, "q": remaining}
                )


class HmsPrescriptionLine(models.Model):
    _name = "hms.prescription.line"
    _description = "Baris Resep"
    _order = "prescription_id, sequence, id"

    prescription_id = fields.Many2one("hms.prescription", required=True, ondelete="cascade",
                                      index=True)
    sequence = fields.Integer(default=10)
    medicine_id = fields.Many2one("hms.medicine", "Obat", required=True)
    product_id = fields.Many2one(related="medicine_id.product_id", store=True, readonly=True)
    is_compound = fields.Boolean("Racikan")
    compound_name = fields.Char("Nama Racikan")
    compound_instruction = fields.Char("Instruksi Peracikan")
    parent_line_id = fields.Many2one("hms.prescription.line", "Bagian Dari Racikan",
                                     ondelete="cascade")
    component_ids = fields.One2many("hms.prescription.line", "parent_line_id", "Komponen Racikan")

    dose = fields.Float("Dosis", digits=(12, 3))
    dose_unit = fields.Char("Satuan Dosis", default="mg")
    frequency_id = fields.Many2one("hms.frequency", "Frekuensi")
    route_id = fields.Many2one("hms.route", "Rute")
    duration_days = fields.Integer("Durasi (hari)", default=1)
    qty_prescribed = fields.Float("Jumlah Diresepkan", default=1.0, required=True)
    qty_dispense = fields.Float("Jumlah Diserahkan", compute="_compute_qty_dispense",
                                store=True, readonly=False)
    sig = fields.Char("Aturan Pakai")
    is_prn = fields.Boolean("Bila Perlu (PRN)")
    note = fields.Char("Catatan")
    state = fields.Selection(
        [("pending", "Menunggu"), ("dispensed", "Diserahkan"), ("substituted", "Diganti"),
         ("cancelled", "Dibatalkan")],
        default="pending", required=True,
    )
    substitution_reason = fields.Char("Alasan Penggantian")

    @api.depends("qty_prescribed")
    def _compute_qty_dispense(self):
        for line in self:
            if not line.qty_dispense:
                line.qty_dispense = line.qty_prescribed

    @api.onchange("medicine_id")
    def _onchange_medicine(self):
        if self.medicine_id:
            self.sig = self.medicine_id.default_sig
            self.dose = self.medicine_id.default_dose
            self.frequency_id = self.medicine_id.default_frequency_id
            self.duration_days = self.medicine_id.default_duration_days or 1
            self.route_id = self.medicine_id.route_ids[:1]

    @api.constrains("qty_prescribed", "qty_dispense")
    def _check_qty(self):
        for line in self:
            if line.qty_prescribed <= 0:
                raise ValidationError(_("Jumlah resep harus lebih besar dari nol."))
            if line.qty_dispense > line.qty_prescribed:
                raise ValidationError(
                    _("Jumlah diserahkan (%(d).2f) tidak boleh melebihi jumlah diresepkan (%(p).2f).")
                    % {"d": line.qty_dispense, "p": line.qty_prescribed}
                )
