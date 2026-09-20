# -*- coding: utf-8 -*-
{
    "name": "LGX — Integrasi CEISA 4.0",
    "summary": "Pengiriman deklarasi pabean host-to-host ke CEISA 4.0 lewat antrian, "
               "dengan OAuth2 client credentials, token yang diperiksa saat dijalankan, "
               "dan mode manual untuk kantor pabean yang belum wajib.",
    "description": """
LGX — CEISA 4.0 (custom_lgx_ceisa)
==================================

**Tidak ada panggilan HTTP sinkron dari dalam transaksi ORM.** Tombol "Kirim ke
CEISA" hanya membuat satu baris `lgx.integration.message` dan mengantrikan job;
HTTP-nya terjadi di runner `queue_job`. Memanggil Bea Cukai dari dalam transaksi
pengguna berarti kursor database ditahan selama jaringan lambat, dan satu
gangguan di sisi mereka menjadi tabel terkunci di sisi kita.

**Token diperiksa saat job DIJALANKAN, bukan saat dijadwalkan.** Masa berlaku
access token sangat pendek. Job yang mengambil token saat dijadwalkan lalu
berjalan lima menit kemudian akan mengirim dengan token yang sudah mati — dan
gagalnya terlihat sebagai 401 yang membingungkan, bukan sebagai token basi.
Karena itu `_lgx_ceisa_token()` dipanggil tepat sebelum request, selalu.

**Kantor pabean yang belum wajib CEISA 4.0 tidak dikirimi apa pun.** Penetapan
mandatory berjalan bertahap per kantor dan per layanan. Mencoba mengirim ke
kantor yang belum wajib menghasilkan penolakan yang tidak ada artinya, dan
antrian yang penuh galat permanen adalah antrian yang berhenti dibaca orang.

⚠ Endpoint, alur OAuth, dan masa berlaku token adalah PERKIRAAN TERBAIK dari
dokumentasi publik dan belum diverifikasi ke lingkungan development sungguhan
(butir A20 di Lampiran A). Semuanya konfigurasi, bukan konstanta — mengganti
base URL dan nama field tidak menuntut menyentuh kode.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_customs", "queue_job"],
    "capability_tags": ["logistics", "customs", "ceisa", "integration", "indonesia", "queue-job"],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_ceisa_data.xml",
        "views/res_config_settings_views.xml",
        "views/lgx_ceisa_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
