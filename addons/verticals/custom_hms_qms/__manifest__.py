# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Sistem Antrian (QMS)",
    "summary": "Antrian terpadu multi-tahap: kiosk cetak, display TV, loket pemanggil, "
               "prioritas lansia/disabilitas, estimasi tunggu, ESC/POS tanpa pustaka luar.",
    "description": """
SIMRS — Sistem Antrian / QMS (custom_hms_qms)
=============================================

**Satu pasien, satu perjalanan.** Seorang pasien melewati beberapa titik
layanan dalam sehari — pendaftaran, poli, lab, kembali ke poli, apotek, kasir.
``hms.qms.journey`` merangkai tiketnya sehingga waktu tunggu total dapat
dihitung, bukan hanya waktu tunggu di satu loket.

**Tahap berikutnya terbit sendiri.** Dokter menutup encounter dengan resep →
tiket apotek terbit; ada order lab → tiket lab terbit. Petugas tidak perlu
mengingat alurnya, dan pasien tidak perlu kembali ke loket untuk minta nomor
baru.

**Prioritas disisipkan, bukan mendahului seluruhnya.** Lansia, disabilitas, ibu
hamil, dan bayi dipanggil satu di antara setiap N reguler. Prioritas mutlak
membuat antrian reguler berhenti bergerak pada jam sibuk, dan itu memicu
keributan di ruang tunggu yang nyata.

**ESC/POS dirender sendiri.** ``tools/escpos.py`` menghasilkan byte perintah
printer termal langsung — tidak ada pustaka pihak ketiga, sesuai standar
Athera, dan struk dapat dikirim ke printer jaringan lewat soket 9100 atau
diambil agen cetak di PC kiosk.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # custom_hms_order is a real dependency: this module extends
    # hms.order.line so a lab order puts the patient in the lab queue.
    # Without it declared, the class extension loads before the model
    # exists and the registry refuses to build.
    "depends": ["custom_hms_registration", "custom_hms_queue", "custom_hms_order"],
    "capability_tags": ["simrs", "qms", "queue", "kiosk", "escpos", "display"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_qms_data.xml",
        "report/hms_qms_reports.xml",
        "views/hms_qms_service_views.xml",
        "views/hms_qms_ticket_views.xml",
        "views/hms_qms_device_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
