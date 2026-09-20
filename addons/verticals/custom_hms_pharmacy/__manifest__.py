# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Farmasi & E-Resep",
    "summary": "E-resep, racikan, skrining alergi, antrian apotek, dispensing FEFO yang "
               "memotong stok Odoo, etiket obat.",
    "description": """
SIMRS — Farmasi & E-Resep (custom_hms_pharmacy)
===============================================

**Stok obat adalah stok Odoo, bukan tabel kedua.** Penyerahan obat membuat
``stock.picking`` keluar dari lokasi depo. Tidak ada kolom "sisa stok" milik
SIMRS yang bisa berbeda dari ``stock.quant`` — perbedaan seperti itu selalu
ketahuan saat stok opname, setelah obatnya telanjur habis.

**FEFO, bukan FIFO.** Lot dipilih berdasarkan tanggal kedaluwarsa terdekat.
Obat bukan komoditas: yang masuk lebih dulu belum tentu kedaluwarsa lebih dulu,
dan yang penting adalah yang kedaluwarsa lebih dulu.

**Skrining alergi memperingatkan, tidak memblokir.** Apoteker yang tahu pasien
pernah toleran terhadap suatu obat harus bisa melanjutkan dengan alasan
tercatat. Sistem yang memblokir keras akan dilewati dengan cara yang tidak
tercatat sama sekali.

**Obat high-alert wajib double-check.** Penyerahan tanpa apoteker kedua
ditolak — ini satu dari sedikit hal yang memang harus keras.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # product_expiry is what puts `expiration_date` on stock.lot. Without it the
    # FEFO selection below silently degrades to "any lot", which is exactly the
    # failure a pharmacy cannot see until expired stock reaches a patient.
    "depends": ["custom_hms_order", "stock", "product", "product_expiry"],
    "capability_tags": ["simrs", "pharmacy", "e-prescription", "fefo", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_pharmacy_sequence.xml",
        "report/hms_pharmacy_reports.xml",
        "report/hms_medicine_label_template.xml",
        "views/hms_medicine_views.xml",
        "views/hms_depot_views.xml",
        "views/hms_prescription_views.xml",
        "views/hms_prescription_review_views.xml",
        "views/hms_medication_reconciliation_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
