# -*- coding: utf-8 -*-
{
    "name": "SIMRS — P&L per Unit Layanan",
    "summary": "Analytic account per poli/unit, akrual jasa medis dokter, alokasi overhead "
               "berbasis driver, laporan laba-rugi per unit.",
    "description": """
SIMRS — P&L per Unit Layanan (custom_hms_unit_pnl)
==================================================

**Pendapatan dikreditkan ke unit yang mengerjakan.** Pemeriksaan lab yang
dipesan poli anak adalah pendapatan laboratorium. Mengkreditkannya ke poli
pemesan membuat laboratorium tampak merugi selamanya dan poli tampak jauh
lebih untung daripada kenyataannya.

**Jasa medis diakui saat tagihan ditutup, bukan saat dibayar dokter.**
``hms.medical.fee`` mencatat komponen ``amount_medical`` per baris tagihan;
pembayarannya kemudian dikumpulkan per periode. Tanpa akrual ini, laba unit
bulan berjalan selalu terlalu besar.

**Alokasi overhead memakai driver, dan dapat dijalankan ulang.** Listrik per
luas lantai, manajemen per jumlah kunjungan, laundry per hari rawat. Hasilnya
ditulis sebagai ``account.analytic.line`` saja — tidak memindahkan saldo buku
besar, sehingga menjalankan ulang alokasi tidak pernah merusak GL.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_billing", "account", "analytic"],
    "capability_tags": ["simrs", "pnl", "analytic", "medical-fee", "cost-allocation"],
    "data": [
        "security/ir.model.access.csv",
        "views/hms_unit_pnl_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
