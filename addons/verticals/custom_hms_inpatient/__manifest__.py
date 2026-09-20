# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Rawat Inap",
    "summary": "Admisi, bed board realtime, transfer kelas, charge harian otomatis, "
               "pemulangan, sensus dan BOR.",
    "description": """
SIMRS — Rawat Inap (custom_hms_inpatient)
=========================================

**Riwayat bed adalah dasar tarif, bukan catatan.** ``hms.bed.assignment``
menyimpan tiap potongan waktu seorang pasien di sebuah bed beserta kelas yang
berlaku saat itu. Pasien yang pindah dari kelas II ke kelas I pada hari ketiga
ditagih kelas II untuk dua hari pertama — dan itu hanya mungkin bila riwayatnya
ada, bukan bila bed terakhir yang dibaca.

**Naik kelas atas permintaan sendiri berbeda dari pindah karena medis.**
``charge_class_id`` dipisahkan dari ``class_id``: pasien BPJS yang naik kelas
tetap ditagih hak kelasnya ke penjamin, selisihnya ke pasien. Menyatukan dua
kolom ini berarti rumah sakit menagih BPJS untuk kelas yang bukan haknya.

**Charge harian berjalan pukul 00:05 dan idempoten.** Cron yang tereksekusi dua
kali tidak boleh menagih kamar dua kali; kunci uniknya (admisi, tanggal, jenis)
ada di basis data, bukan di keyakinan bahwa cron hanya jalan sekali.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_emr", "custom_hms_order"],
    "capability_tags": ["simrs", "inpatient", "bed-management", "census", "bor"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_inpatient_sequence.xml",
        "data/hms_inpatient_cron.xml",
        "views/hms_admission_views.xml",
        "views/hms_bed_board_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
