# -*- coding: utf-8 -*-
{
    "name": "SIMRS — Casemix & Klaim",
    "summary": "Koding klaim terpisah dari diagnosis klinis, state machine klaim "
               "BPJS lengkap, aturan pre-grouping tanpa E-Klaim, batch & "
               "penyesuaian klaim.",
    "description": """
SIMRS — Casemix & Klaim (custom_hms_casemix)
============================================

**Koding klaim TIDAK PERNAH menulis ke diagnosis klinis.**
Ini keputusan arsitektur inti modul ini. ``hms.claim.code`` adalah salinan
kerja koder dengan tautan balik ke ``hms.diagnosis`` yang menjadi sumbernya
(``source_diagnosis_id``), bukan penunjuk yang bisa diedit. Ketika koder
memilih kode lain daripada yang ditulis DPJP, yang berubah hanya baris klaim;
diagnosis dokter tetap apa adanya, dan selisihnya wajib beralasan
(``change_reason``). Lihat ``models/hms_claim_code.py``.

Kenapa sekeras itu: begitu koding boleh menimpa diagnosis, rekam medis
berhenti menjadi catatan apa yang dokter simpulkan dan berubah menjadi
catatan apa yang paling menguntungkan untuk ditagih. Upcoding pun kehilangan
jejaknya — tidak ada lagi versi "sebelum" untuk dibandingkan saat audit.

**KLPCM adalah gerbangnya.** ``action_start_coding`` menolak kunjungan yang
masih punya temuan ``hms.klpcm`` terbuka (lihat ``custom_hms_medrec``).

**Yang sengaja dikosongkan.** Manual resmi web service E-Klaim 5.10.x belum
ada. Karena itu modul ini **tidak** membangun bridging E-Klaim: tidak ada
``set_claim_data``, tidak ada enkripsi, tidak ada pemanggilan ``ws.php``, dan
tidak satu pun enumerasi (``jenis_rawat``, ``cara_masuk``,
``discharge_status``, ``kode_tarif``, ``payor_id``, 18 komponen ``tarif_rs``)
ditebak di dalam kode. Yang ada hanya dua titik masuk yang menunggu diisi dari
manual resmi: ``hms.eklaim.code`` (master yang dapat diimpor) dan
``hms.eklaim.config`` (parameter, tanpa nilai bawaan).

**Finalisasi mengunci kunjungannya.** Begitu klaim mencapai ``finalized``,
dokumentasi klinis yang menjadi isinya — CPPT, diagnosis, tindakan, resume —
menolak tulis. Kuncinya punya pintu: sebuah ``hms.correction.request``
(``custom_hms_medrec``) yang sudah disetujui PMIK/pimpinan membukanya untuk
record yang ditunjuknya. Cakupan, pagar, dan alasan keduanya ada di
``models/hms_encounter_lock.py``.

**Penyesuaian klaim bersifat append-only, dan wewenangnya berjenjang.**
Baris yang sudah diotorisasi tidak pernah disunting; koreksinya baris baru.
Siapa yang boleh mengesahkan ditentukan
``hms.settings.claim_adjustment_authorization_limit`` — sengaja BUKAN
``claim_variance_threshold``, karena ambang review tarif dan plafon
pengesahan kerugian adalah dua keputusan yang berbeda.

Semua angka kebijakan berasal dari ``hms.settings``: ``claim_expiry_months``,
``claim_variance_threshold``, ``readmission_window_days``,
``fragmentation_window_days``, ``grouper_mode``,
``claim_adjustment_authorization_limit``.
""",
    "author": "Athera Digital Solution",
    "website": "https://athera-digital.com",
    "category": "Healthcare/SIMRS",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    # custom_hms_medrec  -> hms.klpcm (gerbang koding) + seluruh rantai klinis
    # custom_hms_billing -> hms.bill (tarif rumah sakit untuk variance)
    # custom_hms_bridging_bpjs -> hms.sep
    # Tidak ada dependensi di luar custom_hms_*.
    "depends": [
        "custom_hms_medrec",
        "custom_hms_billing",
        "custom_hms_bridging_bpjs",
    ],
    "capability_tags": ["simrs", "casemix", "klaim", "inacbg", "bpjs", "koding"],
    "data": [
        "security/hms_casemix_groups.xml",
        "security/ir.model.access.csv",
        "security/hms_casemix_rules.xml",
        "data/hms_casemix_sequence.xml",
        "data/hms_casemix_cron.xml",
        "views/hms_claim_views.xml",
        "views/hms_coding_query_views.xml",
        "views/hms_claim_batch_views.xml",
        "views/hms_claim_adjustment_views.xml",
        "views/hms_eklaim_views.xml",
        "views/hms_casemix_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
