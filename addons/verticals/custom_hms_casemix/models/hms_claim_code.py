# -*- coding: utf-8 -*-
"""Kode klaim — salinan kerja koder, BUKAN penunjuk ke diagnosis dokter.

=============================================================================
KEPUTUSAN ARSITEKTUR INTI: KODING KLAIM TIDAK PERNAH MENULIS KE `hms.diagnosis`
=============================================================================

Cara termudah membangun ini salah: biarkan koder menyunting ``hms.diagnosis``
langsung, toh "itu diagnosis yang sama". Akibatnya tiga, dan ketiganya baru
terasa setelah bertahun-tahun data terkumpul:

1. **Rekam medis berhenti mencatat apa yang dokter simpulkan.** Ia berubah
   menjadi catatan apa yang paling menguntungkan untuk ditagih. Pasien yang
   membaca rekam medisnya membaca keputusan bagian keuangan.
2. **Upcoding kehilangan jejaknya.** Tidak ada lagi versi "sebelum" untuk
   dibandingkan. Audit internal (Permenkes 16/2019 mewajibkan tim pencegahan
   kecurangan) kehilangan satu-satunya bukti objektifnya.
3. **Laporan klinis dan laporan klaim jadi identik**, sehingga perbedaan
   antara keduanya — yang justru merupakan indikator mutu dokumentasi —
   tidak pernah bisa diukur.

Karena itu model ini berdiri sendiri. ``source_diagnosis_id`` adalah tautan
**balik** ke diagnosis dokter: dari mana koder mengambilnya. Tidak ada satu
baris pun di berkas ini yang menulis, membuat, atau menghapus
``hms.diagnosis``/``hms.procedure``, dan ``tests/test_claim_code.py``
membuktikannya dari dua arah — memeriksa nilai diagnosis dokter tetap sama,
dan memeriksa tidak ada baris diagnosis baru yang lahir.

Bila kode berbeda dari yang ditulis dokter, ``changed_by_coder`` menyala
sendiri dan ``change_reason`` menjadi wajib. Yang dijaga bukan larangan
mengubah — koder memang berwenang dan sering benar — melainkan larangan
mengubah **tanpa meninggalkan alasan**.

=============================================================================
KEPUTUSAN: DUA KOLOM KODE BERTIPE, BUKAN SATU KOLOM `Reference`
=============================================================================

Spesifikasi menyebut satu ``code_id``. Diimplementasikan sebagai
``fields.Reference``, kolomnya menjadi teks ``"model,id"``: tidak ada foreign
key, tidak ada integritas referensial, dan laporan RL 4 nanti tidak bisa
menjoin ke ``hms.icd10`` sama sekali. ICD-10 dan ICD-9-CM adalah dua master
yang berbeda, jadi di sini mereka dua kolom: ``icd10_id`` dan ``icd9_id``,
dengan ``kind`` yang menjaga hanya satu yang terisi.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

CODE_ROLES = [
    ("principal", "Diagnosis/Prosedur Utama"),
    ("comorbidity", "Komorbiditas"),
    ("complication", "Komplikasi"),
    ("external_cause", "Sebab Luar (Bab XX)"),
    ("secondary_procedure", "Prosedur Penyerta"),
]


class HmsClaimCode(models.Model):
    _name = "hms.claim.code"
    _description = "Kode Klaim (Koding Casemix)"
    _order = "claim_id, kind desc, seq, id"

    claim_id = fields.Many2one("hms.claim", "Klaim", required=True,
                               ondelete="cascade", index=True)
    encounter_id = fields.Many2one(related="claim_id.encounter_id", store=True, index=True)
    kind = fields.Selection(
        [("icd10", "ICD-10 — Diagnosis"), ("icd9", "ICD-9-CM — Prosedur")],
        string="Jenis Kode", required=True, default="icd10", index=True,
    )
    icd10_id = fields.Many2one("hms.icd10", "Kode ICD-10", index=True)
    icd9_id = fields.Many2one("hms.icd9", "Kode ICD-9-CM", index=True)
    code_display = fields.Char("Kode", compute="_compute_code_display", store=True)
    seq = fields.Integer("Urutan", default=10)
    role = fields.Selection(CODE_ROLES, string="Peran", required=True, default="principal")
    is_primary = fields.Boolean(
        "Kode Utama", compute="_compute_is_primary", store=True,
        help="Turunan dari peran. Disimpan sebagai kolom sendiri hanya supaya "
             "bisa disaring dan diindeks; satu-satunya yang menentukan adalah "
             "'Peran'.",
    )

    source_diagnosis_id = fields.Many2one(
        "hms.diagnosis", "Diagnosis Dokter (sumber)", ondelete="restrict",
        help="Diagnosis klinis yang menjadi dasar kode ini. Tautan BACA SAJA: "
             "koding klaim tidak pernah mengubah diagnosis dokter. Kosong "
             "berarti koder menambahkan kode yang tidak ada di catatan klinis "
             "— itu selalu dihitung sebagai perubahan.",
    )
    source_procedure_id = fields.Many2one(
        "hms.procedure", "Tindakan (sumber)", ondelete="restrict",
        help="Padanan source_diagnosis_id untuk kode ICD-9-CM.",
    )
    changed_by_coder = fields.Boolean(
        "Diubah Koder", compute="_compute_changed_by_coder", store=True,
        help="Menyala bila kode ini berbeda dari catatan klinis sumbernya, "
             "atau tidak punya sumber sama sekali.",
    )
    change_reason = fields.Text(
        "Alasan Perbedaan",
        help="Wajib bila kode berbeda dari diagnosis/tindakan dokter. Inilah "
             "satu-satunya catatan yang bisa dibaca auditor ketika "
             "membandingkan resume dengan kode yang diajukan.",
    )
    query_id = fields.Many2one("hms.coding.query", "Pertanyaan ke DPJP",
                               ondelete="set null")
    note = fields.Char("Catatan")

    # Satu kode utama per klaim PER JENIS. Sebuah episode rawat inap punya
    # diagnosis utama (ICD-10) sekaligus prosedur utama (ICD-9-CM); index yang
    # hanya memakai claim_id akan menolak salah satunya dan memaksa koder
    # menurunkan prosedur utama menjadi penyerta — yang mengubah hasil
    # grouping. Partial unique index, karena peran selain 'principal' memang
    # boleh berulang.
    _one_principal_per_kind = models.UniqueIndex(
        "(claim_id, kind) WHERE role = 'principal'",
    )
    _no_duplicate_icd10 = models.UniqueIndex(
        "(claim_id, icd10_id) WHERE kind = 'icd10' AND icd10_id IS NOT NULL",
    )

    # --- computes ---------------------------------------------------------
    @api.depends("kind", "icd10_id", "icd9_id")
    def _compute_code_display(self):
        for rec in self:
            code = rec.icd10_id if rec.kind == "icd10" else rec.icd9_id
            rec.code_display = code.code or False

    @api.depends("role")
    def _compute_is_primary(self):
        for rec in self:
            rec.is_primary = rec.role == "principal"

    @api.depends("kind", "icd10_id", "icd9_id",
                 "source_diagnosis_id.icd10_id", "source_procedure_id.icd9_id")
    def _compute_changed_by_coder(self):
        for rec in self:
            if rec.kind == "icd10":
                source = rec.source_diagnosis_id
                rec.changed_by_coder = (
                    not source or source.icd10_id != rec.icd10_id
                )
            else:
                source = rec.source_procedure_id
                rec.changed_by_coder = (
                    not source or source.icd9_id != rec.icd9_id
                )

    @api.depends("code_display", "role")
    def _compute_display_name(self):
        roles = dict(CODE_ROLES)
        for rec in self:
            rec.display_name = f"{rec.code_display or '?'} ({roles.get(rec.role, '')})"

    # --- constraints ------------------------------------------------------
    @api.constrains("kind", "icd10_id", "icd9_id")
    def _check_code_matches_kind(self):
        for rec in self:
            if rec.kind == "icd10" and (not rec.icd10_id or rec.icd9_id):
                raise ValidationError(_(
                    "Kode berjenis ICD-10 harus mengisi kolom ICD-10 dan "
                    "mengosongkan kolom ICD-9-CM."
                ))
            if rec.kind == "icd9" and (not rec.icd9_id or rec.icd10_id):
                raise ValidationError(_(
                    "Kode berjenis ICD-9-CM harus mengisi kolom ICD-9-CM dan "
                    "mengosongkan kolom ICD-10."
                ))

    @api.constrains("kind", "role")
    def _check_role_matches_kind(self):
        """Peran diagnosis dan peran prosedur bukan daftar yang sama."""
        for rec in self:
            if rec.kind == "icd9" and rec.role in (
                "comorbidity", "complication", "external_cause"
            ):
                raise ValidationError(_(
                    "Peran '%s' hanya berlaku untuk kode diagnosis ICD-10."
                ) % dict(CODE_ROLES)[rec.role])
            if rec.kind == "icd10" and rec.role == "secondary_procedure":
                raise ValidationError(_(
                    "Peran 'Prosedur Penyerta' hanya berlaku untuk kode "
                    "ICD-9-CM."
                ))

    @api.constrains("changed_by_coder", "change_reason")
    def _check_change_reason(self):
        for rec in self:
            if rec.changed_by_coder and not (rec.change_reason or "").strip():
                raise ValidationError(_(
                    "Kode %(c)s berbeda dari catatan klinis dokter (atau tidak "
                    "punya sumber). Alasan perbedaan wajib diisi — inilah satu-"
                    "satunya penjelasan yang tersedia ketika auditor "
                    "membandingkan resume dengan kode yang diajukan."
                ) % {"c": rec.code_display or "-"})

    @api.constrains("source_diagnosis_id", "source_procedure_id", "claim_id")
    def _check_source_belongs_to_encounter(self):
        for rec in self:
            encounter = rec.claim_id.encounter_id
            if rec.source_diagnosis_id and rec.source_diagnosis_id.encounter_id != encounter:
                raise ValidationError(_(
                    "Diagnosis sumber berasal dari kunjungan lain."
                ))
            if rec.source_procedure_id and rec.source_procedure_id.encounter_id != encounter:
                raise ValidationError(_(
                    "Tindakan sumber berasal dari kunjungan lain."
                ))

    @api.constrains("claim_id", "kind", "icd10_id", "icd9_id", "role", "seq",
                    "change_reason", "source_diagnosis_id", "source_procedure_id")
    def _check_claim_is_editable(self):
        """Kode klaim yang sudah final tidak boleh berubah lagi.

        Setelah finalisasi, angka yang diajukan ke penjamin sudah keluar.
        Perubahan setelah itu ditempuh lewat pengajuan ulang (yang membawa
        ``correction_note``) atau lewat ``hms.claim.adjustment``, bukan dengan
        menyunting baris lama sampai cocok.
        """
        frozen = ("finalized", "submitted", "bpjs_verifying", "approved",
                  "resubmitted", "dispute", "rejected", "paid", "expired")
        for rec in self:
            if rec.claim_id.state in frozen:
                raise ValidationError(_(
                    "Klaim %(n)s berstatus '%(s)s'; kodenya tidak dapat diubah "
                    "lagi. Pakai pengajuan ulang atau penyesuaian klaim."
                ) % {"n": rec.claim_id.name,
                     "s": dict(rec.claim_id._fields["state"].selection)[
                         rec.claim_id.state]})
