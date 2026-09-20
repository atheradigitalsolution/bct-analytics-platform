# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Order Klinis (CPOE)",
    "summary": "Order dokter terpadu: obat, laboratorium, radiologi, tindakan, asuhan — "
               "satu siklus status yang sama untuk semuanya.",
    "description": """
SIMRS — Order Klinis / CPOE (custom_hms_order)
==============================================

Satu model order untuk semua jenis permintaan. Laboratorium, radiologi,
farmasi dan tindakan punya isi yang berbeda tetapi siklus hidup yang identik:
dibuat → dikirim → dikerjakan → selesai. Membuat empat model terpisah berarti
empat implementasi pembebanan biaya yang lambat laun berbeda; itu persis cara
tagihan pasien kehilangan satu item.

**Baris order adalah sumber tagihan.** Saat baris berstatus selesai (atau saat
dibuat, untuk kategori seperti administrasi), ``_create_charge()`` dipanggil.
``custom_hms_billing`` mengisinya; tanpa modul itu order tetap berjalan, hanya
tidak menagih.

**Harga dikunci saat pembebanan, bukan saat penagihan.** Baris menyimpan hasil
``resolve_price`` beserta komponen jasa sarana/medis/BHP pada saat layanan
diberikan. Perubahan master tarif bulan depan tidak boleh mengubah tagihan
pasien bulan ini.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_emr"],
    "capability_tags": ["simrs", "cpoe", "orders", "billing-source"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_order_sequence.xml",
        "views/hms_order_views.xml",
        "views/hms_encounter_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
