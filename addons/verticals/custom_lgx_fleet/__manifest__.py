# -*- coding: utf-8 -*-
{
    "name": "LGX — Armada",
    "summary": "Perluasan fleet.vehicle: JBI/JBB dan dimensi bak untuk validasi ODOL, "
               "KIR, STNK, Kartu Pengawasan, GPS, dan pool kendaraan.",
    "description": """
LGX — Armada (custom_lgx_fleet)
===============================

**Kapasitas legal, bukan kapasitas aktual.** Zero ODOL mengubah model bisnis
trucking: tarif harus dihitung di atas JBI, bukan di atas apa yang sebenarnya
muat. Karena itu JBI dan dimensi bak adalah field master, dan perencanaan muatan
memvalidasi terhadapnya.

⚠ Tanggal penegakan disimpan sebagai ``ir.config_parameter``
``lgx.odol_enforcement_date`` dengan default 1 Januari 2027. Tanggal itu berasal
dari pernyataan pejabat dan siaran pers, **bukan peraturan yang sudah terbit**
(Lampiran A butir A12b). Sebelum tanggal itu sistem hanya memperingatkan; sejak
tanggal itu ia menolak. Keduanya diubah lewat konfigurasi, tanpa menyentuh kode.

Masa berlaku dokumen kendaraan diperlakukan sebagai DATA, bukan konstanta:
angka "6 bulan" untuk KIR beredar luas di sumber sekunder dan belum terkonfirmasi
ke PM 19/2021 fulltext (butir A5).
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_base", "fleet"],
    "capability_tags": ["logistics", "fleet", "odol", "compliance", "indonesia"],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_fleet_data.xml",
        "views/lgx_fleet_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
