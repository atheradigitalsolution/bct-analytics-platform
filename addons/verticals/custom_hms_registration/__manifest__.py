# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Pendaftaran & Kunjungan",
    "summary": "Registrasi rawat jalan dan IGD, encounter, triase, rujukan, cetak kartu & gelang.",
    "description": """
SIMRS — Pendaftaran & Kunjungan (custom_hms_registration)
=========================================================

``hms.encounter`` adalah sumbu seluruh sistem: setiap catatan klinis, order,
resep, tagihan dan tiket antrian menggantung padanya. Satu kunjungan = satu
encounter, dari kedatangan sampai tagihan ditutup.

**Registrasi adalah satu transaksi.** Mencari/membuat pasien, membuat
encounter, menerbitkan nomor kunjungan, dan menjadwalkan job SEP terjadi dalam
satu commit. Kalau salah satu gagal, tidak ada pasien setengah terdaftar yang
harus dibereskan petugas secara manual.

**IGD mendahului identitas.** Pasien gawat darurat didaftarkan dengan nama
sementara dan triase, tanpa NIK. Kewajiban melengkapi identitas dicatat sebagai
utang data pada encounter, bukan sebagai penghalang di depan pintu.

**Tiket antrian tidak dibuat di sini.** Modul ini memanggil hook
``_hms_issue_ticket``; ``custom_hms_qms`` yang mengisinya. Dengan begitu
pendaftaran tetap berfungsi di instalasi tanpa QMS, dan aturan antrian tidak
tersebar di dua modul.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_base", "custom_hms_audit", "custom_hms_queue"],
    "capability_tags": ["simrs", "registration", "encounter", "triage", "emergency"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_registration_sequence.xml",
        "report/hms_registration_reports.xml",
        "report/hms_patient_card_template.xml",
        "report/hms_wristband_template.xml",
        "views/hms_encounter_views.xml",
        "views/hms_registration_wizard_views.xml",
        "views/hms_access_log_ext_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
