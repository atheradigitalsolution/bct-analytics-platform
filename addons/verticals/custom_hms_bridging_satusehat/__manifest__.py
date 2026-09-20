# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Bridging SATUSEHAT",
    "summary": "Pemetaan data klinis ke FHIR R4 (Patient, Encounter, Condition, "
               "Observation, MedicationRequest) dan pengirimannya lewat antrian job.",
    "description": """
SIMRS — Bridging SATUSEHAT (custom_hms_bridging_satusehat)
==========================================================

**Pemetaan FHIR hidup di satu tempat.** ``models/fhir_builder.py`` mengubah
record SIMRS menjadi resource FHIR R4. Membangun payload di tempat pemanggilan
berarti dua resource ``Encounter`` yang berbeda bentuk tergantung siapa yang
mengirimnya.

**ID SATUSEHAT disimpan kembali ke record sumber.** ``ihs_patient_id``,
``ihs_encounter_id``, ``ihs_condition_id``: pengiriman berikutnya adalah
``PUT`` ke resource yang sama, bukan ``POST`` yang membuat duplikat di server
Kemenkes — duplikat di sana tidak bisa dibersihkan dari sini.

**Token OAuth2 di-cache sampai hampir kedaluwarsa.** SATUSEHAT membatasi
penerbitan token; meminta token baru untuk setiap resource adalah cara paling
cepat terkena rate limit di tengah demo.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_queue", "custom_hms_emr", "custom_hms_pharmacy"],
    "capability_tags": ["simrs", "satusehat", "fhir", "kemenkes", "bridging"],
    "data": [
        "security/ir.model.access.csv",
        "views/hms_satusehat_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
