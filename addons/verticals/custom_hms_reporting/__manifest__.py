# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Laporan & Analitik",
    "summary": "View SQL untuk kunjungan, pendapatan, sensus rawat inap dan RL 4a morbiditas, "
               "siap dipakai pivot dan grafik Odoo.",
    "description": """
SIMRS — Laporan & Analitik (custom_hms_reporting)
=================================================

Laporan dibangun sebagai **SQL view**, bukan sebagai model yang menyalin data.
Salinan berarti dua kebenaran yang bisa berbeda, dan yang salah selalu ketahuan
saat dilaporkan ke dinas kesehatan.

- ``hms.report.visit`` — kunjungan per unit, dokter, penjamin, jenis kunjungan.
- ``hms.report.revenue`` — pendapatan per unit dan kategori tarif, dengan
  komponen jasa medis terpisah.
- ``hms.report.census`` — sensus harian rawat inap: pasien masuk, keluar, dan
  hari rawat.
- ``hms.report.rl4`` — morbiditas rawat inap menurut diagnosis utama, kelompok
  umur dan jenis kelamin, bentuk yang dipakai RL 4a.

Semuanya memakai pivot dan graph bawaan Odoo, jadi manajemen dapat mengiris
sendiri tanpa meminta laporan baru dibuatkan.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_billing", "custom_hms_inpatient", "custom_hms_emr"],
    "capability_tags": ["simrs", "reporting", "rl4", "census", "pivot"],
    "data": [
        "security/ir.model.access.csv",
        "views/hms_reporting_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
