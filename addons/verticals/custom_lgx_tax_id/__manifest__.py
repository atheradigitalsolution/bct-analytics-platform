# -*- coding: utf-8 -*-
{
    "name": "LGX — Pajak Indonesia untuk Logistik",
    "summary": "PPN besaran tertentu JPT, dasar PPh 23 yang mengecualikan reimbursement, "
               "keputusan PPh 23 versus PPh 15, ekspor jasa 0% dengan validasi keras, "
               "dan NITKU cabang pada faktur.",
    "description": """
LGX — Pajak Indonesia (custom_lgx_tax_id)
=========================================

**Modul ini MEMPERLUAS, tidak menduplikasi.** Repo sudah memuat
``custom_coretax`` (NSFP, e-Faktur XML, Bukti Potong), ``custom_coretax_bupot``
(Bupot PPh Unifikasi termasuk Pasal 15 dan 23) dan ``custom_pph_witholding``
(registry tarif dan mesin perhitungan). Yang belum ada di sana, dan hanya ada di
sini, adalah pengetahuan yang khusus logistik.

**NSFP DISIMPAN dari respons DJP, tidak pernah dihasilkan sendiri.** Sejak
Coretax, nomor seri faktur pajak 17 digit diberikan server saat faktur di-upload
dan disetujui (PER-11/PJ/2025 Pasal 37). Tidak ada lagi permintaan jatah nomor
seri, dan logika "range NSFP" lama harus dibuang. Modul ini karena itu tidak
memuat satu pun ``ir.sequence`` untuk nomor pajak — dan itu dapat diperiksa
dengan grep.

**Dasar PPh 23 mengecualikan reimbursement.** PMK 141/2015: jumlah bruto tidak
termasuk reimbursement yang dapat dibuktikan dengan faktur tagihan dan/atau
bukti pembayaran dari pihak ketiga. Yang menghubungkannya ke model data adalah
``lgx.job.charge.nature``.

**Arah pemotongan menentukan NPWP siapa yang diuji.** Kenaikan 100% menjadi 4%
selalu bergantung pada NPWP PENERIMA PENGHASILAN — vendor pada bukti potong
keluaran, perusahaan sendiri pada potongan yang diterima dari pelanggan. Menguji
``partner_id.vat`` pada faktur penjualan adalah kesalahan arah, dan hasilnya
salah setiap kali pelanggan tidak ber-NPWP sementara perusahaan ber-NPWP.

**Dua hal sengaja TIDAK otomatis penuh** (§11.1 langkah 3 dan 5): tagihan tanpa
freight charge, dan angkutan umum yang dibebaskan. Keduanya berada di wilayah
yang belum pasti secara regulasi, dan keputusan diam-diam di sana menciptakan
risiko sengketa yang baru ketahuan saat pemeriksaan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_billing", "custom_coretax"],
    "capability_tags": [
        "logistics", "indonesian-tax", "ppn", "pph23", "pph15", "coretax", "nitku",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_tax_data.xml",
        "views/account_move_tax_views.xml",
        "views/lgx_tax_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
