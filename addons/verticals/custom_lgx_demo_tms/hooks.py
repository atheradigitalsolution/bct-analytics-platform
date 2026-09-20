# -*- coding: utf-8 -*-
"""Data demo trucking: armada, pengemudi, rute, dan trip yang benar-benar berjalan."""
import base64
import logging
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)

SIGNATURE = base64.b64encode(b"demo-signature").decode()


def post_init_hook(env):
    company = env.company
    today = fields.Date.context_today(env["res.company"])
    now = fields.Datetime.now()

    if env["lgx.trip"].search_count([]):
        _logger.info("Data demo trucking sudah ada; pembangkitan dilewati.")
        return

    Partner = env["res.partner"]

    def partner(name, **values):
        record = Partner.search([("name", "=", name)], limit=1)
        return record or Partner.create(dict({"name": name, "company_type": "company"}, **values))

    customer = partner("PT Nusantara Distribusi Pangan", vat="9922334455667788")
    consignee = partner("Gudang Regional Bandung — NDP")

    brand = env["fleet.vehicle.model.brand"].search([("name", "=", "Hino")], limit=1) \
        or env["fleet.vehicle.model.brand"].create({"name": "Hino"})
    model_tronton = env["fleet.vehicle.model"].search(
        [("name", "=", "FM 260 JD"), ("brand_id", "=", brand.id)], limit=1) \
        or env["fleet.vehicle.model"].create({"name": "FM 260 JD", "brand_id": brand.id})
    model_cdd = env["fleet.vehicle.model"].search(
        [("name", "=", "Dutro 130 HD"), ("brand_id", "=", brand.id)], limit=1) \
        or env["fleet.vehicle.model"].create({"name": "Dutro 130 HD", "brand_id": brand.id})

    pool = env.ref("custom_lgx_base.loc_cikarang")
    vehicles = env["fleet.vehicle"].create([
        {
            "model_id": model_tronton.id, "license_plate": "B 9012 TRN",
            "lgx_is_freight": True,
            "lgx_category_id": env.ref("custom_lgx_fleet.vcat_tronton").id,
            "lgx_jbb_kg": 26000, "lgx_jbi_kg": 24000, "lgx_kerb_weight_kg": 8600,
            "lgx_body_length_mm": 8200, "lgx_body_width_mm": 2400, "lgx_body_height_mm": 2200,
            # Dimensi tipe WAJIB diisi sejak A12: tanpanya kendaraan
            # berstatus "tidak dapat divalidasi", dan itu bukan "aman".
            "lgx_type_length_mm": 8200, "lgx_type_width_mm": 2400, "lgx_type_height_mm": 2200,
            "lgx_axle_configuration": "1.22",
            "lgx_kir_number": "KIR-JKT-118822", "lgx_kir_expiry_date": today + timedelta(days=45),
            "lgx_stnk_number": "STNK-0091827", "lgx_stnk_expiry_date": today + timedelta(days=210),
            "lgx_kp_number": "KP-2026-0451", "lgx_kp_expiry_date": today + timedelta(days=20),
            "lgx_gps_device_id": "GPS-88-0912", "lgx_gps_provider": "Cartrack",
            "lgx_pool_location_id": pool.id,
        },
        {
            "model_id": model_cdd.id, "license_plate": "B 9455 CDD",
            "lgx_is_freight": True,
            "lgx_category_id": env.ref("custom_lgx_fleet.vcat_cdd").id,
            "lgx_jbb_kg": 8250, "lgx_jbi_kg": 8000, "lgx_kerb_weight_kg": 3100,
            "lgx_body_length_mm": 4300, "lgx_body_width_mm": 2000, "lgx_body_height_mm": 1900,
            "lgx_type_length_mm": 4300, "lgx_type_width_mm": 2000, "lgx_type_height_mm": 1900,
            "lgx_axle_configuration": "1.2",
            "lgx_kir_number": "KIR-JKT-118901", "lgx_kir_expiry_date": today - timedelta(days=5),
            "lgx_stnk_number": "STNK-0091833", "lgx_stnk_expiry_date": today + timedelta(days=90),
            "lgx_gps_device_id": "GPS-88-0977", "lgx_gps_provider": "Cartrack",
            "lgx_pool_location_id": pool.id,
        },
    ])

    drivers = env["lgx.driver"].create([
        {
            "name": "Budi Santoso",
            "partner_id": partner("Budi Santoso", company_type="person").id,
            "employee_code": "DRV-001", "phone": "+62 812-1100-2201",
            "sim_number": "0302-1105-880011", "sim_class": "b2_umum",
            "sim_expiry_date": today + timedelta(days=430),
            "medical_check_date": today - timedelta(days=120),
            "medical_valid_until": today + timedelta(days=245),
            "home_pool_id": pool.id, "performance_score": 92.5,
        },
        {
            "name": "Agus Priyanto",
            "partner_id": partner("Agus Priyanto", company_type="person").id,
            "employee_code": "DRV-002", "phone": "+62 812-1100-2202",
            "sim_number": "0302-1105-880042", "sim_class": "b1_umum",
            "sim_expiry_date": today + timedelta(days=25),
            "home_pool_id": pool.id, "performance_score": 87.0,
        },
    ])

    route = env["lgx.route"].create({
        "code": "CKR-BDO",
        "origin_location_id": pool.id,
        "destination_location_id": env.ref("custom_lgx_base.loc_bandung").id,
        "distance_km": 145, "standard_duration_hours": 4.5,
        "toll_estimate": 180_000, "fuel_estimate": 520_000,
        "tariff_ids": [(0, 0, {
            "vehicle_category_id": env.ref("custom_lgx_fleet.vcat_tronton").id,
            "pricing_basis": "per_trip", "price": 4_200_000,
            "standard_advance": 900_000, "valid_from": today - timedelta(days=180),
        })],
    })

    job = env["lgx.job"].create({
        "job_type": "trucking", "transport_mode": "land",
        "customer_id": customer.id,
        "customer_reference": "SPK-NDP-2026-0918",
        "origin_location_id": route.origin_location_id.id,
        "destination_location_id": route.destination_location_id.id,
        "etd": today - timedelta(days=2),
        "eta": today - timedelta(days=1),
    })
    trk = env.ref("custom_lgx_base.charge_trk")
    uj = env.ref("custom_lgx_base.charge_uj")
    env["lgx.job.charge"].create([
        {"job_id": job.id, "charge_code_id": trk.id, "kind": "revenue", "nature": "service",
         "quantity": 1, "unit_price": 4_200_000, "amount_estimated": 4_200_000,
         "currency_id": job.currency_id.id},
        {"job_id": job.id, "charge_code_id": uj.id, "kind": "cost", "nature": "service",
         "partner_id": drivers[0].partner_id.id,
         "quantity": 1, "unit_price": 900_000, "amount_estimated": 900_000,
         "currency_id": job.currency_id.id},
    ])
    job.action_confirm()
    job.action_start()

    # --- trip yang selesai penuh: POD ada, uang jalan ditutup ---------------
    trip = env["lgx.trip"].create({
        "job_id": job.id, "trip_type": "ftl",
        "vehicle_id": vehicles[0].id, "driver_id": drivers[0].id,
        "route_id": route.id,
        "cargo_weight_kg": 12_000, "cargo_volume_cbm": 38, "package_count": 640,
        "planned_start": now - timedelta(days=2, hours=6),
        "planned_end": now - timedelta(days=2),
        "odometer_start": 184_320,
    })
    env["lgx.trip.stop"].create([
        {"trip_id": trip.id, "sequence": 10, "stop_type": "pickup",
         "partner_id": customer.id, "location_id": route.origin_location_id.id,
         "planned_arrival": now - timedelta(days=2, hours=6),
         "actual_arrival": now - timedelta(days=2, hours=6), "qty_planned": 640},
        {"trip_id": trip.id, "sequence": 20, "stop_type": "dropoff",
         "partner_id": consignee.id, "location_id": route.destination_location_id.id,
         "planned_arrival": now - timedelta(days=2, hours=1),
         "actual_arrival": now - timedelta(days=2, hours=1),
         "qty_planned": 640, "qty_delivered": 638, "qty_rejected": 2,
         "rejection_reason": "Dua karton basah, ditolak penerima.",
         "pod_signature": SIGNATURE, "received_by_name": "Hendra (Kepala Gudang)",
         "received_at": now - timedelta(days=2), "pod_source": "manual"},
    ])
    trip.action_create_advance()
    advance = trip.advance_id
    advance.action_approve()
    advance.action_pay()
    env["lgx.trip.expense"].create([
        {"trip_id": trip.id, "advance_id": advance.id, "category": "fuel",
         "amount": 520_000, "quantity": 65, "description": "Solar 65 liter",
         "proof_ids": [(0, 0, {"name": "nota-solar.jpg", "datas": SIGNATURE})]},
        {"trip_id": trip.id, "advance_id": advance.id, "category": "toll",
         "amount": 182_000, "description": "Tol Cikampek–Padalarang",
         "proof_ids": [(0, 0, {"name": "struk-tol.jpg", "datas": SIGNATURE})]},
        {"trip_id": trip.id, "advance_id": advance.id, "category": "meal",
         "amount": 75_000, "description": "Makan pengemudi"},
    ])
    trip.action_assign()
    trip.action_dispatch()
    trip.action_in_transit()
    trip.write({"actual_end": now - timedelta(days=2), "odometer_end": 184_612, "laden_km": 145})
    trip.action_deliver()
    advance.action_settle()
    trip.action_settle()

    # --- trip yang MELEBIHI JBI, sengaja dibiarkan draf --------------------
    # Demo yang semuanya mulus tidak menunjukkan apa pun tentang kontrol yang
    # justru menjadi alasan sistem ini dibeli.
    env["lgx.trip"].create({
        "job_id": job.id, "trip_type": "ftl",
        "vehicle_id": vehicles[1].id, "driver_id": drivers[1].id,
        "route_id": route.id,
        "cargo_weight_kg": 9_500,  # 9,5t + 3,1t kerb = 12,6t melebihi JBI 8t
        "planned_start": now + timedelta(days=1),
        "planned_end": now + timedelta(days=1, hours=8),
    })
    _logger.info("Data demo trucking dibuat: %s kendaraan, %s pengemudi, trip %s",
                 len(vehicles), len(drivers), trip.name)
