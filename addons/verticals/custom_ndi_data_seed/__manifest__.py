# -*- coding: utf-8 -*-
{
    "name": "NDI Feed Mill — Sample Data (FIXTURE)",
    "summary": "Master, BOM, dan 12 bulan transaksi PT Nutrisi Daya Indonesia: "
               "pembelian -> produksi -> penjualan yang benar-benar mengalir.",
    "description": """
NDI Feed Mill — Sample Data
===========================

**MODUL FIXTURE. JANGAN masukkan ke set instalasi produksi klien.**

Ia ada karena alur NDI POS + PRODUKSI tidak bisa diperagakan, apalagi di-UAT, di
atas database yang produknya nol. Yang dihasilkannya bukan tabel berisi angka:
bahan benar-benar dibeli dan diterima, benar-benar dikonsumsi perintah produksi,
produk jadi benar-benar masuk gudang, dipindahkan ke outlet, lalu dijual kredit
lewat Sales Order dan tunai lewat POS.

Pengaman, urut menurut seberapa besar ia benar-benar melindungi:

1. **Tidak menghasilkan apa pun saat install.** Data muncul hanya ketika
   ``ndi.data.seed.generate()`` dipanggil eksplisit.
2. Bukan ``auto_install`` dan tidak ada modul yang bergantung padanya.
3. ``generate()`` menolak dijalankan bukan administrator.
4. Idempoten lewat external ID ``ir.model.data``, sehingga jalan kedua tidak
   membuat baris baru — dan generator bisa **dilanjutkan** setelah gagal di
   tengah jalan.
5. **Otoritas parameter.** Bentuk penuh sebuah dataset dicatat saat pertama
   dibuat; panggilan berikutnya dengan bentuk berbeda menolak dan menyebut setiap
   parameter yang bentrok. Tanpa ini, idempotensi lewat external ID diam-diam
   mengembalikan bentuk yang tidak diminta pemanggil.
6. Seluruh nama pelanggan, pemasok, dan perusahaan fiktif; e-mail memakai domain
   ``.invalid`` (RFC 2606) dan telepon memakai ``+62-800-555-``. ``vat`` sengaja
   dikosongkan: nilai yang lolos validasi NPWP menurut definisi adalah NPWP yang
   checksum-nya sah.

Urutan yang load-bearing
------------------------
Beli dulu, produksi kemudian, jual terakhir — di dalam setiap bulan. Odoo tidak
menolak konsumsi melebihi stok; ia membuat kuant negatif dan diam. Setiap MO
diperiksa ``reservation_state == 'assigned'`` sebelum diselesaikan, dan setiap
baris penjualan dipotong terhadap ``free_qty`` di lokasi asalnya.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Industry/Feed Mill",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": [
        "custom_ndi_master",
        "custom_ndi_pricing",
        "custom_operating_unit",
        "custom_pdp_core",
        "mrp",
        "purchase_stock",
        "sale_management",
        "sale_stock",
        "point_of_sale",
        "account",
        "stock",
        "product",
    ],
    "capability_tags": ["feedmill", "ndi", "fixture", "sample-data"],
    "data": [
        "security/ir.model.access.csv",
        "views/ndi_data_seed_views.xml",
    ],
    "installable": True,
    "application": False,
    # Eksplisit False. Modul fixture tidak boleh pernah tertarik oleh dependency.
    "auto_install": False,
}
