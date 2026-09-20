# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Bridging BPJS",
    "summary": "Klien VClaim dan Antrean BPJS: cek peserta, SEP, rujukan, antrean — "
               "seluruhnya lewat antrian job, tidak pernah sinkron dari layar petugas.",
    "description": """
SIMRS — Bridging BPJS (custom_hms_bridging_bpjs)
================================================

**Tidak ada panggilan BPJS yang sinkron.** Setiap permintaan menjadi
``hms.job``. Waktu respons BPJS di luar kendali rumah sakit; loket pendaftaran
yang menunggu panggilan HTTP berarti antrian berhenti karena masalah pihak lain.

**Signature dan dekripsi ditulis sendiri.** VClaim memakai HMAC-SHA256 atas
``consId&timestamp`` dan membalas payload terenkripsi AES-256-CBC yang
dikompresi LZ-String. Keduanya diimplementasikan di ``models/vclaim_crypto.py``
memakai ``hashlib``/``hmac``/``base64`` bawaan Python — tanpa dependensi baru,
sesuai standar Athera.

**Mode mock adalah default.** ``BPJS_MODE=mock`` mengarahkan klien ke server
tiruan sehingga alur demo — termasuk kegagalan dan retry — dapat ditunjukkan
tanpa kredensial produksi. Beralih ke sandbox/produksi hanya mengganti variabel
lingkungan; kodenya sama.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_queue", "custom_hms_registration"],
    "capability_tags": ["simrs", "bpjs", "vclaim", "antrol", "bridging"],
    "data": [
        "security/ir.model.access.csv",
        "views/hms_bpjs_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
