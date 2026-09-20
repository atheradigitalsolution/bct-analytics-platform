# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Dashboard & Shift Kasir",
    "summary": "Shift kasir dengan modal awal dan closing per metode, antrian kasir, "
               "estimasi biaya rawat inap, piutang pasien.",
    "description": """
SIMRS — Dashboard & Shift Kasir (custom_hms_cashier)
====================================================

**Tidak ada uang masuk tanpa shift terbuka.** Setiap pembayaran menempel pada
``hms.cashier.session``. Tanpa itu, selisih kas di akhir hari tidak dapat
ditelusuri ke siapa pun — dan selisih kas yang tidak dapat ditelusuri adalah
temuan audit, bukan sekadar ketidaknyamanan.

**Closing membandingkan hitungan fisik dengan yang seharusnya, per metode.**
Tunai dihitung tangan; EDC, transfer dan QRIS dicocokkan dengan struk. Satu
angka gabungan menyembunyikan kesalahan yang saling menutup.

**Estimasi biaya rawat inap dihitung dari tarif yang berlaku**, bukan dari
angka yang diingat petugas. Keluarga pasien berhak tahu perkiraan sebelum
menyetujui kelas perawatan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_billing", "custom_hms_qms", "account"],
    "capability_tags": ["simrs", "cashier", "shift", "closing", "receivable"],
    "data": [
        "security/ir.model.access.csv",
        "report/hms_cashier_reports.xml",
        "views/hms_cashier_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
