# -*- coding: utf-8 -*-
"""Pertanyaan koder kepada DPJP.

=============================================================================
KEPUTUSAN: PERTANYAAN ADALAH REKAM, JAWABANNYA ADALAH REKAM — BUKAN CHAT
=============================================================================

Dalam praktik, pertanyaan koder ("dokumentasinya menyebut sepsis, tapi tidak
ada kultur — apakah dimaksudkan sebagai diagnosis definitif?") disampaikan
lewat WhatsApp atau ditempel di berkas. Jawabannya hilang, dan enam bulan
kemudian ketika klaim dipending, tidak ada yang bisa membuktikan bahwa koder
pernah bertanya dan dokter pernah menjawab.

Model ini menyimpan keduanya, dan ``hms.claim.action_code_done`` **menolak**
menyelesaikan koding selama masih ada pertanyaan terbuka. Pertanyaan yang
boleh diabaikan bukan pertanyaan; ia hanya menunda kesalahan yang sama.

Yang sengaja TIDAK dilakukan: jawaban DPJP tidak otomatis mengubah kode.
Koder yang memutuskan, dan keputusannya tetap harus lewat ``change_reason``
seperti biasa. Otomatisasi di titik ini akan membuat jawaban singkat "iya"
mengubah diagnosis utama sebuah klaim tanpa ada manusia yang membacanya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsCodingQuery(models.Model):
    _name = "hms.coding.query"
    _description = "Pertanyaan Koder ke DPJP"
    _order = "asked_at desc, id desc"

    name = fields.Char("Nomor", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    claim_id = fields.Many2one("hms.claim", "Klaim", required=True,
                               ondelete="cascade", index=True)
    encounter_id = fields.Many2one(related="claim_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="claim_id.patient_id", store=True, index=True)

    topic = fields.Selection(
        [("specificity", "Kode kurang spesifik"),
         ("conflict", "Dokumentasi saling bertentangan"),
         ("definitive", "Diagnosis kerja vs definitif"),
         ("missing_support", "Diagnosis tanpa dukungan penunjang"),
         ("procedure", "Tindakan tidak terdokumentasi"),
         ("other", "Lainnya")],
        string="Pokok Pertanyaan", required=True, default="specificity",
    )
    question = fields.Text("Pertanyaan", required=True)
    asked_by_id = fields.Many2one("res.users", "Ditanyakan Oleh", readonly=True,
                                  default=lambda s: s.env.user)
    asked_at = fields.Datetime("Waktu Bertanya", readonly=True,
                               default=fields.Datetime.now, index=True)
    addressed_to_id = fields.Many2one("hms.practitioner", "Ditujukan Kepada",
                                      required=True, index=True)

    state = fields.Selection(
        [("open", "Menunggu Jawaban"), ("answered", "Dijawab"),
         ("closed", "Selesai"), ("withdrawn", "Ditarik")],
        default="open", required=True, index=True,
    )
    answer = fields.Text("Jawaban DPJP")
    answered_by_id = fields.Many2one("res.users", "Dijawab Oleh", readonly=True, copy=False)
    answered_at = fields.Datetime("Waktu Dijawab", readonly=True, copy=False)
    outcome = fields.Selection(
        [("code_changed", "Kode diubah mengikuti jawaban"),
         ("code_kept", "Kode tetap"),
         ("documentation_added", "Dokumentasi dilengkapi DPJP")],
        string="Tindak Lanjut",
    )
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor pertanyaan koder harus unik.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hms.coding.query") or "/"
        return super().create(vals_list)

    @api.depends("name", "topic")
    def _compute_display_name(self):
        topics = dict(self._fields["topic"].selection)
        for rec in self:
            rec.display_name = f"{rec.name} — {topics.get(rec.topic, '')}"

    def action_answer(self):
        for rec in self:
            if rec.state != "open":
                raise UserError(_("Pertanyaan %s tidak lagi menunggu jawaban.") % rec.name)
            if not (rec.answer or "").strip():
                raise UserError(_("Isi jawaban wajib diisi."))
            rec.write({
                "state": "answered",
                "answered_by_id": self.env.uid,
                "answered_at": fields.Datetime.now(),
            })
        return True

    def action_close(self):
        """Ditutup koder setelah jawaban dibaca dan ditindaklanjuti."""
        for rec in self:
            if rec.state != "answered":
                raise UserError(_(
                    "Pertanyaan hanya dapat ditutup setelah dijawab. Bila "
                    "pertanyaan ini keliru, tariklah — jangan tutup seolah "
                    "sudah dijawab."
                ))
            if not rec.outcome:
                raise UserError(_(
                    "Tindak lanjut wajib dipilih: jawaban DPJP yang tidak "
                    "pernah dinyatakan mengubah apa pun tidak bisa dibedakan "
                    "dari jawaban yang diabaikan."
                ))
            rec.write({"state": "closed"})
        return True

    def action_withdraw(self):
        for rec in self:
            if rec.state == "closed":
                raise UserError(_("Pertanyaan yang sudah selesai tidak dapat ditarik."))
            rec.write({"state": "withdrawn"})
        return True

    def unlink(self):
        if any(rec.state != "open" for rec in self):
            raise UserError(_(
                "Pertanyaan yang sudah dijawab atau ditutup tidak dapat dihapus."
            ))
        return super().unlink()
