# -*- coding: utf-8 -*-
{
    "name": "LGX — Penagihan Gudang 3PL",
    "summary": "Potret okupansi harian yang idempoten, tarif penyimpanan dan handling berjenjang, "
               "serta proses penagihan periodik yang dapat dipratinjau dan dibatalkan.",
    "description": """
LGX — Penagihan Gudang (custom_lgx_wms_billing)
===============================================

**Penyimpanan ditagih atas RUANG DIKALI WAKTU, bukan atas transaksi.** Untuk
menagih "pallet-hari", sistem harus tahu berapa pallet milik siapa yang ada di
gudang PADA SETIAP HARI — bukan hanya saldo akhir bulan. Itulah sebabnya ada
potret harian, dan itulah model paling sensitif terhadap volume di seluruh
sistem.

**Keputusan yang diambil di depan, bukan ditambal belakangan:**

* **Granularitas per PRODUK**, bukan per pallet. Per produk jauh lebih ringan,
  dan ``pallet_count`` tetap dihitung dari faktor konversi sehingga tarif per
  pallet tetap bisa ditagihkan. Kalau sebuah kontrak benar-benar menuntut
  identitas pallet, itu perubahan yang dianggarkan, bukan asumsi diam-diam.
* **Idempoten per (tanggal, klien, produk, lokasi, lot).** Menjalankan ulang
  cron untuk tanggal yang sama memperbarui baris, tidak menggandakannya —
  ditegakkan unique constraint di Postgres, bukan hanya oleh kehati-hatian cron.
* **Indeks pada (date, client_id)** sejak awal. Perkiraan volume:
  SKU aktif × lokasi terisi × 365 baris per tahun; untuk gudang 5.000 SKU itu
  jutaan baris.
* **Retensi 13 bulan** detail harian, lalu diringkas bulanan.

**Proses penagihan dapat dipratinjau sebelum diposting dan dibatalkan selama
belum difakturkan**, dan hasilnya dapat ditelusuri kembali ke potret harian yang
menjadi dasarnya. Tagihan gudang yang tidak dapat ditelusuri ke okupansi adalah
tagihan yang diperdebatkan setiap bulan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_wms", "custom_lgx_billing"],
    "capability_tags": ["logistics", "wms", "storage-billing", "occupancy", "3pl"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_wms_billing_rules.xml",
        "data/lgx_wms_billing_data.xml",
        "views/lgx_occupancy_views.xml",
        "views/lgx_wms_rule_views.xml",
        "views/lgx_wms_billing_run_views.xml",
        "views/lgx_wms_billing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
