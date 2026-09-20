# -*- coding: utf-8 -*-
{
    "name": "LGX — Gudang 3PL",
    "summary": "Operasi multi-pemilik di atas stock bawaan: segregasi owner_id, SLA per klien, "
               "stock opname siklus, dan barang klien yang TIDAK masuk neraca perusahaan.",
    "description": """
LGX — Gudang 3PL (custom_lgx_wms)
=================================

Dibangun DI ATAS ``stock`` bawaan, tidak menggantikannya. Yang ditambahkan hanya
apa yang membedakan gudang 3PL dari gudang biasa.

**Isi gudang bukan aset perusahaan.** Stok milik banyak pemilik berbeda, tidak
boleh bercampur di laporan, dan tidak boleh masuk neraca. Odoo menyediakan
``owner_id`` pada quant dan move line — terkonfirmasi ada di instalasi ini —
tetapi:

**`owner_id` saja TIDAK mengecualikan barang dari valuasi.** Ini keputusan 2 di
Fase 0, dan jawabannya harus dibuktikan, bukan diasumsikan: dengan
``stock_account`` dan valuasi otomatis, penerimaan tetap membentuk jurnal tanpa
memedulikan pemilik. Mekanisme yang dipakai modul ini adalah **kategori produk
non-valuasi khusus barang klien** (``property_valuation = periodic``),
dan itu dibuktikan tes LGX-E07: menerima barang milik klien tidak menghasilkan
satu pun ``account.move``.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "stock", "stock_account"],
    "capability_tags": ["logistics", "wms", "3pl", "multi-owner", "consignment", "sla"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_wms_rules.xml",
        "security/lgx_wms_group_implications.xml",
        "data/lgx_wms_data.xml",
        "views/lgx_wms_client_views.xml",
        "views/lgx_wms_count_views.xml",
        "views/stock_views_inherit.xml",
        "views/lgx_wms_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
