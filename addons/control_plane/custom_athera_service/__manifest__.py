# -*- coding: utf-8 -*-
{
    "name": "ATHERA Service Contracts",
    "summary": "Jam kontrak untuk pengembangan kustom, pemeliharaan, dan training",
    "description": """
ATHERA Service Contracts
========================

Tiga layanan dijual di ``/produk`` — pengembangan modul kustom, pemeliharaan,
dan training — dan sampai modul ini ada, ketiganya **nol model**: tidak ada
tempat mencatat berapa jam dibeli, berapa terpakai, dan kapan habis.

APA YANG MODUL INI *TIDAK* BANGUN, DAN KENAPA
---------------------------------------------
Lapisan ini sengaja setipis mungkin. Odoo 19 dan modul ee_gap yang sudah
terpasang sudah menyediakan hampir semuanya:

- **Permintaan pengembangan** = ``project.task``. Native, sudah punya tahapan,
  penugasan, dan timesheet.
- **Tiket pemeliharaan** = ``helpdesk.ticket`` (``custom_helpdesk``). Sudah ada.
- **SLA** = ``helpdesk.sla`` (``custom_helpdesk``). Sudah ada, lengkap dengan
  ``time_response_hours`` dan ``time_resolve_hours``. Membangun SLA kedua di
  sini berarti dua definisi yang akhirnya berselisih.
- **Pencatatan jam** = ``account.analytic.line`` lewat ``hr_timesheet``. Native.

Yang benar-benar hilang hanyalah **objek komersialnya**: berapa jam yang
dibeli klien, terhadap kontrak mana pekerjaan itu dibebankan, dan berapa sisa.
Itu saja yang ditambahkan di sini, plus dua tautan (``project.task`` dan
``helpdesk.ticket`` → kontrak) supaya jam yang sudah dicatat native bisa
dijumlahkan terhadap saldo.

KENAPA JAM TIKET DICATAT MANUAL
-------------------------------
``helpdesk.ticket`` di ``custom_helpdesk`` tidak punya kaitan ke project atau
ke analytic line, jadi tidak ada timesheet yang bisa dijumlahkan darinya.
Menambahkan timesheet penuh ke helpdesk adalah modul tersendiri dan bukan
"lapisan tipis". Sampai itu ada, tiket membawa ``athera_hours_spent`` yang
diisi tangan — angka yang jujur tentang asal-usulnya, bukan nol yang menyamar
sebagai "belum ada pekerjaan".

KENAPA SALDO TIDAK MEMBLOKIR APA PUN
------------------------------------
Kontrak yang habis berpindah ke state ``exhausted`` dan berhenti di situ. Ia
tidak menolak task baru, tidak mengunci tiket, dan tidak membatalkan apa pun.
Alasannya: pekerjaan yang sudah terlanjur dikerjakan tetap harus bisa dicatat,
dan sistem yang menolak pencatatan mendorong jam itu keluar dari buku — persis
kegagalan yang tombol "perpanjang akses" di ``custom_super_admin`` dibangun
untuk mencegah. Saldo minus terlihat, dan itu memang tujuannya.
""",
    "author": "ATHERA Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Custom Platform/Operations",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "custom_super_admin",      # tenant.registry
        "custom_athera_billing",   # athera.subscription
        "custom_helpdesk",         # helpdesk.ticket, helpdesk.sla
        "project",                 # project.task
        "hr_timesheet",            # project.task.effective_hours
    ],
    "capability_tags": ["multi-tenant", "audit-trail"],
    "data": [
        "security/ir.model.access.csv",
        "views/athera_service_contract_views.xml",
        "views/project_task_views.xml",
        "views/helpdesk_ticket_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
