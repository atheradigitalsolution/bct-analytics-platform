# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Master Data",
    "summary": "Fondasi SIMRS di atas Odoo 19 CE: pasien, praktisi, unit layanan, "
               "kelas/ruang/bed, penjamin, tarif, referensi klinis ICD-10/ICD-9-CM.",
    "description": """
SIMRS — Master Data (custom_hms_base)
=====================================

Lapisan master untuk Sistem Informasi Manajemen Rumah Sakit. Semua modul
``custom_hms_*`` lain berdiri di atas modul ini.

**Nomor rekam medis.** ``RM-YYYY-NNNNNN`` dari ``ir.sequence`` per tahun dengan
``implementation='no_gap'``. Nomor diambil di dalam transaksi ``create`` sehingga
20 pendaftaran paralel tidak pernah menghasilkan nomor kembar.

**Tarif berlapis.** ``hms.tariff`` adalah item yang bisa ditagih; harganya hidup
di ``hms.tariff.price`` per (kelas perawatan, penjamin) dengan masa berlaku.
Setiap harga dipecah menjadi jasa sarana / jasa medis / BHP — pemecahan itu yang
nanti dipakai ``custom_hms_unit_pnl`` untuk menghitung jasa medis dokter tanpa
menebak-nebak.

**Kelompok akses.** Tujuh ``res.groups.privilege`` terpisah (pendaftaran, rekam
medis, farmasi, penunjang, keperawatan, kasir, manajemen). Sengaja terpisah:
Odoo 19 merender semua grup yang berbagi satu privilege sebagai satu dropdown
pilih-satu, sehingga satu privilege untuk semua peran akan membuat seorang
perawat kehilangan hak farmasinya begitu form user disimpan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["base", "mail", "contacts", "product", "uom", "hr"],
    "capability_tags": ["simrs", "healthcare", "master-data", "indonesia"],
    "data": [
        "security/hms_groups.xml",
        "security/ir.model.access.csv",
        "security/hms_rules.xml",
        "security/hms_group_implications.xml",
        "data/hms_sequence.xml",
        "data/hms_care_class_data.xml",
        "views/hms_menus.xml",
        "views/hms_patient_views.xml",
        "views/hms_practitioner_views.xml",
        "views/hms_unit_views.xml",
        "views/hms_ward_views.xml",
        "views/hms_payer_views.xml",
        "views/hms_tariff_views.xml",
        "views/hms_reference_views.xml",
        "views/hms_settings_views.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
