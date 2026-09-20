# -*- coding: utf-8 -*-
"""Data demo gudang 3PL: dua pemilik, stok di luar neraca, dan tagihan pallet-hari."""
import logging
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    company = env.company
    today = fields.Date.context_today(env["res.company"])

    if env["lgx.wms.client"].search_count([]):
        _logger.info("Data demo gudang sudah ada; pembangkitan dilewati.")
        return

    category = env.ref("custom_lgx_wms.product_category_client_goods")
    warehouse = env["stock.warehouse"].search([("company_id", "=", company.id)], limit=1)
    Partner = env["res.partner"]

    def partner(name, **values):
        record = Partner.search([("name", "=", name)], limit=1)
        return record or Partner.create(dict({"name": name, "company_type": "company"}, **values))

    sla = env["lgx.wms.sla"].create({
        "name": "SLA Standar 3PL ATHERA",
        "receiving_hours": 4.0, "putaway_hours": 8.0, "order_cutoff_time": 14.0,
        "dispatch_same_day": True,
        "inventory_accuracy_target": 99.5, "order_accuracy_target": 99.0,
        "on_time_delivery_target": 95.0,
        "penalty_note": "Penalti 2% dari tagihan bulanan per poin persentase di bawah target.",
    })

    clients = []
    specs = [
        ("Fast Moving Consumer Goods", "FMCG", "PT Maju Boga Nusantara", 48.0, 12500.0, 7),
        ("Suku Cadang Otomotif", "SPARE", "PT Karya Otoparts", 120.0, 9000.0, 3),
    ]
    for label, code, partner_name, per_pallet, rate, free_days in specs:
        owner = partner(partner_name, lgx_is_warehouse_client=True)
        job = env["lgx.job"].create({
            "job_type": "warehouse", "transport_mode": "land",
            "customer_id": owner.id,
            "customer_reference": "3PL-%s" % code,
            "etd": today - timedelta(days=45),
        })
        client = env["lgx.wms.client"].create({
            "name": partner_name, "code": code,
            "partner_id": owner.id, "owner_partner_id": owner.id,
            "product_category_id": category.id,
            "warehouse_id": warehouse.id,
            "job_id": job.id,
            "sla_id": sla.id,
            "free_days_storage": free_days,
            "minimum_monthly_charge": 25_000_000,
            "units_per_pallet_default": per_pallet,
            "storage_rule_ids": [(0, 0, {
                "name": "Penyimpanan %s per pallet-hari" % label,
                "basis": "per_pallet_day",
                "rate": rate,
                "free_days": free_days,
                "valid_from": today - timedelta(days=180),
                "tier_ids": [
                    (0, 0, {"min_volume": 2000.0, "rate": rate * 0.92}),
                    (0, 0, {"min_volume": 5000.0, "rate": rate * 0.85}),
                ],
            })],
            "handling_rule_ids": [
                (0, 0, {"name": "Handling masuk", "operation": "inbound",
                        "basis": "per_pallet", "rate": 18_000,
                        "valid_from": today - timedelta(days=180)}),
                (0, 0, {"name": "Handling keluar", "operation": "outbound",
                        "basis": "per_line", "rate": 6_500,
                        "valid_from": today - timedelta(days=180)}),
            ],
        })
        client.action_activate()
        clients.append(client)

    # Produk milik klien — kategori NON-VALUASI, jadi tidak masuk neraca.
    products = []
    catalogue = [
        ("Mi Instan Goreng kardus 40", "SKU-FMCG-001", 48.0, 0.032, 8.4, 0),
        ("Minyak Goreng 2L kardus 6", "SKU-FMCG-002", 40.0, 0.028, 11.2, 0),
        ("Kampas Rem Cakram set", "SKU-SPARE-001", 120.0, 0.006, 2.1, 1),
        ("Filter Oli karton 24", "SKU-SPARE-002", 96.0, 0.011, 4.8, 1),
    ]
    for name, code, per_pallet, volume, weight, client_index in catalogue:
        product = env["product.product"].create({
            "name": name, "default_code": code, "barcode": "899%010d" % (len(products) + 1),
            "type": "consu", "is_storable": True,
            "categ_id": category.id,
            "lgx_units_per_pallet": per_pallet,
            "volume": volume, "weight": weight,
        })
        products.append((product, clients[client_index]))

    # Stok masuk lewat picking sungguhan, supaya owner_id benar-benar terpasang.
    picking_type = env["stock.picking.type"].search([
        ("code", "=", "incoming"), ("warehouse_id", "=", warehouse.id)], limit=1)
    supplier_location = env.ref("stock.stock_location_suppliers")
    for product, client in products:
        picking = env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "partner_id": client.partner_id.id,
            "lgx_wms_client_id": client.id,
            "owner_id": client.owner_partner_id.id,
            "location_id": supplier_location.id,
            "location_dest_id": picking_type.default_location_dest_id.id,
            "move_ids": [(0, 0, {
                "product_id": product.id,
                "product_uom_qty": 2400,
                "description_picking": product.name,
                "location_id": supplier_location.id,
                "location_dest_id": picking_type.default_location_dest_id.id,
            })],
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = 2400
            move.picked = True
        picking.button_validate()

    # Potret okupansi mundur 30 hari. Cron harian hanya memotret HARI INI, jadi
    # tanpa ini proses penagihan tidak punya apa pun untuk dihitung.
    Snapshot = env["lgx.wms.occupancy.snapshot"]
    for offset in range(30, 0, -1):
        Snapshot._cron_take_snapshot(for_date=today - timedelta(days=offset))

    run = env["lgx.wms.billing.run"].create({
        "client_id": clients[0].id,
        "date_from": today - timedelta(days=30),
        "date_to": today - timedelta(days=1),
    })
    run.action_compute()
    _logger.info("Data demo gudang dibuat: %s klien, %s produk, potret %s baris, proses %s = %s",
                 len(clients), len(products), Snapshot.search_count([]), run.name, run.amount_total)
