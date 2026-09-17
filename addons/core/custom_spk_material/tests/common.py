# -*- coding: utf-8 -*-
from __future__ import annotations

from odoo.tests.common import TransactionCase


class MaterialCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.MR = cls.env["custom.spk.material.request"]
        cls.MRL = cls.env["custom.spk.material.request.line"]
        cls.Ret = cls.env["custom.spk.material.return"]
        cls.RetL = cls.env["custom.spk.material.return.line"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})
        cls.worker = cls.env["hr.employee"].create({"name": "Tukang"})

        # Class A: a sheet that gets recut, so it produces remnants worth arguing about.
        cls.offcut_product = cls.env["product.product"].create({
            "name": "Multiplek 12mm — Sisa", "type": "consu", "standard_price": 111_000.0,
        })
        cls.sheet = cls.env["product.product"].create({
            "name": "Multiplek 12mm", "type": "consu", "standard_price": 185_000.0,
        })
        cls.sheet.product_tmpl_id.write({
            "x_spk_material_class": "a_stock",
            "x_spk_offcut_product_id": cls.offcut_product.id,
            "x_spk_offcut_threshold_pct": 30.0,
            "x_spk_offcut_valuation_pct": 60.0,
        })
        # Class D: printed to one size, so it has no second life.
        cls.banner = cls.env["product.product"].create({
            "name": "Banner Custom", "type": "consu", "standard_price": 500_000.0,
        })
        cls.banner.product_tmpl_id.x_spk_material_class = "d_made_to_order"

    @classmethod
    def _spk(cls, event="GIIAS"):
        spk = cls.env["custom.spk"].create({
            "partner_id": cls.partner.id, "event_name": event})
        spk.action_confirm()
        return spk

    def _estimate(self, spk, product, qty):
        est = self.env["custom.spk.estimation"].create({"spk_id": spk.id})
        self.env["custom.spk.estimation.line"].create({
            "estimation_id": est.id, "category": "material", "name": product.name,
            "product_id": product.id, "quantity": qty, "unit_cost": product.standard_price,
        })
        est.action_approve()
        return est

    def _request(self, spk, product, qty):
        req = self.MR.create({"spk_id": spk.id, "requested_by": self.worker.id})
        self.MRL.create({
            "request_id": req.id, "product_id": product.id, "qty_requested": qty})
        return req
