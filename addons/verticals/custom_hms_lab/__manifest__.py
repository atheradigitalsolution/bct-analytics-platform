# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Laboratorium",
    "summary": "Worklist lab, input hasil per parameter dengan nilai rujukan per usia & "
               "jenis kelamin, penandaan nilai kritis, validasi analis dan verifikasi dokter PJ.",
    "description": """
SIMRS — Laboratorium (custom_hms_lab)
=====================================

**Nilai rujukan bergantung pada siapa pasiennya.** Hemoglobin normal seorang
laki-laki dewasa adalah anemia berat pada bayi. Rentang rujukan karena itu
disimpan sebagai baris per (parameter, jenis kelamin, rentang usia), dan
penandaan H/L dihitung terhadap baris yang cocok — bukan terhadap satu rentang
global yang menghasilkan bendera palsu sepanjang hari.

**Nilai kritis bukan sekadar bendera.** Parameter dengan ``critical_low`` /
``critical_high`` yang terlampaui menerbitkan event ``result.critical`` saat
diverifikasi. ``custom_hms_doctor_portal`` mengubahnya menjadi kewajiban
acknowledge dengan batas waktu — indikator mutu sasaran keselamatan pasien.

**Dua mata, dua langkah.** Analis memvalidasi, dokter penanggung jawab
memverifikasi. Hasil baru terlihat di rekam medis setelah verifikasi; hasil
yang belum diverifikasi tidak pernah menjadi dasar terapi.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_order"],
    "capability_tags": ["simrs", "laboratory", "loinc", "critical-value"],
    "data": [
        "security/ir.model.access.csv",
        "security/hms_lab_rules.xml",
        "data/hms_lab_cron.xml",
        "report/hms_lab_reports.xml",
        "views/hms_lab_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
