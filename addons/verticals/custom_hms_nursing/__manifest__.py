# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Nurse Center",
    "summary": "Station keperawatan: papan pasien, tugas terjadwal, skor EWS dengan eskalasi, "
               "eMAR dengan double-check high-alert, asuhan SDKI/SLKI/SIKI, hand-over SBAR.",
    "description": """
SIMRS — Nurse Center (custom_hms_nursing)
=========================================

**Tugas keperawatan dibuat sistem, bukan diingat perawat.** Jadwal TTV, jadwal
pemberian obat, instruksi dokter di CPPT, dan permintaan sampel semuanya
menjadi ``hms.nursing.task`` dengan jam jatuh tempo. Yang terlewat terlihat
sebagai *overdue*, bukan hilang.

**EWS menghitung dan mengeskalasi.** Setiap observasi dinilai NEWS2; skor ≥ 5
membuat tugas "lapor dokter" secara otomatis dan menerbitkan event. Skor yang
hanya ditampilkan tanpa konsekuensi adalah angka yang diabaikan saat sibuk.

**Obat high-alert menolak diberikan tanpa saksi.** Ini satu dari sedikit aturan
yang memang harus keras: ``hms.emar.administration`` menolak simpan bila obat
high-alert tidak punya perawat kedua yang berwenang.

**Hand-over SBAR terisi dari data 24 jam terakhir**, lalu ditandatangani dua
pihak. Perawat masih menulis penilaiannya sendiri — yang dihilangkan hanyalah
menyalin ulang angka yang sudah ada di sistem.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": ["custom_hms_inpatient", "custom_hms_pharmacy", "custom_hms_emr", "stock"],
    "capability_tags": ["simrs", "nursing", "emar", "ews", "sbar", "sdki"],
    "data": [
        "security/ir.model.access.csv",
        "data/hms_nursing_data.xml",
        "views/hms_nursing_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
