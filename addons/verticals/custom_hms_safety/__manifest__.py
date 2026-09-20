# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Keselamatan Pasien & Mutu",
    "summary": "Insiden Keselamatan Pasien (IKP) 2x24 jam dengan ACL tim KP, "
               "grading risiko, akar masalah, dan penanganan komplain pasien.",
    "description": """
SIMRS — Keselamatan Pasien & Mutu (custom_hms_safety)
=====================================================

**Insiden keselamatan pasien tinggal di modul sendiri, bukan menumpang rekam
medis.** PMK 11/2017 menuntut laporan insiden bersifat rahasia dan tidak
menjadi bagian dari berkas rekam medis yang dicetak. Menaruhnya di
``custom_hms_emr`` berarti setiap peran yang boleh membaca rekam medis ikut
membaca laporan insiden — dan begitu itu terjadi, pelaporan berhenti.

**Semua peran klinis boleh melapor, hanya tim KP yang boleh membaca.**
Itulah satu-satunya pembagian yang membuat budaya tanpa-menyalahkan mungkin:
melapor harus semurah mungkin, membaca harus semahal mungkin. Pelapor tetap
bisa membuka laporannya sendiri lewat record rule, karena laporan yang hilang
dari pandangan pelapornya terasa seperti laporan yang tidak pernah sampai.

**Anonimitas pelapor ditawarkan apa adanya, bukan sebagai janji kosong.**
Lihat ``models/hms_incident_report.py`` — batas anonimitas ditulis di sana
sebagai komentar, bukan disembunyikan, karena menjanjikan anonimitas yang
tidak bisa dipenuhi lebih merusak daripada tidak menjanjikannya sama sekali.

**Tenggat datang dari kebijakan RS, bukan dari kode.**
``hms.settings.incident_report_due_hours`` (default 48 = 2x24 jam, PMK 11/2017
Ps. 18) menentukan ``due_at``; target tanggap komplain memakai parameter
sendiri yang ditambahkan modul ini ke ``hms.settings``.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # hms.encounter, hms.patient, hms.unit, hms.practitioner dan hms.settings
    # semuanya sudah tersedia lewat rantai custom_hms_registration ->
    # custom_hms_base. Tidak ada dependensi baru di luar custom_hms_*.
    "depends": ["custom_hms_registration"],
    "capability_tags": ["simrs", "patient-safety", "ikp", "mutu", "starkes"],
    "data": [
        "security/hms_safety_groups.xml",
        "security/ir.model.access.csv",
        "security/hms_safety_rules.xml",
        "data/hms_safety_sequence.xml",
        "views/hms_incident_report_views.xml",
        "views/hms_complaint_views.xml",
        "views/hms_safety_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
