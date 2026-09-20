# -*- coding: utf-8 -*-
"""Surat keterangan medis bernomor dengan penandatangan.

=============================================================================
KEPUTUSAN: NOMOR DITERBITKAN SAAT DITANDATANGANI, BUKAN SAAT DIBUAT
=============================================================================

Surat keterangan adalah dokumen hukum yang dipakai di luar rumah sakit:
keterangan sakit untuk atasan, keterangan sehat untuk melamar kerja,
keterangan kelahiran untuk akta. Nomornya adalah janji bahwa surat itu
benar-benar terbit dari rumah sakit ini.

Kalau nomor diterbitkan saat draf dibuat, setiap draf yang dibatalkan
meninggalkan lubang di deret nomor — dan deret bernomor yang berlubang tidak
bisa dipakai membuktikan apa pun, karena tidak ada cara membedakan "nomor 47
tidak pernah ada" dari "nomor 47 hilang dari arsip". Jadi draf tidak bernomor;
``action_sign`` yang menerbitkannya.

Konsekuensi yang diterima: dua petugas yang menandatangani bersamaan
mendapat nomor berurutan sesuai urutan commit, bukan sesuai urutan mereka
membuka layar. Itu benar.

=============================================================================
KEPUTUSAN: PENANDATANGAN ADALAH PRAKTISI, PENGESAH ADALAH PENGGUNA
=============================================================================

``signed_by_id`` menunjuk ``hms.practitioner`` — yang bertanggung jawab secara
profesional adalah dokternya, lengkap dengan SIP-nya, bukan akun yang kebetulan
menekan tombol. ``signed_uid`` menyimpan akunnya secara terpisah supaya
keduanya bisa dibandingkan saat ada dugaan surat ditandatangani orang lain.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

LETTER_TYPES = [
    ("sick_leave", "Surat Keterangan Sakit / Istirahat"),
    ("fit", "Surat Keterangan Sehat"),
    ("birth", "Surat Keterangan Kelahiran"),
    ("hospitalization", "Surat Keterangan Rawat Inap"),
    ("referral_support", "Surat Pengantar / Keterangan Rujukan"),
    ("visum", "Visum et Repertum"),
    ("other", "Surat Keterangan Lain"),
]


class HmsMedicalLetter(models.Model):
    _name = "hms.medical.letter"
    _description = "Surat Keterangan Medis"
    _order = "issued_at desc, id desc"

    name = fields.Char("Nomor Surat", readonly=True, copy=False, index=True,
                       help="Diterbitkan saat surat ditandatangani. Draf sengaja "
                            "tidak bernomor supaya deret nomor tidak berlubang.")
    type = fields.Selection(LETTER_TYPES, "Jenis Surat", required=True,
                            default="sick_leave", index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True,
                                 ondelete="restrict", index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="restrict", index=True,
                                   domain="[('patient_id', '=', patient_id)]")
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter Penandatangan", required=True)
    purpose = fields.Char("Untuk Keperluan")
    body = fields.Text("Isi Keterangan", required=True)

    # Khusus keterangan sakit / istirahat.
    rest_from = fields.Date("Istirahat Mulai")
    rest_to = fields.Date("Istirahat Sampai")
    rest_days = fields.Integer("Lama Istirahat (hari)", compute="_compute_rest_days", store=True)

    issued_at = fields.Datetime("Waktu Terbit", readonly=True, copy=False, index=True)
    valid_until = fields.Date("Berlaku Sampai")
    state = fields.Selection(
        [("draft", "Draf"), ("signed", "Ditandatangani"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    signed_by_id = fields.Many2one("hms.practitioner", "Ditandatangani Oleh", readonly=True,
                                   copy=False)
    signed_uid = fields.Many2one("res.users", "Akun Penanda Tangan", readonly=True, copy=False)
    signed_at = fields.Datetime("Waktu Tanda Tangan", readonly=True, copy=False)
    cancel_reason = fields.Char("Alasan Pembatalan")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor surat keterangan harus unik.")

    @api.depends("rest_from", "rest_to")
    def _compute_rest_days(self):
        for rec in self:
            if rec.rest_from and rec.rest_to:
                rec.rest_days = (rec.rest_to - rec.rest_from).days + 1
            else:
                rec.rest_days = 0

    @api.constrains("rest_from", "rest_to")
    def _check_rest_range(self):
        for rec in self:
            if rec.rest_from and rec.rest_to and rec.rest_to < rec.rest_from:
                raise ValidationError(_(
                    "Tanggal akhir istirahat tidak boleh sebelum tanggal mulai."
                ))

    @api.constrains("encounter_id", "patient_id")
    def _check_encounter_matches_patient(self):
        for rec in self:
            if rec.encounter_id and rec.encounter_id.patient_id != rec.patient_id:
                raise ValidationError(_("Kunjungan yang dipilih milik pasien lain."))

    @api.depends("name", "type", "patient_id")
    def _compute_display_name(self):
        labels = dict(LETTER_TYPES)
        for rec in self:
            title = labels.get(rec.type, "")
            rec.display_name = f"{rec.name} — {title}" if rec.name else _("%s (draf)") % title

    def action_sign(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Surat ini sudah ditandatangani atau dibatalkan."))
            if rec.type == "sick_leave" and rec.rest_days <= 0:
                raise UserError(_(
                    "Surat keterangan sakit harus menyebut rentang istirahat. "
                    "Tanpa tanggal, surat ini tidak bisa dipakai pemegangnya."
                ))
            practitioner = rec.practitioner_id
            # Kewenangan profesi, bukan kewenangan aplikasi: surat keterangan
            # medis adalah pernyataan klinis atas nama seorang dokter. Perawat
            # atau apoteker yang punya akses layar tetap tidak boleh menjadi
            # penandatangannya.
            if practitioner.type not in ("doctor", "dentist"):
                raise UserError(_(
                    "%s bukan dokter, sehingga tidak berwenang menandatangani "
                    "surat keterangan medis."
                ) % practitioner.display_name)
            rec.write({
                "name": rec.name or self.env["ir.sequence"].next_by_code(
                    "hms.medical.letter") or "/",
                "state": "signed",
                "signed_by_id": practitioner.id,
                "signed_uid": self.env.uid,
                "signed_at": fields.Datetime.now(),
                "issued_at": fields.Datetime.now(),
            })
        return True

    def action_cancel(self):
        for rec in self:
            if not rec.cancel_reason:
                raise UserError(_(
                    "Alasan pembatalan wajib diisi: surat yang sudah keluar "
                    "mungkin sudah dipegang orang lain."
                ))
            rec.write({"state": "cancelled"})
        return True

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_(
                "Surat yang sudah bernomor tidak dapat dihapus. Batalkan surat "
                "agar nomornya tetap terpakai dan deretnya tidak berlubang."
            ))
        return super().unlink()
