# -*- coding: utf-8 -*-
{
    "name": "LGX — Tarif, Penawaran, Kontrak",
    "summary": "Rate card beli dan jual sebagai record terpisah, penawaran berversi, "
               "kontrak pelanggan, dan konversi penawaran menjadi job berikut akrual biayanya.",
    "description": """
LGX — Pricing (custom_lgx_pricing)
==================================

**Harga beli dan harga jual adalah record terpisah**, bukan dua kolom pada
record yang sama. Keduanya punya sumber, pemilik, dan siklus pembaruan yang
berbeda: harga beli datang dari carrier dan berubah saat kontrak carrier
diperbarui; harga jual dimiliki penjualan dan berubah saat strategi harga
berubah. Menggabungkannya membuat setiap pembaruan tarif carrier menyentuh
harga jual yang sudah dijanjikan ke pelanggan.

**Konversi penawaran ke job membuat DUA baris charge per baris penawaran** —
satu pendapatan dari harga jual, satu biaya dari harga beli, keduanya berstatus
estimasi. Inilah yang membuat akrual biaya terbentuk sejak job lahir, bukan
menunggu tagihan vendor yang baru datang dua sampai enam minggu kemudian.

**Faktor volumetrik hidup di rate card**, bukan di kode. Angka 6000 untuk udara
adalah default IATA, tetapi tiap carrier boleh berbeda, dan pembulatan berbeda
lagi. Menaruhnya di kode berarti setiap carrier baru adalah rilis modul.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job"],
    "capability_tags": ["logistics", "pricing", "rate-card", "quotation", "contract"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_pricing_rules.xml",
        "data/lgx_pricing_sequence.xml",
        "views/lgx_rate_card_views.xml",
        "views/lgx_quote_views.xml",
        "views/lgx_contract_views.xml",
        "views/lgx_job_views_inherit.xml",
        "views/lgx_pricing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
