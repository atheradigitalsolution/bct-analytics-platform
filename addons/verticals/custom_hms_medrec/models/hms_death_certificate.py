# -*- coding: utf-8 -*-
"""Sertifikat medis penyebab kematian — struktur ICD-10 bagian I dan II.

=============================================================================
KEPUTUSAN: PENYEBAB DASAR DIHITUNG, TIDAK DIISI TANGAN
=============================================================================

Formulir kematian internasional (dan ICD-10 Volume 2) menyusun bagian I
sebagai rantai sebab-akibat: I(a) adalah penyakit/kondisi yang **langsung**
menyebabkan kematian, I(b) yang menyebabkan I(a), dan seterusnya sampai I(d).
Yang dipakai statistik mortalitas — RL 4, sebab kematian nasional, SATUSEHAT
— **bukan** I(a), melainkan baris **terakhir yang terisi** pada bagian I:
itulah *underlying cause of death*.

Kesalahan klasik pada SIMRS adalah menyediakan satu kolom "penyebab kematian"
dan mengisinya dengan I(a). Hasilnya statistik yang seluruhnya berisi "gagal
napas" dan "henti jantung" — benar secara medis, tidak berguna sama sekali
untuk kesehatan masyarakat. Karena itu ``underlying_cause_id`` di sini
**computed**, tidak bisa diketik, dan diambil dari baris terdalam bagian I.

Bagian II (kondisi lain yang berkontribusi tetapi bukan bagian dari rantai)
sengaja dipisah dan tidak pernah ikut menjadi penyebab dasar.

=============================================================================
KEPUTUSAN: NDR DIHITUNG DARI JAM, BUKAN DARI PENILAIAN
=============================================================================

GDR menghitung seluruh kematian; NDR hanya kematian **≥ 48 jam** setelah
masuk. Batas itu dipakai sebagai proksi "kematian yang sempat dipengaruhi
mutu pelayanan". ``is_ndr`` dihitung dari selisih waktu masuk dan waktu
meninggal supaya angkanya tidak bergantung pada siapa yang mengisi formulir.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsDeathCertificate(models.Model):
    _name = "hms.death.certificate"
    _description = "Sertifikat Medis Penyebab Kematian"
    _order = "died_at desc, id desc"

    name = fields.Char("Nomor Sertifikat", readonly=True, copy=False, index=True,
                       help="Diterbitkan saat sertifikat ditandatangani.")
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True,
                                 ondelete="restrict", index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="restrict", index=True,
                                   domain="[('patient_id', '=', patient_id)]")
    died_at = fields.Datetime("Waktu Meninggal", required=True, index=True)
    place_of_death = fields.Selection(
        [("hospital", "Di rumah sakit"), ("on_arrival", "Meninggal saat tiba (DOA)"),
         ("transport", "Dalam perjalanan / ambulans"), ("other", "Tempat lain")],
        string="Tempat Meninggal", required=True, default="hospital",
    )
    manner = fields.Selection(
        [("natural", "Wajar / penyakit"), ("accident", "Kecelakaan"),
         ("suicide", "Bunuh diri"), ("homicide", "Pembunuhan"),
         ("undetermined", "Belum dapat ditentukan")],
        string="Jenis Kematian", required=True, default="natural",
    )

    # --- Bagian I: rantai sebab-akibat -----------------------------------
    cause_a_id = fields.Many2one("hms.icd10", "I(a) Penyebab Langsung", required=True,
                                 help="Penyakit atau kondisi yang langsung menyebabkan kematian.")
    cause_a_interval = fields.Char("I(a) Perkiraan Selang Waktu")
    cause_b_id = fields.Many2one("hms.icd10", "I(b) Akibat dari",
                                 help="Kondisi yang menyebabkan I(a).")
    cause_b_interval = fields.Char("I(b) Perkiraan Selang Waktu")
    cause_c_id = fields.Many2one("hms.icd10", "I(c) Akibat dari")
    cause_c_interval = fields.Char("I(c) Perkiraan Selang Waktu")
    cause_d_id = fields.Many2one("hms.icd10", "I(d) Akibat dari")
    cause_d_interval = fields.Char("I(d) Perkiraan Selang Waktu")

    # --- Bagian II: kondisi penyerta -------------------------------------
    contributing_ids = fields.Many2many(
        "hms.icd10", "hms_death_certificate_contributing_rel",
        "certificate_id", "icd10_id", string="II — Kondisi Lain yang Berkontribusi",
        help="Kondisi yang ikut menyebabkan kematian tetapi bukan bagian dari "
             "rantai pada bagian I. Tidak pernah menjadi penyebab dasar.",
    )

    underlying_cause_id = fields.Many2one(
        "hms.icd10", "Penyebab Dasar Kematian", compute="_compute_underlying_cause",
        store=True, index=True,
        help="Baris terakhir yang terisi pada bagian I. Inilah yang dipakai "
             "statistik mortalitas (RL 4, sebab kematian), bukan I(a).",
    )

    admitted_at = fields.Datetime("Waktu Masuk", help="Diisi otomatis dari kunjungan bila ada.")
    hours_since_admission = fields.Float("Lama Dirawat (jam)",
                                         compute="_compute_ndr", store=True)
    is_ndr = fields.Boolean(
        "Masuk NDR (>= 48 jam)", compute="_compute_ndr", store=True,
        help="Net Death Rate hanya menghitung kematian 48 jam atau lebih "
             "setelah pasien masuk.",
    )

    certified_by_id = fields.Many2one("hms.practitioner", "Dokter yang Menerangkan",
                                      required=True)
    certified_uid = fields.Many2one("res.users", "Akun Penanda Tangan", readonly=True, copy=False)
    certified_at = fields.Datetime("Waktu Tanda Tangan", readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draf"), ("signed", "Ditandatangani"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    cancel_reason = fields.Char("Alasan Pembatalan")
    note = fields.Text("Catatan")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor sertifikat kematian harus unik.")
    _one_per_patient = models.UniqueIndex(
        "(patient_id) WHERE state = 'signed'",
    )

    @api.depends("cause_a_id", "cause_b_id", "cause_c_id", "cause_d_id")
    def _compute_underlying_cause(self):
        for rec in self:
            chain = [rec.cause_d_id, rec.cause_c_id, rec.cause_b_id, rec.cause_a_id]
            rec.underlying_cause_id = next((c for c in chain if c), False)

    @api.depends("admitted_at", "died_at")
    def _compute_ndr(self):
        for rec in self:
            if rec.admitted_at and rec.died_at and rec.died_at >= rec.admitted_at:
                hours = (rec.died_at - rec.admitted_at).total_seconds() / 3600.0
            else:
                hours = 0.0
            rec.hours_since_admission = hours
            rec.is_ndr = hours >= 48.0

    @api.constrains("cause_a_id", "cause_b_id", "cause_c_id", "cause_d_id")
    def _check_chain_has_no_gap(self):
        """Rantai sebab-akibat tidak boleh berlubang.

        Mengisi I(a) dan I(c) tanpa I(b) berarti rantainya putus, dan penyebab
        dasar yang dihitung darinya salah. Lebih baik ditolak sekarang
        daripada masuk ke statistik mortalitas nasional.
        """
        for rec in self:
            chain = [rec.cause_a_id, rec.cause_b_id, rec.cause_c_id, rec.cause_d_id]
            # Setelah baris kosong pertama, tidak boleh ada baris yang terisi.
            seen_empty = False
            for entry in chain:
                if not entry:
                    seen_empty = True
                elif seen_empty:
                    raise ValidationError(_(
                        "Rantai penyebab kematian bagian I tidak boleh berlubang. "
                        "Isi I(a), lalu I(b), lalu I(c), lalu I(d) berurutan — "
                        "penyebab dasar dihitung dari baris terakhir yang terisi."
                    ))

    @api.constrains("died_at")
    def _check_not_in_future(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.died_at and rec.died_at > now:
                raise ValidationError(_("Waktu meninggal tidak boleh di masa depan."))

    @api.constrains("encounter_id", "patient_id")
    def _check_encounter(self):
        for rec in self:
            if not rec.encounter_id:
                continue
            if rec.encounter_id.patient_id != rec.patient_id:
                raise ValidationError(_("Kunjungan yang dipilih milik pasien lain."))
            disposition = rec.encounter_id.discharge_disposition
            if disposition and disposition != "deceased":
                raise ValidationError(_(
                    "Kunjungan %(n)s tercatat keluar dengan cara '%(d)s', bukan "
                    "meninggal. Perbaiki cara keluar kunjungan lebih dulu — dua "
                    "catatan yang saling membantah tentang hidup-matinya seorang "
                    "pasien tidak boleh dibiarkan berdampingan."
                ) % {"n": rec.encounter_id.name,
                     "d": dict(rec.encounter_id._fields["discharge_disposition"].selection
                               ).get(disposition)})

    @api.onchange("encounter_id")
    def _onchange_encounter(self):
        for rec in self:
            if rec.encounter_id and not rec.admitted_at:
                rec.admitted_at = rec.encounter_id.arrival_at

    @api.depends("name", "patient_id")
    def _compute_display_name(self):
        for rec in self:
            base = rec.name or _("Draf")
            rec.display_name = f"{base} — {rec.patient_id.name}" if rec.patient_id else base

    def action_sign(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Sertifikat ini sudah ditandatangani atau dibatalkan."))
            if rec.certified_by_id.type not in ("doctor", "dentist"):
                raise UserError(_(
                    "Sertifikat medis penyebab kematian hanya dapat "
                    "ditandatangani dokter."
                ))
            if not rec.underlying_cause_id:
                raise UserError(_("Penyebab dasar kematian belum dapat ditentukan."))
            rec.write({
                "name": rec.name or self.env["ir.sequence"].next_by_code(
                    "hms.death.certificate") or "/",
                "state": "signed",
                "certified_uid": self.env.uid,
                "certified_at": fields.Datetime.now(),
            })
            rec.env["hms.event"].emit("death.certificate.signed", {
                "patient_id": rec.patient_id.id,
                "underlying_cause": rec.underlying_cause_id.code,
                "is_ndr": rec.is_ndr,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if not rec.cancel_reason:
                raise UserError(_("Alasan pembatalan wajib diisi."))
            rec.write({"state": "cancelled"})
        return True

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_(
                "Sertifikat kematian yang sudah bernomor tidak dapat dihapus."
            ))
        return super().unlink()
