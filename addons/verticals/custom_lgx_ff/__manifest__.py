# -*- coding: utf-8 -*-
{
    "name": "LGX — Freight Forwarding",
    "summary": "Shipment, konsolidasi master/house, B/L & AWB, kontainer dengan validasi ISO 6346, "
               "berat yang ditagih, dan perhitungan demurrage/detensi yang menahan penutupan job.",
    "description": """
LGX — Freight Forwarding (custom_lgx_ff)
========================================

**Konsolidasi adalah mekanisme yang membuat forwarding menguntungkan, dan yang
paling sering salah dimodelkan.** Forwarder membeli satu kontainer penuh dari
pelayaran lalu menjual ruangnya ke banyak pengirim kecil. Akibatnya dokumen
berlapis dua: Master B/L dari carrier ke forwarder, House B/L dari forwarder ke
tiap pengirim. Model datanya karena itu rekursif: satu shipment bisa menjadi
induk shipment lain, P&L konsol dihitung di tingkat master sementara tagihan
terbit di tingkat house.

**Demurrage dan detensi adalah sumber kebocoran nomor satu.** Keduanya berbeda:
demurrage untuk kontainer yang terlalu lama DI DALAM terminal, detensi untuk
kontainer yang sudah KELUAR dan terlambat dikembalikan. Carrier menagihkannya
beberapa minggu kemudian, dan kalau job sudah ditutup, biaya itu tidak pernah
diteruskan ke pelanggan. Karena itu kontainer yang belum kembali MENAHAN job
agar tidak bisa diselesaikan.

**Berat yang ditagih memakai faktor dari rate card, bukan konstanta.** Angka 6000
untuk udara adalah standar IATA, tetapi carrier boleh berbeda dan pembulatan
berbeda lagi.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "custom_lgx_pricing"],
    "capability_tags": ["logistics", "freight-forwarding", "consolidation", "container", "demurrage"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_ff_rules.xml",
        "data/lgx_ff_sequence.xml",
        "views/lgx_shipment_views.xml",
        "views/lgx_container_views.xml",
        "views/lgx_job_ff_views.xml",
        "views/lgx_ff_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
