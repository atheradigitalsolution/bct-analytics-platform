# -*- coding: utf-8 -*-
{
    "name": "LGX — Jembatan Trucking ⇄ Forwarding",
    "summary": "Menautkan trip haulage ke kontainer forwarding, dan memutakhirkan tanggal "
               "gerbang kontainer dari pergerakan trip.",
    "description": """
LGX — Jembatan Trucking ⇄ Forwarding (custom_lgx_tms_ff)
========================================================

Modul kecil dengan satu alasan keberadaan: ``custom_lgx_tms`` sengaja TIDAK
bergantung pada ``custom_lgx_ff``. Klien trucking murni tidak boleh dipaksa
memasang seluruh lapisan forwarding hanya untuk mengelola trip.

Tetapi ketika keduanya memang dipasang, trip haulage jelas mengangkut kontainer
yang sama yang dilacak forwarding — dan tanggal keluar/masuk gerbang yang
menentukan detensi justru diketahui oleh trip, bukan oleh staf forwarding.
Membiarkan keduanya terpisah berarti tanggal gerbang diketik dua kali, lalu
berbeda, lalu perhitungan detensi salah.

Jembatan ini yang menyambungkannya — dan ia adalah dependency yang jujur:
ia bergantung pada keduanya, sementara keduanya tidak bergantung satu sama lain.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_tms", "custom_lgx_ff"],
    "capability_tags": ["logistics", "trucking", "forwarding", "container-haulage", "bridge"],
    "data": ["views/lgx_trip_ff_views.xml"],
    "installable": True,
    "application": False,
    "auto_install": True,
}
