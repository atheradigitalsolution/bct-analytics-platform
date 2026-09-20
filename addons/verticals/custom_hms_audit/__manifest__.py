# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Audit Akses Rekam Medis",
    "summary": "Jejak akses rekam medis: siapa membuka data pasien mana, kapan, dari mana.",
    "description": """
SIMRS — Audit Akses Rekam Medis (custom_hms_audit)
==================================================

UU PDP menuntut rumah sakit dapat menunjukkan siapa saja yang pernah membuka
rekam medis seorang pasien. Modul ini menyediakan mixin ``hms.audited`` yang
mencatat pembacaan dan penulisan ke ``hms.access.log``.

**Pencatatan baca itu mahal — dan tetap dilakukan.** Setiap ``read()`` pada
model ber-mixin menulis satu baris per (user, pasien, model, hari), bukan satu
baris per pemanggilan. Tanpa penggabungan harian, membuka satu encounter
menghasilkan puluhan baris identik dan tabel audit menjadi tidak terbaca justru
saat dibutuhkan untuk investigasi.

**Log audit tidak dapat diubah atau dihapus** oleh siapa pun lewat ORM,
termasuk administrator SIMRS. Retensi dijalankan oleh cron dengan batas umur
yang dikonfigurasi, karena penghapusan manual adalah cara paling mudah untuk
menutupi akses yang tidak sah.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_base"],
    "capability_tags": ["simrs", "audit", "pdp", "healthcare"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_audit_cron.xml",
        "views/hms_access_log_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
