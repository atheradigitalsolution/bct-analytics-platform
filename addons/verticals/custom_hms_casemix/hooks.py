# -*- coding: utf-8 -*-
"""Penyemaian contoh casemix — dan hanya untuk demo.

Pola yang sama dengan ``custom_hms_safety`` dan ``custom_hms_medrec``:
dilewati dengan tenang di luar database ``*_demo``.

**Yang sengaja TIDAK disemai: satu baris pun ``hms.eklaim.code``.**
Master itu harus diisi dari manual resmi WS E-Klaim; mengisinya dengan contoh
berarti menaruh tebakan di tabel yang justru dibuat untuk menampung jawaban
resmi — dan contoh yang terlanjur ada selalu berakhir dipakai sungguhan.
Layar demo master E-Klaim karena itu memang kosong, dengan teks yang
menjelaskan kenapa.
"""
import logging

from odoo import fields

_logger = logging.getLogger(__name__)

DEMO_CODER_LOGINS = ["pendaftaran@simrs-demo.invalid"]
DEMO_VERIFIER_LOGINS = ["manajer@simrs-demo.invalid"]


def post_init_hook(env):
    if not env.cr.dbname.endswith("_demo"):
        _logger.info(
            "SIMRS: %s bukan database demo, contoh casemix dilewati.", env.cr.dbname
        )
        return
    _grant_demo_groups(env)
    _seed_claims(env)


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
    _grant(env, "custom_hms_casemix.group_hms_coder", DEMO_CODER_LOGINS)
    _grant(env, "custom_hms_casemix.group_hms_casemix_verifier", DEMO_VERIFIER_LOGINS)


def _seed_claims(env):
    """Buka klaim untuk kunjungan yang memang sudah selesai dan berpenjamin.

    Klaimnya berhenti di state yang bisa dicapai apa adanya. Kunjungan yang
    masih punya temuan KLPCM terbuka sengaja dibiarkan berhenti di
    ``to_code`` — itulah gerbangnya bekerja, dan layar demo justru perlu
    memperlihatkannya.
    """
    Claim = env["hms.claim"]
    if Claim.search_count([]):
        return
    encounters = env["hms.encounter"].search([
        ("state", "in", ("finished", "discharged")),
        ("payer_id.requires_sep", "=", True),
    ], limit=6)
    if not encounters:
        encounters = env["hms.encounter"].search(
            [("state", "in", ("finished", "discharged"))], limit=6
        )
    if not encounters:
        _logger.info("SIMRS demo: belum ada kunjungan selesai, contoh klaim dilewati.")
        return

    # Tanpa `try/except` yang menelan galat. Sebuah penyemaian demo yang
    # menangkap Exception apa pun akan menyembunyikan galat basis data
    # sekaligus meninggalkan transaksi dalam keadaan abort — dan yang terlihat
    # kemudian bukan "contoh dilewati", melainkan instalasi modul yang gagal
    # dengan pesan sama sekali lain. Yang dipakai di sini adalah syarat yang
    # diperiksa lebih dulu, bukan galat yang ditangkap belakangan.
    created = Claim.browse()
    for encounter in encounters:
        created |= Claim.create_for_encounter(encounter)
    if not created:
        return

    for claim in created:
        _advance_one(env, claim)
    _logger.info("SIMRS demo: %s contoh klaim dibuat", len(created))


def _advance_one(env, claim):
    """Dorong satu klaim sejauh yang datanya izinkan, tanpa memaksa.

    Setiap gerbang yang menolak dicatat sebagai info, bukan ditembus: contoh
    demo yang dibuat dengan mem-bypass penjaganya sendiri akan memperagakan
    sistem yang tidak ada.
    """
    if claim.encounter_id.klpcm_open_count:
        _logger.info(
            "SIMRS demo: klaim %s berhenti di to_code (%s temuan KLPCM terbuka)",
            claim.name, claim.encounter_id.klpcm_open_count,
        )
        return
    claim.action_start_coding()

    diagnoses = env["hms.diagnosis"].search([
        ("encounter_id", "=", claim.encounter_id.id),
    ], order="rank, id")
    primary = diagnoses.filtered(lambda d: d.rank == "primary")[:1]
    if not primary:
        _logger.info("SIMRS demo: klaim %s tanpa diagnosis utama, berhenti di coding",
                     claim.name)
        return
    Code = env["hms.claim.code"]
    Code.create({
        "claim_id": claim.id,
        "kind": "icd10",
        "icd10_id": primary.icd10_id.id,
        "role": "principal",
        "seq": 1,
        "source_diagnosis_id": primary.id,
    })
    for index, secondary in enumerate(diagnoses - primary, start=2):
        Code.create({
            "claim_id": claim.id,
            "kind": "icd10",
            "icd10_id": secondary.icd10_id.id,
            "role": "comorbidity" if secondary.rank != "complication" else "complication",
            "seq": index,
            "source_diagnosis_id": secondary.id,
        })
    procedures = env["hms.procedure"].search([
        ("encounter_id", "=", claim.encounter_id.id), ("icd9_id", "!=", False),
    ], limit=1)
    if procedures:
        Code.create({
            "claim_id": claim.id,
            "kind": "icd9",
            "icd9_id": procedures.icd9_id.id,
            "role": "principal",
            "seq": 10,
            "source_procedure_id": procedures.id,
        })

    # Jalankan aturan pre-grouping lebih dulu supaya kondisinya diperiksa,
    # bukan ditabrak. Klaim yang terdeteksi readmisi sengaja DIBIARKAN
    # berhenti di `coding`: alasan readmisi adalah keterangan klinis, dan
    # mengarangnya demi layar demo yang rapi justru memperagakan sistem yang
    # penjaganya bisa dilewati.
    claim.action_run_pregrouping()
    if claim.is_readmission and not claim.readmission_reason:
        _logger.info(
            "SIMRS demo: klaim %s berhenti di coding (readmisi, alasan harus manusia)",
            claim.name,
        )
        return
    claim.action_code_done()
    claim.action_verify_internal()
    claim.action_finalize()
    _seed_batch_and_submit(env, claim)


def _seed_batch_and_submit(env, claim):
    if not claim.discharge_at:
        return
    period = claim.discharge_at.date().replace(day=1)
    Batch = env["hms.claim.batch"]
    batch = Batch.search([
        ("service_period", "=", period),
        ("care_type", "=", claim.care_type),
        ("batch_type", "=", "regular"),
        ("payer_id", "=", claim.payer_id.id),
    ], limit=1)
    if not batch:
        batch = Batch.create({
            "service_period": period,
            "care_type": claim.care_type,
            "batch_type": "regular",
            "payer_id": claim.payer_id.id,
            "fpk_no": f"FPK/{period.strftime('%Y%m')}/DEMO",
        })
    claim.write({"batch_id": batch.id})
    claim.action_submit()
    claim.action_start_verification()
