# -*- coding: utf-8 -*-
{
    "name": "LGX — Job (Tulang Punggung Komersial)",
    "summary": "lgx.job, lgx.job.charge dengan nilai estimasi dan aktual berdampingan, "
               "milestone, dan laba per job yang memisahkan talangan dari jasa.",
    "description": """
LGX — Job (custom_lgx_job)
==========================

Satu objek komersial dan keuangan untuk KETIGA segmen logistik. Operasi per
segmen — shipment, trip, picking — menggantung di bawahnya, tidak
menggantikannya.

**Setiap baris biaya punya nilai estimasi DAN nilai aktual.** Ini fitur inti,
bukan tambahan. Di forwarding, pendapatan diketahui saat job berjalan tetapi
tagihan vendor baru datang dua sampai enam minggu kemudian. Sistem yang hanya
mencatat biaya saat faktur vendor masuk akan selalu melaporkan laba bulan
berjalan yang terlalu optimistis, lalu mengoreksinya turun belakangan.

**Talangan tidak masuk margin.** ``nature = disbursement`` adalah biaya pihak
ketiga yang ditalangi dan ditagihkan kembali apa adanya — bukan pendapatan dan
bukan beban. Pada job impor, talangan rutin berkali lipat nilai jasanya; kalau
ikut dihitung, ``margin_pct`` menjadi angka yang tidak berarti dan dasar
pemotongan PPh 23 ikut salah.

**Penutupan operasional dan penutupan finansial adalah dua hal berbeda.**
``completed`` berarti pekerjaan fisik selesai; ``closed_provisioned`` berarti
sisa estimasi sudah dibukukan sebagai provisi yang nyata; ``closed`` berarti
seluruh provisi sudah terpakai atau dilepas. Menyatukan ketiganya menghasilkan
aturan yang di lapangan diakali dengan menolkan estimasi — persis kebocoran yang
aturan itu ingin cegah.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_base", "account"],
    "capability_tags": ["logistics", "job-costing", "profitability", "accrual", "indonesia"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_job_rules.xml",
        "data/lgx_job_sequence.xml",
        "views/lgx_job_views.xml",
        "views/lgx_job_charge_views.xml",
        "views/lgx_milestone_views.xml",
        "views/lgx_job_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
