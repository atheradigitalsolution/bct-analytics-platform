# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Outbox Event & Antrian Job",
    "summary": "Outbox event realtime ke Redis dan job runner dengan retry/backoff "
               "untuk bridging BPJS dan SATUSEHAT.",
    "description": """
SIMRS — Outbox Event & Antrian Job (custom_hms_queue)
=====================================================

Dua mekanisme, satu modul, karena keduanya menyelesaikan masalah yang sama:
pekerjaan yang tidak boleh ikut menggantung transaksi pengguna.

**Outbox (``hms.event``).** Perubahan penting ditulis ke tabel event di dalam
transaksi yang sama dengan perubahan datanya. Publikasi ke Redis terjadi pada
*post-commit*, bukan lewat cron — layar TV antrian harus menyala di bawah dua
detik, dan cron Odoo paling cepat satu menit. Cron tetap ada, tapi perannya
hanya menyapu event yang gagal terkirim (Redis mati, jaringan putus).

Konsekuensi yang disengaja: event tidak pernah terbit untuk transaksi yang
di-rollback, karena barisnya ikut hilang bersama rollback.

**Klien Redis ditulis sendiri.** Image Odoo bersama tidak punya paket
``redis`` dan menambahkannya berarti membangun ulang image yang dipakai seluruh
tenant produksi. Protokol RESP untuk ``AUTH``/``SELECT``/``PUBLISH`` hanya
puluhan baris, jadi modul ini membawa klien soketnya sendiri di
``tools/resp.py``.

**Job (``hms.job``).** Semua panggilan keluar (SEP, Antrean, FHIR) berjalan di
sini, tidak pernah sinkron dari request pengguna. Worker mengambil pekerjaan
dengan ``SELECT ... FOR UPDATE SKIP LOCKED`` sehingga beberapa worker aman
berjalan bersamaan; kegagalan mundur secara eksponensial (1m, 5m, 15m, 1j, 6j)
lalu berhenti di status ``dead`` alih-alih mencoba selamanya.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_base"],
    "capability_tags": ["simrs", "outbox", "redis", "job-queue", "bridging"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_queue_cron.xml",
        "views/hms_event_views.xml",
        "views/hms_job_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
