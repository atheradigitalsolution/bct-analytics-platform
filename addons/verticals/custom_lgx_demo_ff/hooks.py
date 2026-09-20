# -*- coding: utf-8 -*-
"""Bangkitkan data demo forwarding.

Dibangkitkan dalam Python, bukan XML, karena dua hal harus DIHITUNG dan bukan
diketik: digit periksa ISO 6346 pada nomor kontainer, dan tanggal yang relatif
terhadap hari pemasangan. Data demo bertanggal mati akan tampak sudah lewat
berminggu-minggu saat benar-benar didemokan.
"""
import logging
from datetime import timedelta

from odoo import api, fields, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ISO6346_LETTERS = {
    "A": 10, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17, "H": 18,
    "I": 19, "J": 20, "K": 21, "L": 23, "M": 24, "N": 25, "O": 26, "P": 27,
    "Q": 28, "R": 29, "S": 30, "T": 31, "U": 32, "V": 34, "W": 35, "X": 36,
    "Y": 37, "Z": 38,
}


def container_number(prefix, serial):
    """Nomor kontainer lengkap dengan digit periksa yang BENAR."""
    body = "%s%06d" % (prefix, serial)
    total = 0
    for index, char in enumerate(body[:4]):
        total += ISO6346_LETTERS[char] * (2 ** index)
    for index, char in enumerate(body[4:]):
        total += int(char) * (2 ** (index + 4))
    return "%s%d" % (body, (total % 11) % 10)


def post_init_hook(env):
    if isinstance(env, object) and not hasattr(env, "ref"):  # kompatibilitas pemanggilan lama
        env = api.Environment(env, SUPERUSER_ID, {})
    company = env.company
    company.lgx_setup_default_accounts()
    today = fields.Date.context_today(env["res.company"])

    Partner = env["res.partner"]

    def partner(name, **values):
        record = Partner.search([("name", "=", name)], limit=1)
        if record:
            return record
        return Partner.create(dict({"name": name, "company_type": "company"}, **values))

    customer = partner("PT Sinar Kencana Elektronik", lgx_is_consignee=True,
                       vat="9911223344556677")
    shipper = partner("Shenzhen Everbright Trading Co., Ltd", lgx_is_shipper=True,
                      country_id=env.ref("base.cn").id)
    carrier = partner("Evergreen Marine Indonesia", lgx_is_carrier=True,
                      lgx_scac="EGLV", lgx_free_days_demurrage=7, lgx_free_days_detention=5)
    agent = partner("Ocean Link Logistics (Shanghai)", lgx_is_agent=True,
                    lgx_agent_profit_share=35.0, country_id=env.ref("base.cn").id)
    ppjk = partner("PT Athera Kepabeanan Nusantara", lgx_is_ppjk=True,
                   lgx_nib="1234567890123", lgx_customs_access_type="ppjk",
                   vat="9900112233445577")
    depot = partner("Depo Kontainer Cakung Jaya", lgx_is_depot=True)
    treasury = partner("Kas Negara — Bea Cukai Tanjung Priok")
    env.ref("custom_lgx_base.office_040300").partner_id = treasury

    # Ahli Kepabeanan bersertifikat, masih berlaku.
    expert = env["lgx.customs.expert"].search([("certificate_no", "=", "AK-2024-01881")], limit=1)
    if not expert:
        expert = env["lgx.customs.expert"].create({
            "name": "Rina Kartika, A.Md.",
            "certificate_no": "AK-2024-01881",
            "certificate_date": today - timedelta(days=400),
            "certificate_expiry": today + timedelta(days=700),
            "ppjk_partner_id": ppjk.id,
            "npwp": "9900112233445588",
        })

    origin = env.ref("custom_lgx_base.loc_cnsha")
    destination = env.ref("custom_lgx_base.loc_idjkt")
    ofr = env.ref("custom_lgx_base.charge_ofr")
    thc = env.ref("custom_lgx_base.charge_thc_d")
    doc = env.ref("custom_lgx_base.charge_doc")
    cus = env.ref("custom_lgx_base.charge_cus")
    trk = env.ref("custom_lgx_base.charge_trk")
    ctype_40hc = env.ref("custom_lgx_base.ctype_40hc")

    Card = env["lgx.rate.card"]
    sell = Card.search([("code", "=", "DEMO-SELL-SHAJKT")], limit=1)
    if not sell:
        sell = Card.create({
            "name": "Jual Shanghai → Jakarta FCL",
            "code": "DEMO-SELL-SHAJKT",
            "direction": "sell", "transport_mode": "sea", "load_type": "fcl",
            "origin_id": origin.id, "destination_id": destination.id,
            "valid_from": today - timedelta(days=90),
            "valid_to": today + timedelta(days=275),
            "line_ids": [
                (0, 0, {"charge_code_id": ofr.id, "basis": "per_container",
                        "container_type_id": ctype_40hc.id, "price": 14_500_000}),
                (0, 0, {"charge_code_id": thc.id, "basis": "per_container", "price": 1_850_000}),
                (0, 0, {"charge_code_id": doc.id, "basis": "per_bl", "price": 850_000}),
                (0, 0, {"charge_code_id": cus.id, "basis": "per_shipment", "price": 2_500_000}),
                (0, 0, {"charge_code_id": trk.id, "basis": "per_trip", "price": 3_200_000}),
            ],
        })
        sell.action_activate()
    buy = Card.search([("code", "=", "DEMO-BUY-SHAJKT")], limit=1)
    if not buy:
        buy = Card.create({
            "name": "Beli Shanghai → Jakarta FCL (Evergreen)",
            "code": "DEMO-BUY-SHAJKT",
            "direction": "buy", "partner_id": carrier.id,
            "transport_mode": "sea", "load_type": "fcl",
            "origin_id": origin.id, "destination_id": destination.id,
            "valid_from": today - timedelta(days=90),
            "valid_to": today + timedelta(days=275),
            "line_ids": [
                (0, 0, {"charge_code_id": ofr.id, "basis": "per_container",
                        "container_type_id": ctype_40hc.id, "price": 10_800_000}),
                (0, 0, {"charge_code_id": thc.id, "basis": "per_container", "price": 1_850_000}),
                (0, 0, {"charge_code_id": trk.id, "basis": "per_trip", "price": 2_400_000}),
            ],
        })
        buy.action_activate()

    Quote = env["lgx.quote"]
    if Quote.search_count([("customer_id", "=", customer.id)]):
        _logger.info("Data demo forwarding sudah ada; pembangkitan dilewati.")
        return

    quote = Quote.create({
        "customer_id": customer.id,
        "date": today - timedelta(days=30),
        "validity_date": today + timedelta(days=5),
        "job_type": "ff_import", "transport_mode": "sea", "load_type": "fcl",
        "origin_id": origin.id, "destination_id": destination.id,
        "incoterm_id": env["account.incoterms"].search([("code", "=", "FOB")], limit=1).id,
    })
    quote.action_load_rates()
    quote.action_send()
    quote.action_accept()
    quote.action_create_job()
    job = quote.job_id
    job.write({
        "shipper_id": shipper.id,
        "consignee_id": customer.id,
        "agent_id": agent.id,
        "is_nomination": True,
        "customer_reference": "PO-SKE-2026-0917",
        "etd": today - timedelta(days=22),
        "eta": today - timedelta(days=4),
        "atd": today - timedelta(days=22),
        "ata": today - timedelta(days=3),
        "fx_rate_book": 15_800.0,
        "fx_rate_tax": 15_912.0,
        "fx_rate_source": "KMK mingguan",
        "fx_rate_date": today - timedelta(days=5),
    })
    job.action_confirm()
    job.action_start()

    shipment = env["lgx.shipment"].create({
        "job_id": job.id,
        "transport_mode": "sea", "direction": "import", "load_type": "fcl",
        "carrier_id": carrier.id,
        "vessel_name": "EVER LOGIC", "voyage_no": "0914-091E",
        "master_doc_no": "EGLV142600512345",
        "house_doc_no": "ATHJKT2600118",
        "pol_id": origin.id, "pod_id": destination.id,
        "etd": job.etd, "eta": job.eta, "atd": job.atd, "ata": job.ata,
        "commodity_id": env["lgx.commodity"].create({"name": "Elektronik konsumen"}).id,
        "goods_description": "CONSUMER ELECTRONICS — 1200 CARTONS",
    })
    containers = env["lgx.container"].create([{
        "shipment_id": shipment.id,
        "container_no": container_number("EGHU", 601234 + index),
        "seal_no": "SGL%06d" % (778100 + index),
        "container_type_id": ctype_40hc.id,
        "gross_weight": 21500 + index * 120,
        "tare_weight": 3970,
        "discharge_date": today - timedelta(days=3),
        "free_days_demurrage": 7,
        "free_days_detention": 5,
        "gate_out_date": today - timedelta(days=1) if index == 0 else False,
        "depot_id": env.ref("custom_lgx_base.loc_depo_cakung").id,
    } for index in range(2)])
    env["lgx.package"].create({
        "shipment_id": shipment.id,
        "container_id": containers[0].id,
        "description": "Karton elektronik",
        "package_type": "carton",
        "quantity": 1200,
        "length_cm": 60, "width_cm": 40, "height_cm": 40,
        "gross_weight_kg": 21500,
    })
    shipment.action_book()
    shipment.action_depart()
    shipment.action_arrive()

    declaration = env["lgx.customs.declaration"].create({
        "job_id": job.id,
        "shipment_id": shipment.id,
        "doc_type": "bc20_pib",
        "principal_id": customer.id,
        "ppjk_id": ppjk.id,
        "customs_expert_id": expert.id,
        "customs_office_id": env.ref("custom_lgx_base.office_040300").id,
        "currency_id": env.ref("base.USD").id,
        "fx_rate_tax": 15_912.0,
        "aju_number": "000001-000123-20260917-000045",
        "importer_has_api": True,
        "line_ids": [
            (0, 0, {"hs_code_id": env.ref("custom_lgx_customs.hs_84713020").id,
                    "description": "Laptop 14 inci", "quantity": 400,
                    "country_of_origin_id": env.ref("base.cn").id,
                    "customs_value": 86_000.0}),
            (0, 0, {"hs_code_id": env.ref("custom_lgx_customs.hs_39269099").id,
                    "description": "Casing plastik", "quantity": 800,
                    "country_of_origin_id": env.ref("base.cn").id,
                    "customs_value": 9_400.0}),
        ],
    })
    customer.write({"lgx_nib": "9988776655443", "lgx_customs_access_type": "importer"})

    # Checklist dokumen MENAHAN milestone kepabeanan, jadi dokumennya harus ada
    # sebelum deklarasi diajukan. Itu justru yang didemokan di sini: alur yang
    # berhenti karena dokumen kurang, bukan alur yang mulus karena aturannya
    # dimatikan untuk demo.
    Document = env["lgx.document"]
    Checklist = env["lgx.document.checklist"]
    if "checklist_ids" in job._fields:
        job.action_generate_checklist()
        demo_documents = {
            "custom_lgx_base.doctype_packing": ("PL/EVB/2026/0917", None),
            "custom_lgx_base.doctype_ci": ("INV/EVB/2026/0917", None),
            "custom_lgx_base.doctype_hbl": (shipment.house_doc_no, None),
            "custom_lgx_base.doctype_sppb": ("SPPB-040300-2026-004512", None),
            "custom_lgx_base.doctype_do": ("DO/EGLV/2026/09/0771", None),
        }
        for xmlid, (number, expiry) in demo_documents.items():
            doc_type = env.ref(xmlid)
            document = Document.create({
                "name": number,
                "document_type_id": doc_type.id,
                "job_id": job.id,
                "partner_id": customer.id,
                "issue_date": today - timedelta(days=6),
                "expiry_date": expiry,
            })
            item = Checklist.search([
                ("job_id", "=", job.id), ("document_type_id", "=", doc_type.id)], limit=1)
            if item:
                item.document_id = document

    declaration.action_submit()
    declaration.action_receive()
    declaration.action_respond(channel="green")
    declaration.action_release()
    declaration.action_generate_job_charges()

    job.action_post_accrual()
    _logger.info("Data demo forwarding dibuat: job %s, shipment %s, %s kontainer, deklarasi %s",
                 job.name, shipment.name, len(containers), declaration.name)
