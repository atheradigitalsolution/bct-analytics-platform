# -*- coding: utf-8 -*-
{
    "name": "NDI Feed Mill — Master Data",
    "summary": "Master produk pabrik pakan: jenis produk, divisi/kategori, komponen "
               "pembentuk harga HJ1-HJ9, UoM bertingkat dan berat gross per tingkat.",
    "description": """
NDI Feed Mill — Master Data
===========================

Lapisan master untuk PT Nutrisi Daya Indonesia (pabrik pakan ternak), pasal 5,
13, 17 dan 18 requirement.

**Komponen pembentuk harga (pasal 13).** ``product.template`` menyimpan sembilan
komponen (HPP dasar, profit %, risiko %, pajak %, ongkir, pembulatan, insentif
kwartal, insentif bulanan, margin HET) dan sembilan hasil ``ndi_hj1``..``ndi_hj9``
sebagai compute **stored**. Rumus waterfall tinggal di satu tempat —
``models/ndi_waterfall.py`` — dan dipakai ulang oleh ``custom_ndi_pricing``.
Tidak ada dua implementasi rumus yang bisa berbeda diam-diam.

**UoM bertingkat (pasal 5, D2).** Odoo 19 menghapus ``uom.category`` dan
``product.packaging``; ``uom.uom`` kini pohon rekursif lewat ``relative_uom_id``
/ ``relative_factor``. Modul ini menyemai pohon feed mill KG -> SAK -> TON di
atas ``uom.product_uom_kgm`` bawaan, plus akar hitung sendiri untuk PCS, BTL,
JRG, SCH, CONE dan SAK sekam. Karena ``uom.uom`` global, satu label "SAK" tidak
cukup: SAK 50 KG, SAK 30 KG dan SAK 25 KG adalah record berbeda.

**Dimensi pelanggan yang bisa direplikasi (addendum K-2/K-3).**
``res.partner.ndi_customer_type`` dan ``res.partner.ndi_sales_region`` adalah
Selection skalar, bukan ``res.partner.category`` dan bukan ``city``. Tabel relasi
tag tidak punya kolom ``id`` sehingga tidak bisa masuk publication CDC, dan ``city``
diklasifikasi ``personal`` sehingga di-hash saat load. Dua sumbu laporan pasal 24
karena itu harus punya kolomnya sendiri.

**Berat gross per tingkat (pasal 17/18).** ``product.template.weight`` hanya satu
Float pada base unit. ``ndi.product.uom.weight`` menyimpan berat gross per
(produk, UoM) sehingga "BERAT T. BARANG" bisa dihitung pada satuan yang benar-benar
ditransaksikan.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Industry/Feed Mill",
    "version": "19.0.0.2.0",
    "license": "LGPL-3",
    "depends": ["custom_core", "custom_pdp_audit", "product", "uom", "stock", "sale", "purchase"],
    "capability_tags": ["feedmill", "ndi", "master-data", "multi-uom"],
    "data": [
        "security/ndi_master_groups.xml",
        "security/ir.model.access.csv",
        "data/ndi_uom_data.xml",
        "views/ndi_master_views.xml",
        "views/product_template_views.xml",
        "views/res_partner_views.xml",
        "views/ndi_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
