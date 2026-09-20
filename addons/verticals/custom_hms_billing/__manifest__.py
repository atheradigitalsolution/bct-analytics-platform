# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Billing & Kasir",
    "summary": "Tagihan per kunjungan, pemecahan porsi penjamin dan pasien, deposit, "
               "diskon berotorisasi, penutupan ke account.move dan pembayaran.",
    "description": """
SIMRS — Billing & Kasir (custom_hms_billing)
============================================

**Satu kunjungan, satu tagihan.** ``hms.bill`` mengumpulkan semua yang
dikerjakan: order, obat yang diserahkan, dan charge harian rawat inap. Tidak
ada tagihan kedua yang bisa muncul diam-diam untuk kunjungan yang sama.

**Pemecahan penjamin dihitung per baris, bukan per total.** Sebuah plan bisa
menanggung 100% tindakan tetapi mengecualikan kategori tertentu, dan pasien
yang naik kelas membayar selisih tarif kamar saja. Menghitung di tingkat total
membuat kedua aturan itu mustahil dinyatakan.

**Penutupan tagihan menghasilkan ``account.move`` yang seimbang**, satu per
lawan transaksi: satu invoice ke penjamin dan satu ke pasien bila tagihannya
terpecah. Pembayaran menjadi ``account.payment`` pada jurnal sesuai metode.
Akuntansi rumah sakit dengan begitu adalah akuntansi Odoo — bukan tabel
paralel yang harus direkonsiliasi tiap bulan.

**Harga dibekukan saat pembebanan.** Baris tagihan menyimpan angka yang berlaku
saat layanan diberikan, beserta komponen jasa sarana/jasa medis/BHP. Revisi
master tarif tidak pernah mengubah tagihan yang sudah berjalan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_order", "custom_hms_inpatient", "custom_hms_pharmacy", "account"],
    "capability_tags": ["simrs", "billing", "cashier", "account-move", "payer-split"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_billing_sequence.xml",
        "report/hms_billing_reports.xml",
        # The wizard action is referenced by a button on the bill form, so it
        # must exist before that view is parsed.
        "views/hms_payment_wizard_views.xml",
        "views/hms_discount_wizard_views.xml",
        "views/hms_bill_views.xml",
        "views/hms_deposit_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
