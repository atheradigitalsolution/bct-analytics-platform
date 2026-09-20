# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Rekam Medis Elektronik",
    "summary": "Asesmen, CPPT/SOAP append-only dengan tanda tangan elektronik, diagnosis ICD-10, "
               "prosedur ICD-9-CM, persetujuan, resume medis.",
    "description": """
SIMRS — Rekam Medis Elektronik (custom_hms_emr)
===============================================

**Catatan yang sudah ditandatangani tidak pernah diubah.** ``write`` pada
``hms.clinical.note`` bertanda tangan ditolak di level ORM, bukan disembunyikan
di UI. Koreksi membuat versi baru yang menunjuk versi lama lewat ``revises_id``;
versi lama tetap ada dan tetap terbaca. Ini syarat hukum rekam medis, dan
satu-satunya cara membuktikannya adalah membuat jalur ubah benar-benar buntu.

**Tanda tangan elektronik adalah hash, bukan gambar.** ``signature_hash``
adalah SHA-256 atas isi catatan + penulis + waktu. Mengubah satu huruf membuat
hash tidak cocok, dan ketidakcocokan itu bisa ditunjukkan tanpa mempercayai log
aplikasi.

**Observasi TTV disimpan terstruktur, bukan sebagai teks.** Skor EWS di
``custom_hms_nursing`` dan pemetaan FHIR ``Observation`` keduanya membaca kolom
yang sama; TTV berupa narasi berarti dua fitur itu mustahil.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_registration"],
    "capability_tags": ["simrs", "emr", "cppt", "soap", "icd10", "e-signature"],
    "data": [
        "security/ir.model.access.csv",
        "security/hms_emr_rules.xml",
        "data/hms_emr_sequence.xml",
        "data/hms_emr_cron.xml",
        "report/hms_emr_reports.xml",
        "report/hms_summary_template.xml",
        "views/hms_observation_views.xml",
        "views/hms_clinical_note_views.xml",
        "views/hms_diagnosis_views.xml",
        "views/hms_consent_views.xml",
        "views/hms_encounter_emr_views.xml",
        "views/hms_verbal_order_views.xml",
        "views/hms_delegation_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
