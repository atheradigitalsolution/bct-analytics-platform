# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Jadwal Praktik & Tim Perawatan",
    "summary": "Template jadwal dokter, generate slot harian, cuti lewat hr_holidays, "
               "jadwal visite, tim perawatan (DPJP/konsulen), konsul antar dokter.",
    "description": """
SIMRS — Jadwal Praktik & Tim Perawatan (custom_hms_scheduling)
==============================================================

**Cuti dokter tidak boleh menjadi kejutan bagi pasien.** Persetujuan cuti di
``hr_holidays`` otomatis membuat ``hms.schedule.exception`` dan memblokir slot
yang terkena. Slot yang sudah terisi tidak hilang diam-diam — ia muncul sebagai
daftar kerja: alihkan ke dokter lain, geser, atau batalkan dengan notifikasi.

**Siapa merawat siapa itu data, bukan asumsi.** ``hms.care.team`` mencatat
DPJP, dokter rawat bersama, konsulen, residen dan perawat primer per kunjungan
beserta periodenya. Aturan akses rekam medis dan audit "di luar tim perawatan"
membaca tabel ini, jadi ketepatannya punya konsekuensi nyata.

**Konsul adalah permintaan yang dijawab, bukan pesan.** ``hms.consult.request``
punya pertanyaan klinis, status, dan jawaban yang mendarat di CPPT sebagai
catatan bertanda tangan — sekaligus memicu tarif konsul.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_base", "custom_hms_emr", "custom_hms_order", "hr_holidays"],
    "capability_tags": ["simrs", "scheduling", "care-team", "consult", "leave"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_scheduling_cron.xml",
        "views/hms_schedule_views.xml",
        "views/hms_care_team_views.xml",
        "views/hms_procedure_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
