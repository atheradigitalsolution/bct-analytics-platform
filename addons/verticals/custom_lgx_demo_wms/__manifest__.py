# -*- coding: utf-8 -*-
{
    "name": "LGX — Data Demo Gudang 3PL",
    "summary": "Dua pemilik barang di satu gudang, stok yang tidak masuk neraca, "
               "potret okupansi 30 hari, dan satu proses penagihan penyimpanan.",
    "description": """
LGX — Demo Gudang (custom_lgx_demo_wms)
=======================================

**Dua pemilik barang, bukan satu.** Segregasi stok tidak dapat didemokan dengan
satu klien: yang harus terlihat adalah bahwa stok klien A tidak muncul di
laporan klien B, dan itu butuh B yang benar-benar ada.

Potret okupansi dibangkitkan mundur 30 hari supaya proses penagihan penyimpanan
punya sesuatu untuk dihitung. Tanpa itu, tagihan pallet-hari akan bernilai nol
dan tidak menunjukkan apa pun.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_wms_billing"],
    "capability_tags": ["logistics", "demo-data", "wms", "3pl"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
