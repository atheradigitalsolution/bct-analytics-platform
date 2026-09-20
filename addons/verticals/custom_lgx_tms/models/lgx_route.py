# -*- coding: utf-8 -*-
"""Master rute dan tarifnya — tempat batas uang jalan berasal.

Batas uang jalan yang diketik bebas adalah kebocoran, bukan fleksibilitas. Di
sini ia menjadi angka master yang dinegosiasikan sekali dan dipakai berulang;
nilai di atasnya menuntut persetujuan dengan alasan tercatat.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxRoute(models.Model):
    _name = "lgx.route"
    _description = "Rute Angkutan Darat"
    _order = "origin_location_id, destination_location_id"

    name = fields.Char("Nama Rute", compute="_compute_name", store=True, readonly=False)
    code = fields.Char("Kode", index=True)
    origin_location_id = fields.Many2one("lgx.location", "Asal", required=True)
    destination_location_id = fields.Many2one("lgx.location", "Tujuan", required=True)
    distance_km = fields.Float("Jarak (km)")
    standard_duration_hours = fields.Float("Durasi Standar (jam)")
    toll_estimate = fields.Monetary("Estimasi Tol", currency_field="currency_id")
    fuel_estimate = fields.Monetary("Estimasi BBM", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    tariff_ids = fields.One2many("lgx.route.tariff", "route_id", "Tarif")
    note = fields.Char("Catatan")
    active = fields.Boolean(default=True)

    _route_uniq = models.Constraint(
        "unique(origin_location_id, destination_location_id, company_id)",
        "Rute dengan asal dan tujuan ini sudah ada.",
    )
    _distance_non_negative = models.Constraint(
        "check(distance_km >= 0)", "Jarak tidak boleh negatif.",
    )

    @api.depends("origin_location_id", "destination_location_id")
    def _compute_name(self):
        for route in self:
            if route.origin_location_id and route.destination_location_id:
                route.name = "%s → %s" % (
                    route.origin_location_id.name, route.destination_location_id.name)


class LgxRouteTariff(models.Model):
    _name = "lgx.route.tariff"
    _description = "Tarif Rute"
    _order = "route_id, valid_from desc"

    route_id = fields.Many2one("lgx.route", "Rute", required=True, ondelete="cascade", index=True)
    vehicle_category_id = fields.Many2one("lgx.vehicle.category", "Kategori Kendaraan")
    partner_id = fields.Many2one("res.partner", "Pelanggan",
                                 help="Kosong berarti tarif umum.")
    pricing_basis = fields.Selection(
        [("per_trip", "Per Trip"), ("per_ton", "Per Ton"), ("per_km", "Per Km"),
         ("per_cbm", "Per CBM"), ("per_ritase", "Per Ritase")],
        string="Dasar", required=True, default="per_trip",
    )
    price = fields.Monetary("Harga Jual", currency_field="currency_id")
    standard_advance = fields.Monetary(
        "Uang Jalan Standar", currency_field="currency_id",
        help="Batas yang dipakai dispatcher. Nilai di atas ini menuntut persetujuan "
             "dengan alasan tercatat.",
    )
    currency_id = fields.Many2one(related="route_id.currency_id", readonly=True)
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    _period_valid = models.Constraint(
        "check(valid_to is null or valid_to >= valid_from)",
        "Masa berlaku tarif tidak boleh berakhir sebelum dimulai.",
    )
    _price_non_negative = models.Constraint(
        "check(price >= 0 and standard_advance >= 0)",
        "Harga dan uang jalan standar tidak boleh negatif.",
    )

    @api.model
    def lgx_find(self, route, vehicle_category=None, partner=None, on_date=None):
        """Tarif yang paling khusus lebih dulu: pelanggan, lalu kategori kendaraan."""
        on_date = on_date or fields.Date.context_today(self)
        domain = [
            ("route_id", "=", route.id if hasattr(route, "id") else route),
            ("valid_from", "<=", on_date),
            "|", ("valid_to", "=", False), ("valid_to", ">=", on_date),
        ]
        tariffs = self.search(domain)
        if partner:
            tariffs = tariffs.filtered(lambda t: not t.partner_id or t.partner_id == partner)
        if vehicle_category:
            tariffs = tariffs.filtered(
                lambda t: not t.vehicle_category_id or t.vehicle_category_id == vehicle_category)
        return tariffs.sorted(key=lambda t: (0 if t.partner_id else 1,
                                             0 if t.vehicle_category_id else 1,
                                             -(t.valid_from.toordinal() if t.valid_from else 0)))
