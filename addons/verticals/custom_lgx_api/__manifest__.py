# -*- coding: utf-8 -*-
{
    "name": "LGX — Fasad API",
    "summary": "Permukaan API bernama jelas di atas /json/2 untuk portal pelacakan, "
               "aplikasi pengemudi, dan pemindai gudang.",
    "description": """
LGX — API (custom_lgx_api)
==========================

**Jalur yang dipakai: modul `rpc` bawaan Odoo 19** — endpoint
``POST /json/2/<model>/<method>``, ``auth='bearer'``, API key sebagai Bearer
token. Nol dependensi eksternal, seluruhnya CE, dan ``api_doc`` menyajikan
``/doc`` dengan playground otomatis. Yang ditolak dan alasannya ada di §13.1
spesifikasi; ringkasnya: XML-RPC lama deprecated, OCA ``base_rest`` belum
dimigrasi ke 19.0, OCA ``auth_jwt`` tidak ada di 19.0.

**Model mentah TIDAK diekspos.** Setiap panggilan ``/json/2`` berjalan dalam
transaksi SQL sendiri, jadi operasi harus atomik dan tidak boleh dirangkai antar
request. Fasad ``lgx.api.service`` memberi satu method per operasi lengkap —
bukan empat panggilan yang harus berhasil semuanya.

**Bentuk respons mengikuti konvensi `custom_hms_api`** yang sudah terbukti
dipakai frontend Next.js di repo ini: amplop ``{"error": {"code", "message",
"fields"}}`` untuk galat, dan data polos untuk sukses. Membuat konvensi kedua di
repo yang sama berarti setiap frontend harus tahu sedang bicara dengan yang mana.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "custom_lgx_ff", "custom_lgx_tms", "custom_lgx_wms", "rpc"],
    "capability_tags": ["logistics", "api", "rest", "tracking", "driver-app", "scanner"],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_api_data.xml",
        "views/lgx_api_device_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
