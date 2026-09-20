# -*- coding: utf-8 -*-
{
    "name": "LGX — Trucking & Dispatch",
    "summary": "Trip multi-stop, dispatch dengan deteksi bentrok, validasi ODOL, POD digital, "
               "uang jalan dengan batas dari master rute, dan pertanggungjawaban berbukti.",
    "description": """
LGX — Trucking (custom_lgx_tms)
===============================

**`lgx.trip` adalah model sendiri dan TIDAK bergantung pada `stock_fleet`.**
`stock_fleet` mengaitkan dispatch ke `stock.picking.batch`, yang mengandaikan ada
pergerakan stok di pembukuan sendiri. Untuk perusahaan trucking murni yang
mengangkut barang milik orang lain, tidak ada stok yang bergerak — memaksakan
`stock.picking` akan menciptakan pergerakan stok palsu, dan memaksa klien
trucking memasang seluruh modul Inventory hanya untuk mengelola trip.

**POD adalah pemicu tagihan, jadi ia menahan status.** Di trucking, bukti terima
bertanda tangan adalah satu-satunya dasar penagihan; POD hilang berarti
pendapatan hilang. Trip karena itu tidak dapat masuk `delivered` selama ada stop
`dropoff` tanpa POD.

**Uang jalan adalah titik kebocoran terbesar, dan tiga kontrolnya struktural:**
batasnya dihitung dari master rute dan bukan diketik bebas; satu pengemudi tidak
boleh punya lebih dari satu uang jalan terbuka; trip tidak dapat ditutup sebelum
pertanggungjawaban selesai. Selisihnya otomatis menjadi piutang atau utang
pengemudi — bukan dibulatkan hilang.

**`lgx.driver` hidup di modul ini, bukan di `custom_lgx_driver`.** Penyimpangan
sadar dari spesifikasi: dispatch harus dapat menolak pengemudi ber-SIM mati pada
saat penugasan, dan itu berarti master pengemudi harus ada sebelum modul
pengemudi dipasang. `custom_lgx_driver` memperluasnya dengan hr.employee, log jam
kerja, dan backend aplikasi lapangan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_job", "custom_lgx_fleet"],
    "capability_tags": ["logistics", "trucking", "dispatch", "pod", "odol", "driver-advance"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_tms_rules.xml",
        "data/lgx_tms_sequence.xml",
        "views/lgx_driver_views.xml",
        "views/lgx_route_views.xml",
        "views/lgx_trip_views.xml",
        "views/lgx_advance_views.xml",
        "views/lgx_tms_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
