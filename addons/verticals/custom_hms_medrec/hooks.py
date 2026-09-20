# -*- coding: utf-8 -*-
"""Penyemaian contoh untuk layar demo — dan hanya untuk demo.

Pola yang sama dengan ``custom_hms_safety``: seluruh basis data SIMRS di
lingkungan ini dipasang dengan ``--without-demo=all``, sehingga kunci ``demo``
pada manifest tidak akan pernah dimuat dan layar rekam medis akan kosong
justru saat dipakai presentasi.

Berbeda dari ``custom_hms_demo`` yang **gagal keras** di luar database
``*_demo``, penyemaian di sini **dilewati dengan tenang**: yang salah bukan
memasang modul ini di produksi — itu justru tujuannya — melainkan menaruh
contoh permintaan pelepasan informasi di sana.

Satu pengecualian yang sengaja: ``_seed_retention_rule`` TIDAK berjalan di
luar demo juga, meskipun aturan retensi adalah konfigurasi dan bukan data
contoh. Alasannya, aturan retensi menentukan kapan sebuah rekam medis masuk
daftar usulan pemusnahan; memasangnya diam-diam saat instalasi berarti rumah
sakit mendapat kebijakan arsip yang tidak pernah diputuskan siapa pun.
"""
import logging
from datetime import timedelta

from odoo import fields

_logger = logging.getLogger(__name__)

# Keanggotaan unit rekam medis di database demo. Lihat catatan yang sama di
# custom_hms_safety: hibah hak akses yang berlaku di setiap pemasangan harus
# lewat XML/implied_ids, bukan lewat hook — yang di sini sengaja terbatas
# pada database demo supaya layarnya bisa diperagakan.
DEMO_MEDREC_LOGINS = ["pendaftaran@simrs-demo.invalid"]
DEMO_MEDREC_MANAGER_LOGINS = ["manajer@simrs-demo.invalid"]


def post_init_hook(env):
    if not env.cr.dbname.endswith("_demo"):
        _logger.info(
            "SIMRS: %s bukan database demo, contoh rekam medis dilewati.",
            env.cr.dbname,
        )
        return
    _grant_demo_groups(env)
    _seed_klpcm(env)
    _seed_roi(env)
    _seed_correction(env)
    _seed_retention(env)
    _seed_letters(env)


def _grant(env, xmlid, logins):
    group = env.ref(xmlid, raise_if_not_found=False)
    if not group:
        return
    users = env["res.users"].sudo().search([("login", "in", logins)])
    admin = env.ref("base.user_admin", raise_if_not_found=False)
    if admin:
        users |= admin
    for user in users:
        if group not in user.all_group_ids:
            user.write({"group_ids": [(4, group.id)]})
            _logger.info("SIMRS demo: %s masuk %s", user.login, xmlid)


def _grant_demo_groups(env):
    _grant(env, "custom_hms_medrec.group_hms_medrec", DEMO_MEDREC_LOGINS)
    _grant(env, "custom_hms_medrec.group_hms_medrec_manager", DEMO_MEDREC_MANAGER_LOGINS)


def _seed_klpcm(env):
    """Jalankan analisis atas kunjungan yang memang sudah selesai.

    Tidak ada baris KLPCM yang dikarang di sini: yang disemai adalah
    *analisisnya*, dan temuannya muncul hanya kalau berkas demo memang kurang.
    Daftar yang kosong karena berkas demo kebetulan lengkap adalah hasil yang
    benar, bukan kegagalan penyemaian.
    """
    if env["hms.klpcm"].search_count([]):
        return
    encounters = env["hms.encounter"].search(
        [("state", "in", ("finished", "discharged"))], limit=40
    )
    if not encounters:
        _logger.info("SIMRS demo: belum ada kunjungan selesai, analisis KLPCM dilewati.")
        return
    env["hms.klpcm"].analyze_encounter(encounters)
    _logger.info(
        "SIMRS demo: %s temuan KLPCM dari %s kunjungan",
        env["hms.klpcm"].search_count([]), len(encounters),
    )


def _seed_roi(env):
    Roi = env["hms.roi.request"]
    if Roi.search_count([]):
        return
    patient = env["hms.patient"].search([], limit=1)
    if not patient:
        _logger.info("SIMRS demo: belum ada pasien, contoh ROI dilewati.")
        return
    consent = env["hms.consent"].search(
        [("patient_id", "=", patient.id), ("state", "=", "signed")], limit=1
    )
    now = fields.Datetime.now()

    # 1. Permintaan asuransi dengan dasar Ps. 34 — lengkap sampai diserahkan,
    #    supaya jejak akses ber-action `disclose` benar-benar ada di layar.
    if consent:
        approved = Roi.create({
            "patient_id": patient.id,
            "requester_type": "insurance",
            "requester_name": "PT Asuransi Contoh",
            "requester_organization": "PT Asuransi Contoh",
            "requester_contact": "021-0000000",
            "purpose": "Verifikasi pengajuan klaim rawat inap peserta.",
            "legal_basis": "art34",
            "consent_id": consent.id,
            "requested_at": now - timedelta(days=3),
            "document_ids": [(0, 0, {
                "doc_type": "summary",
                "description": "Ringkasan pulang rawat inap",
                "page_count": 2,
            })],
            "receipt_name": "Kurir PT Asuransi Contoh",
            "delivery_channel": "in_person",
        })
        approved.action_submit()
        approved.action_approve()
        approved.action_deliver()
    else:
        _logger.info(
            "SIMRS demo: belum ada persetujuan bertanda tangan, contoh ROI Ps. 34 dilewati."
        )

    # 2. Permintaan penelitian dengan dasar Ps. 35 — wajib anonim, berhenti di
    #    meja pimpinan supaya tombol persetujuan bisa diperagakan.
    pending = Roi.create({
        "patient_id": patient.id,
        "requester_type": "research",
        "requester_name": "Tim Peneliti Fakultas Kedokteran",
        "requester_organization": "Universitas Contoh",
        "purpose": "Penelitian pola diagnosis rawat jalan triwulan.",
        "legal_basis": "art35",
        "anonymized": True,
        "requested_at": now - timedelta(days=1),
        "document_ids": [(0, 0, {
            "doc_type": "clinical_note",
            "description": "Ekstraksi diagnosis tanpa identitas",
        })],
    })
    pending.action_submit()
    _logger.info("SIMRS demo: %s contoh permintaan pelepasan informasi", Roi.search_count([]))


def _seed_correction(env):
    Correction = env["hms.correction.request"]
    if Correction.search_count([]):
        return
    note = env["hms.clinical.note"].search([("signed", "=", True)], limit=1)
    if not note:
        _logger.info("SIMRS demo: belum ada catatan bertanda tangan, contoh koreksi dilewati.")
        return
    grace = env["hms.settings"].get_settings().emr_correction_grace_hours or 48
    request = Correction.create({
        "encounter_id": note.encounter_id.id,
        "target_model": note._name,
        "target_res_id": note.id,
        "target_label": note.display_name,
        "field_label": "Asesmen (A)",
        # Sengaja jauh di luar masa tenggang: contoh yang masih di dalam masa
        # tenggang akan ditolak action_submit(), dan antrian persetujuan demo
        # jadi kosong.
        "entry_created_at": fields.Datetime.subtract(
            fields.Datetime.now(), hours=grace * 3
        ),
        "old_value": "Suspek dengue fever hari ke-3.",
        "new_value": "Suspek dengue fever hari ke-5.",
        "reason": "Hari sakit tertulis keliru; anamnesis ulang keluarga menyebut "
                  "demam mulai dua hari lebih awal.",
    })
    request.action_submit()
    _logger.info("SIMRS demo: contoh permintaan koreksi RME dibuat")


def _seed_retention(env):
    Rule = env["hms.retention.rule"]
    if Rule.search_count([]):
        return
    rule = Rule.create({
        "name": "Retensi umum rekam medis",
        "scope": "all",
        "note": "PMK 24/2022 Ps. 39 ayat (1): paling singkat 25 tahun sejak "
                "tanggal terakhir pasien berobat.",
    })
    reviews = env["hms.retention.review"].generate_reviews(rule)
    _logger.info("SIMRS demo: aturan retensi dibuat, %s tinjauan tersusun", len(reviews))


def _seed_letters(env):
    Letter = env["hms.medical.letter"]
    if Letter.search_count([]):
        return
    doctor = env["hms.practitioner"].search([("type", "=", "doctor")], limit=1)
    patient = env["hms.patient"].search([], limit=1)
    if not (doctor and patient):
        _logger.info("SIMRS demo: belum ada dokter/pasien, contoh surat dilewati.")
        return
    today = fields.Date.context_today(env["hms.medical.letter"])
    letter = Letter.create({
        "type": "sick_leave",
        "patient_id": patient.id,
        "practitioner_id": doctor.id,
        "purpose": "Keperluan izin kerja",
        "body": "Yang bersangkutan memerlukan istirahat karena sakit dan "
                "dianjurkan tidak bekerja selama masa tersebut di atas.",
        "rest_from": today,
        "rest_to": today + timedelta(days=2),
    })
    letter.action_sign()
    Letter.create({
        "type": "fit",
        "patient_id": patient.id,
        "practitioner_id": doctor.id,
        "purpose": "Keperluan melamar pekerjaan",
        "body": "Berdasarkan pemeriksaan, yang bersangkutan dalam keadaan sehat.",
    })
    _seed_death_certificate(env, doctor)
    _logger.info("SIMRS demo: contoh surat keterangan medis dibuat")


def _seed_death_certificate(env, doctor):
    """Hanya bila ada kunjungan yang memang tercatat meninggal.

    Menerbitkan sertifikat kematian untuk pasien demo yang di kunjungannya
    tercatat pulang sehat akan membuat dua catatan di layar yang sama saling
    membantah — dan constraint di model memang menolaknya. Jadi contoh ini
    dilewati dengan tenang bila datanya tidak ada.
    """
    if env["hms.death.certificate"].search_count([]):
        return
    encounter = env["hms.encounter"].search(
        [("discharge_disposition", "=", "deceased")], limit=1
    )
    if not encounter:
        _logger.info("SIMRS demo: belum ada kunjungan dengan cara keluar meninggal, "
                     "contoh sertifikat kematian dilewati.")
        return
    codes = env["hms.icd10"].search([], limit=2)
    if len(codes) < 2:
        return
    certificate = env["hms.death.certificate"].create({
        "patient_id": encounter.patient_id.id,
        "encounter_id": encounter.id,
        "admitted_at": encounter.arrival_at,
        "died_at": encounter.closed_at or fields.Datetime.now(),
        "place_of_death": "hospital",
        "manner": "natural",
        "cause_a_id": codes[0].id,
        "cause_a_interval": "6 jam",
        "cause_b_id": codes[1].id,
        "cause_b_interval": "5 hari",
        "certified_by_id": doctor.id,
    })
    certificate.action_sign()
