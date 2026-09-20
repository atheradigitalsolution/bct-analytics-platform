# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Radiologi",
    "summary": "Worklist radiologi, pencatatan pelaksanaan, ekspertise radiolog dengan "
               "lampiran citra, penandaan temuan kritis.",
    "description": """
SIMRS — Radiologi (custom_hms_radiology)
========================================

Alurnya lebih pendek daripada laboratorium karena hasilnya naratif, bukan
angka: pemeriksaan dikerjakan radiografer, lalu radiolog menulis ekspertise dan
memverifikasi. Sampai diverifikasi, yang terlihat di rekam medis hanyalah
"sudah dikerjakan" — bukan kesimpulan yang belum dibaca dokter ahli.

Modul ini sengaja tidak menyentuh PACS/DICOM. Citra dilampirkan sebagai berkas
biasa; integrasi modality worklist adalah pekerjaan fase berikutnya dan
memerlukan perangkat yang tidak ada di lingkungan demo.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_order"],
    "capability_tags": ["simrs", "radiology", "imaging"],
    "data": [
        "security/ir.model.access.csv",
        "security/hms_radiology_rules.xml",
        "data/hms_radiology_cron.xml",
        "report/hms_radiology_reports.xml",
        "views/hms_radiology_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
