# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Data Demo",
    "summary": "Rumah sakit fiktif lengkap untuk presentasi: poli, dokter, bangsal, obat, "
               "tarif, antrian, jadwal, dan skenario pasien end-to-end.",
    "description": """
SIMRS — Data Demo (custom_hms_demo)
===================================

Membuat satu rumah sakit fiktif yang cukup lengkap untuk memperagakan seluruh
alur: **RS Athera Medika**, 6 poli, 12 dokter, 3 bangsal/30 bed, ±200 item obat,
tarif berlapis per kelas dan penjamin, layanan antrian dengan loket dan layar,
jadwal praktik, nurse station, serta kasir.

**Hanya boleh terpasang di database demo.** ``post_init_hook`` menolak berjalan
kecuali nama database berakhiran ``_demo``. Data demo yang menyelinap ke
database produksi adalah kesalahan yang mahal dan sulit dibersihkan: nomor rekam
medis sudah terlanjur terpakai dan tidak dapat dipakai ulang.

Data dibuat lewat kode, bukan XML: 200 obat dan 50 pasien dalam bentuk XML
berarti ribuan baris yang tidak bisa dibaca siapa pun, sementara generator
membuat pola datanya justru terlihat.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_api"],
    "capability_tags": ["simrs", "demo-data"],
    "data": [
        "security/ir.model.access.csv",
        "views/hms_demo_views.xml",
        "data/hms_demo_seed.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
