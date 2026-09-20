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

Tanggal penegakan disimpan sebagai ``ir.config_parameter``
``lgx.odol_enforcement_date`` dengan default 1 Januari 2027. Sebelum tanggal itu
sistem hanya memperingatkan; sejak tanggal itu ia menolak. Keduanya diubah lewat
konfigurasi, tanpa menyentuh kode — dan itu bukan kerapian, melainkan antisipasi.

Pemeriksaan A12b (2026-09-20): larangan ODOL sudah punya dasar hukum terbit —
UU 22/2009, PP 55/2012, Permenhub 60/2019, Permenhub 18/2021 — dan ditegakkan di
jembatan timbang hari ini. Yang **belum** terbit adalah dasar penegakan penuh per
1 Januari 2027: Perpres Penguatan Logistik Nasional masih rancangan, dan yang
berjalan baru uji coba terbatas 27 Januari - 31 Mei 2026. Tanggal itu target
kebijakan, jadi harapkan ia bergeser.

Masa berlaku dokumen kendaraan diperlakukan sebagai DATA, bukan konstanta, dan
pemeriksaan A5 (2026-09-20) menunjukkan mengapa. PM 19/2021 tidak memberi satu
angka: uji berkala pendaftaran berlaku 1 tahun, perpanjangan berikutnya 6 bulan.
Karena itu ``lgx_kir_expiry_date`` disalin dari kartu lulus uji dan tidak pernah
dihitung dari masa berlaku — kartunya membawa tanggalnya sendiri.

Pemeriksaan A6 (2026-09-20): Kartu Pengawasan berlaku **1 tahun**. Yang penting
dibedakan, dan sering tertukar: izin penyelenggaraan angkutannya berlaku
**5 tahun**, kartu pengawasannya hanya satu. Modul ini menyimpan yang satu
tahun (``lgx_kp_expiry_date``, per kendaraan); izin lima tahun itu dokumen
perusahaan dan tidak dimodelkan di sini. Sumbernya halaman layanan Dishub dan
BPTJ, bukan fulltext peraturan — cukup untuk peringatan, belum cukup untuk
dijadikan dasar memblokir.
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
