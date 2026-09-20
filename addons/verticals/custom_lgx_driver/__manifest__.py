# -*- coding: utf-8 -*-
{
    "name": "LGX — Pengemudi & Kepatuhan Jam Kerja",
    "summary": "Tautan pengemudi ke hr.employee, log jam kerja yang dihitung dari waktu aktual trip, "
               "dan penandaan pelanggaran jam mengemudi dengan jejak audit.",
    "description": """
LGX — Pengemudi (custom_lgx_driver)
===================================

**Jejak audit kepatuhan adalah kepentingan PERUSAHAAN, bukan pengemudi.**
UU 22/2009 Pasal 92 memberi sanksi administratif kepada perusahaan — mulai
peringatan tertulis sampai pencabutan izin — bukan hanya kepada pengemudi.
Karena itu jam mengemudi dihitung dari waktu aktual trip dan pelanggarannya
ditandai, bukan dibiarkan menjadi pengetahuan lisan.

⚠ Keempat ambang (4 jam mengemudi berturut-turut, istirahat 30 menit, 8 jam
kerja sehari, 12 jam batas mutlak) baru bersumber SEKUNDER. Pasal 90 dan 92
UU 22/2009 harus dibaca langsung dari JDIH sebelum angkanya dikunci — butir A12c
di Lampiran A. Karena itu keempatnya adalah parameter sistem, bukan konstanta.

Perpanjangan sampai 12 jam menuntut alasan DAN penyetuju tercatat. Perpanjangan
yang bisa dilakukan tanpa jejak adalah perpanjangan yang akan menjadi kebiasaan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Logistics/LGX",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_lgx_tms", "hr"],
    "capability_tags": ["logistics", "driver", "compliance", "working-hours", "indonesia"],
    "data": [
        "security/ir.model.access.csv",
        "security/lgx_driver_rules.xml",
        "data/lgx_driver_data.xml",
        "views/lgx_duty_log_views.xml",
        "views/lgx_driver_views_inherit.xml",
        "views/lgx_driver_menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
