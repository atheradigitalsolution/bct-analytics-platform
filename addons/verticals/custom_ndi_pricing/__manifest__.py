# -*- coding: utf-8 -*-
{
    "name": "NDI Feed Mill — Harga Bertingkat HJ1-HJ9",
    "summary": "Matriks harga waterfall HJ9->HJ1, penerapan lewat 9 product.pricelist "
               "bertipe fixed, snapshot tingkat harga di baris transaksi, dan batas "
               "Harga 1-3 untuk kasir.",
    "description": """
NDI Feed Mill — Harga Bertingkat HJ1-HJ9
========================================

**Pembentukan harga ada di matriks, penerapan harga tetap milik Odoo.**
``ndi.price.matrix`` menghitung sembilan tingkat dari komponen di master produk
(``custom_ndi_master``) lalu meng-*upsert* sembilan ``product.pricelist.item``
bertipe ``fixed``. Odoo tetap yang memilih harga saat transaksi lewat
pelanggan -> pricelist -> ``price_unit``.

**Rantai ``base_pricelist_id`` sengaja diputus.** Merantai HJ3 ke HJ4, HJ4 ke HJ5
dan seterusnya akan memaksa POS memuat seluruh sembilan tingkat ke sisi klien —
``product.pricelist._load_pos_data_domain`` ikut menarik pricelist yang
direferensi sebagai basis, sehingga ``ir.rule`` pembatas kasir jadi tidak ada
gunanya. Sembilan item ``fixed`` yang berdiri sendiri menutup celah itu sekaligus
menghilangkan penelusuran sembilan tingkat setiap kali satu harga dihitung.

**Snapshot tingkat harga.** ``sale.order.line.pricelist_item_id`` di Odoo 19
adalah compute **tanpa** ``store``: database menyimpan *berapa* harganya tetapi
tidak menyimpan *tingkat mana* yang dipakai. Tanpa ``ndi_hj_level`` yang
disimpan sendiri, dashboard "Omset per Harga 1-9" (pasal 4) dan laporan
"Penjualan berdasarkan Harga 1-9" (pasal 24) tidak bisa dibuat sama sekali.

**Batas kasir.** ``ir.rule`` pada ``product.pricelist``, bukan
``pos.config.available_pricelist_ids``. Batasnya mengikuti orang, bukan terminal,
dan berlaku di POS, backend, dan RPC sekaligus karena
``product.pricelist._load_pos_data_read()`` memanggil ``_filtered_access("read")``.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Industry/Feed Mill",
    "version": "19.0.0.2.0",
    "license": "LGPL-3",
    "depends": ["custom_ndi_master", "custom_pdp_audit", "product", "sale", "point_of_sale"],
    "capability_tags": ["feedmill", "ndi", "pricing", "hj-waterfall"],
    "data": [
        "security/ndi_pricing_groups.xml",
        "security/ir.model.access.csv",
        "data/ndi_pricelist_data.xml",
        "security/ndi_pricing_rules.xml",
        "views/ndi_price_matrix_views.xml",
        "views/product_pricelist_views.xml",
        "views/sale_order_views.xml",
        "views/res_partner_views.xml",
        "views/ndi_pricing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
