# -*- coding: utf-8 -*-
{
    "name": "LGX — Data Demo Trucking",
    "summary": "Armada dengan JBI dan dokumen, pengemudi ber-SIM, rute bertarif, "
               "dan trip lengkap dengan POD serta uang jalan yang dipertanggungjawabkan.",
    "description": """
LGX — Demo Trucking (custom_lgx_demo_tms)
=========================================

Satu trip sengaja dibiarkan MELEBIHI JBI supaya validasi ODOL terlihat bekerja
di layar, bukan hanya di tes. Demo yang semuanya mulus tidak menunjukkan apa pun
tentang kontrol yang justru menjadi alasan sistem ini dibeli.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_tms", "custom_lgx_driver", "custom_lgx_pricing"],
    "capability_tags": ["logistics", "demo-data", "trucking"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
