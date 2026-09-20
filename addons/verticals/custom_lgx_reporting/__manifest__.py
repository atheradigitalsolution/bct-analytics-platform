# -*- coding: utf-8 -*-
{
    "name": "LGX — Laporan & Analitik",
    "summary": "Laba per segmen, waktu siklus per tahap, akurasi provisi, dan utilisasi armada — "
               "dari view SQL, bukan dari hitungan ulang di spreadsheet.",
    "description": """
LGX — Laporan (custom_lgx_reporting)
====================================

**Angka yang dibawa ke rapat harus datang dari satu tempat.** Laporan di sini
adalah view SQL di atas data transaksi, bukan model yang diisi proses terpisah:
laporan yang punya salinan datanya sendiri adalah laporan yang suatu saat
berbeda dari sumbernya, dan pada saat itu tidak ada cara memutuskan mana yang
benar.

**Porsi biaya estimasi yang belum menjadi aktual ditampilkan berdampingan dengan
margin.** Itu ukuran seberapa dipercaya angka margin bulan berjalan, dan
menampilkan margin tanpa angka itu adalah menampilkan setengah kalimat.

**Waktu siklus disajikan sebagai median dan persentil 90, bukan rata-rata.**
Rata-rata waktu bongkar pelabuhan tidak berarti apa-apa ketika distribusinya
berekor panjang — dan di pelabuhan ia selalu berekor panjang.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_billing", "custom_lgx_ff", "custom_lgx_tms"],
    "capability_tags": ["logistics", "reporting", "profitability", "cycle-time", "analytics"],
    "data": [
        "security/ir.model.access.csv",
        "views/lgx_report_views.xml",
        "views/lgx_report_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
