# -*- coding: utf-8 -*-
{
    "name": "LGX — Data Demo Forwarding",
    "summary": "Pelanggan, carrier, rate card, penawaran, job impor dan ekspor berikut shipment, "
               "kontainer bernomor sah ISO 6346, dan deklarasi pabean.",
    "description": """
LGX — Demo Forwarding (custom_lgx_demo_ff)
==========================================

Dipasang TERPISAH dari modul segmen supaya mendemokan satu segmen tidak menarik
seluruh pohon modul, dan supaya data demo tidak pernah ikut terpasang di
database klien hanya karena modul operasinya dipasang.

Nomor kontainer dihitung digit periksanya, bukan dikarang: nomor demo yang
ditolak validasi sendiri adalah demo yang berhenti di menit kedua.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_ff", "custom_lgx_customs", "custom_lgx_pricing", "custom_lgx_billing"],
    "capability_tags": ["logistics", "demo-data", "freight-forwarding"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
