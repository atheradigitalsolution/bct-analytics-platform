# -*- coding: utf-8 -*-
{
    "name": "LGX — Penagihan, Akrual, dan Provisi",
    "summary": "Job menjadi faktur pelanggan dan tagihan vendor; talangan lewat akun kliring "
               "di neraca; estimasi membentuk akrual; penutupan finansial lewat provisi.",
    "description": """
LGX — Billing (custom_lgx_billing)
==================================

Tiga hal yang rusak sekaligus tanpa peta akun yang eksplisit: margin per job,
dasar pemotongan PPh 23, dan laporan laba rugi. Modul ini adalah peta akun itu.

**Talangan mengalir lewat neraca, bukan lewat laba rugi.** Bea masuk, THC dan
retribusi yang ditalangi lalu ditagihkan kembali apa adanya bukan pendapatan dan
bukan beban. Pada job impor, talangan rutin berkali lipat nilai jasanya — kalau
keduanya dilewatkan akun laba rugi, pendapatan dan HPP sama-sama menggelembung
dan ``margin_pct`` menjadi angka yang tidak berarti.

    Membayar bea masuk atas nama klien  Dr Kliring talangan  Cr Kas/Bank
    Menagihkan kembali ke klien          Dr Piutang usaha     Cr Kliring talangan
    Dampak ke laba rugi                  NOL

**Akrual dibalik oleh tagihannya, bukan oleh pembalikan otomatis awal periode.**
Pembalikan otomatis akan membuat biaya menghilang selama beberapa minggu sampai
tagihan vendor datang — persis masalah yang akrual ini ada untuk menutupinya.

**Provisi, bukan penghapusan.** Saat job ditutup secara finansial, sisa estimasi
dipindahkan dari akun akrual ke akun provisi job tertutup dengan umur tercatat.
Tagihan yang datang kemudian membebani provisi, bukan membuka kembali laba rugi
periode yang sudah dilaporkan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "account"],
    "capability_tags": ["logistics", "billing", "accrual", "provision", "disbursement", "indonesia"],
    "data": [
        "security/ir.model.access.csv",
        "data/lgx_billing_data.xml",
        "views/res_config_settings_views.xml",
        "views/lgx_job_billing_views.xml",
        "views/account_move_views.xml",
        "wizard/lgx_job_invoice_wizard_views.xml",
        "views/lgx_billing_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
