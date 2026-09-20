# -*- coding: utf-8 -*-
"""Pharmacy depots, mapped onto Odoo stock locations."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsDepot(models.Model):
    _name = "hms.depot"
    _description = "Depo Farmasi"
    _order = "sequence, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    type = fields.Selection(
        [("warehouse", "Gudang Farmasi"), ("outpatient", "Depo Rawat Jalan"),
         ("emergency", "Depo IGD"), ("inpatient", "Depo Rawat Inap"),
         ("ok", "Depo Kamar Operasi"), ("floor", "Floor Stock Ruangan")],
        required=True, default="outpatient",
    )
    unit_id = fields.Many2one("hms.unit", "Unit Layanan")
    location_id = fields.Many2one(
        "stock.location", "Lokasi Stok", required=True, domain="[('usage', '=', 'internal')]",
        help="Lokasi Odoo yang stoknya dipotong saat penyerahan dari depo ini.",
    )
    picking_type_id = fields.Many2one(
        "stock.picking.type", "Tipe Operasi Penyerahan",
        help="Tipe operasi yang dipakai untuk transfer penyerahan obat ke pasien.",
    )
    consumption_location_id = fields.Many2one(
        "stock.location", "Lokasi Konsumsi Pasien",
        domain="[('usage', 'in', ('customer', 'inventory'))]",
        help="Tujuan pergerakan stok saat obat diserahkan. Memakai lokasi "
             "customer membuat nilai HPP keluar dari neraca seperti penjualan biasa.",
    )
    pharmacist_ids = fields.Many2many("hms.practitioner", string="Apoteker Penanggung Jawab",
                                      domain="[('type', 'in', ('pharmacist', 'pharmacy_tech'))]")
    is_active_queue = fields.Boolean("Punya Antrian Resep", default=True)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode depo harus unik.")

    def _get_consumption_location(self):
        """Fallback to the company's customer location if none is configured."""
        self.ensure_one()
        if self.consumption_location_id:
            return self.consumption_location_id
        location = self.env["stock.location"].search([("usage", "=", "customer")], limit=1)
        if not location:
            raise UserError(
                _("Depo %s belum punya lokasi konsumsi pasien dan tidak ada lokasi "
                  "pelanggan default di sistem.") % self.name
            )
        return location

    def _get_picking_type(self):
        self.ensure_one()
        if self.picking_type_id:
            return self.picking_type_id
        picking_type = self.env["stock.picking.type"].search([
            ("code", "=", "outgoing"),
            ("default_location_src_id", "=", self.location_id.id),
        ], limit=1) or self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        if not picking_type:
            raise UserError(
                _("Tidak ada tipe operasi pengiriman yang dapat dipakai untuk depo %s.") % self.name
            )
        return picking_type
