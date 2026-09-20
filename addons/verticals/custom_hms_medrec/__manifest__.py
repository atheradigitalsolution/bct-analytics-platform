# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Rekam Medis (KLPCM, ROI, Retensi, Surat Keterangan)",
    "summary": "Analisis kelengkapan berkas (KLPCM) sebagai gerbang koding klaim, "
               "pelepasan informasi PMK 24/2022, koreksi RME, retensi 25 tahun, "
               "surat keterangan medis dan sertifikat kematian.",
    "description": """
SIMRS — Rekam Medis (custom_hms_medrec)
=======================================

Modul ini menampung pekerjaan **PMIK** (Perekam Medis dan Informasi Kesehatan):
pekerjaan yang dimulai justru ketika pelayanan klinis selesai.

**KLPCM adalah gerbang, bukan laporan.**
``hms.klpcm`` bukan sekadar rekap kelengkapan berkas untuk rapat mutu. Selama
masih ada satu baris KLPCM terbuka pada sebuah kunjungan, kunjungan itu
**tidak boleh masuk koding klaim** (lihat ``custom_hms_casemix``:
``hms.claim.action_start_coding``). Urutannya disengaja: klaim yang dikoding
dari berkas tidak lengkap adalah klaim yang akan dikembalikan BPJS sebagai
*pending* berbulan-bulan kemudian, ketika dokternya sudah lupa pasiennya.
Menahan satu hari di sini lebih murah daripada menahan enam bulan di sana.

**Analisis kuantitatif berjalan sendiri, penutupannya pun sendiri.**
Saat kunjungan ditutup atau pasien dipulangkan, komponen wajib diperiksa dari
dokumen yang benar-benar ada (``hms.clinical.note``, ``hms.consent``,
``hms.summary``, ``hms.nursing.assessment``, ``hms.order``). Setiap komponen
yang kurang melahirkan satu baris KLPCM dengan penanggung jawab dan tenggat.
PPA melengkapi lewat **entri baru** (append-only), lalu analisis ulang menutup
barisnya. Tidak ada tombol "tandai lengkap" — kelengkapan dibuktikan oleh
dokumennya, bukan oleh klaim petugas.

**Pelepasan informasi selalu meninggalkan jejak.**
``hms.roi.request`` menuliskan satu baris ``hms.access.log`` ber-``action``
``disclose`` untuk setiap penyerahan. Dasar hukumnya wajib dipilih: Ps. 34
(dengan persetujuan pasien — dan persetujuannya harus ada recordnya) atau
Ps. 35 (tanpa persetujuan — dan untuk pendidikan/penelitian wajib
dianonimkan). PMK 24/2022.

**Tidak pernah ada hard delete.** ``hms.retention.review`` mengusulkan
pemusnahan, tidak pernah melakukannya, dan menolak mengusulkan bila ada klaim
atau perkara yang masih berjalan.

Semua angka kebijakan datang dari ``hms.settings`` (``klpcm_due_hours``,
``emr_correction_grace_hours``, ``emr_retention_years``), bukan dari kode.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # custom_hms_nursing menarik seluruh rantai yang dibutuhkan analisis
    # kuantitatif: emr (catatan, consent, resume, diagnosis), inpatient
    # (admisi), order (penunjang), registration (encounter), audit
    # (hms.access.log), base (hms.settings, hms.practitioner).
    # Tidak ada dependensi di luar custom_hms_*.
    "depends": ["custom_hms_nursing"],
    "capability_tags": ["simrs", "rekam-medis", "klpcm", "roi", "retensi", "pmik"],
    "data": [
        "security/hms_medrec_groups.xml",
        "security/ir.model.access.csv",
        "security/hms_medrec_rules.xml",
        "data/hms_medrec_sequence.xml",
        "data/hms_medrec_cron.xml",
        "views/hms_klpcm_views.xml",
        "views/hms_roi_request_views.xml",
        "views/hms_correction_request_views.xml",
        "views/hms_retention_views.xml",
        "views/hms_medical_letter_views.xml",
        "views/hms_death_certificate_views.xml",
        "views/hms_medrec_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
