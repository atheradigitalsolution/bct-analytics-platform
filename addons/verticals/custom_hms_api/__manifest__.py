# -*- coding: utf-8 -*-
{
    "name": "SIMRS — REST API v1",
    "summary": "REST API per use-case dengan JWT, idempotency, rate limit dan endpoint cetak "
               "untuk layar frontline Next.js.",
    "description": """
SIMRS — REST API v1 (custom_hms_api)
====================================

**Setiap request berjalan sebagai user Odoo sungguhan.** Token membawa `uid`;
controller membangun ulang environment dengan user itu, sehingga ACL dan record
rule berlaku persis seperti di UI Odoo. Tidak ada ``sudo()`` di jalur request —
API yang melewati hak akses adalah pintu belakang ke seluruh rekam medis.

**Satu use-case, satu endpoint, satu transaksi.** ``POST /registrations``
mencari/membuat pasien, membuat encounter, menerbitkan tiket antrian dan
menjadwalkan SEP dalam satu commit. Frontend tidak pernah memegang setengah
keadaan.

**Idempotency ditegakkan server.** Header ``Idempotency-Key`` disimpan bersama
hash responsnya; pengulangan akibat jaringan buruk mengembalikan jawaban yang
sama, bukan pasien kedua.

**Error punya bentuk tetap** — ``{"error": {"code", "message", "fields"}}``
dengan status HTTP yang benar, sehingga layar bisa membedakan "salah isi" dari
"tidak berhak" dari "sistem sedang bermasalah".
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "custom_hms_base", "custom_hms_registration", "custom_hms_emr", "custom_hms_order",
        "custom_hms_pharmacy", "custom_hms_lab", "custom_hms_radiology",
        "custom_hms_inpatient", "custom_hms_billing", "custom_hms_qms",
        "custom_hms_nursing", "custom_hms_cashier", "custom_hms_scheduling",
        "custom_hms_unit_pnl", "custom_hms_bridging_bpjs", "custom_hms_bridging_satusehat",
        # Casemix, rekam medis dan keselamatan pasien: modelnya dilayani
        # controller di sini, jadi dependensinya harus nyata. Tanpa ini
        # `request.env["hms.claim"]` hanya ada bila kebetulan modulnya ikut
        # terpasang — kegagalan yang muncul di tangan pengguna, bukan saat
        # instalasi.
        "custom_hms_casemix", "custom_hms_medrec", "custom_hms_safety",
    ],
    "capability_tags": ["simrs", "rest-api", "jwt", "idempotency"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_api_cron.xml",
        "views/hms_api_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
