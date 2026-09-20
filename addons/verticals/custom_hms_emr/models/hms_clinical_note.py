# -*- coding: utf-8 -*-
"""CPPT / SOAP notes — append-only once signed."""
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

NOTE_TYPES = [
    ("nurse_initial", "Asesmen Awal Keperawatan"),
    ("medical_initial", "Asesmen Awal Medis"),
    ("soap", "CPPT (SOAP)"),
    ("progress", "Catatan Perkembangan"),
    ("nursing", "Catatan Keperawatan"),
    ("consult_answer", "Jawaban Konsul"),
    ("procedure", "Laporan Tindakan"),
    ("discharge", "Catatan Pemulangan"),
]

# Fields a signed note may still change. Everything else is frozen.
MUTABLE_AFTER_SIGNING = {
    "is_current", "revised_by_id", "message_follower_ids", "message_ids",
    "activity_ids", "write_date", "write_uid",
}


class HmsClinicalNote(models.Model):
    _name = "hms.clinical.note"
    _description = "Catatan Klinis (CPPT)"
    _inherit = ["mail.thread", "hms.audited"]
    _order = "noted_at desc, id desc"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    note_type = fields.Selection(NOTE_TYPES, required=True, default="soap", index=True)
    author_id = fields.Many2one("hms.practitioner", "Penulis", required=True,
                                default=lambda s: s._default_author())
    author_role = fields.Selection(
        [("doctor", "Dokter"), ("nurse", "Perawat"), ("pharmacist", "Apoteker"),
         ("nutritionist", "Ahli Gizi"), ("other", "Lainnya")],
        default="doctor", required=True,
    )
    noted_at = fields.Datetime("Waktu Catatan", required=True, default=fields.Datetime.now, index=True)

    subjective = fields.Text("S — Subjektif")
    objective = fields.Text("O — Objektif")
    assessment = fields.Text("A — Asesmen")
    plan = fields.Text("P — Perencanaan")
    instruction = fields.Text(
        "Instruksi", help="Instruksi untuk perawat. custom_hms_nursing mengubahnya menjadi tugas."
    )

    signed = fields.Boolean("Ditandatangani", readonly=True, copy=False, index=True)
    signed_at = fields.Datetime("Waktu Tanda Tangan", readonly=True, copy=False)
    signed_by_id = fields.Many2one("res.users", "Ditandatangani Oleh", readonly=True, copy=False)
    signature_hash = fields.Char("Hash Tanda Tangan", readonly=True, copy=False)

    revises_id = fields.Many2one("hms.clinical.note", "Merevisi", readonly=True, copy=False,
                                 ondelete="restrict")
    revised_by_id = fields.Many2one("hms.clinical.note", "Direvisi Oleh", readonly=True, copy=False)
    revision_reason = fields.Char("Alasan Revisi")
    is_current = fields.Boolean("Versi Berlaku", default=True, readonly=True, index=True)

    requires_cosign = fields.Boolean(
        "Perlu Co-Sign DPJP",
        help="Catatan residen/dokter jaga baru final setelah DPJP ikut menandatangani.",
    )
    cosigned_by_id = fields.Many2one("hms.practitioner", "Co-Sign Oleh", readonly=True)
    cosigned_at = fields.Datetime("Waktu Co-Sign", readonly=True)

    _current_idx = models.Index("(encounter_id, is_current) WHERE is_current IS TRUE")

    @api.model
    def _default_author(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    @api.constrains("subjective", "objective", "assessment", "plan", "note_type")
    def _check_has_content(self):
        for rec in self:
            if not any((rec.subjective, rec.objective, rec.assessment, rec.plan)):
                raise ValidationError(_("Catatan klinis tidak boleh kosong seluruhnya."))

    # --- the append-only guarantee ---------------------------------------
    def _compute_signature_hash(self):
        """SHA-256 over content + author + timestamp.

        Recomputable by anyone holding the record, so a mismatch is evidence
        of tampering that does not depend on trusting the application log.
        """
        self.ensure_one()
        material = "|".join([
            str(self.id), self.encounter_id.name or "", self.note_type or "",
            str(self.author_id.id), fields.Datetime.to_string(self.noted_at) or "",
            self.subjective or "", self.objective or "", self.assessment or "",
            self.plan or "", self.instruction or "",
        ])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def action_sign(self):
        for note in self:
            if note.signed:
                raise UserError(_("Catatan sudah ditandatangani."))
            if not note.author_id:
                raise UserError(_("Catatan tanpa penulis tidak dapat ditandatangani."))
            note.write({
                "signed": True,
                "signed_at": fields.Datetime.now(),
                "signed_by_id": self.env.uid,
            })
            # Hash last: it must cover the signing timestamp too.
            note.sudo().write({"signature_hash": note._compute_signature_hash()})
            note.env["hms.event"].emit("note.signed", {
                "note_id": note.id, "encounter_id": note.encounter_id.id,
                "type": note.note_type,
            })
        return True

    def verify_signature(self):
        """True when the stored hash still matches the content."""
        self.ensure_one()
        if not self.signed:
            return False
        return self.signature_hash == self._compute_signature_hash()

    def write(self, vals):
        signed = self.filtered("signed")
        if signed:
            # The signing write itself sets these, so they are allowed through;
            # `signed` is only True for records that were already signed before
            # this call.
            forbidden = set(vals) - MUTABLE_AFTER_SIGNING - {
                "signature_hash", "cosigned_by_id", "cosigned_at",
            }
            if forbidden:
                raise UserError(
                    _("Catatan klinis %(n)s sudah ditandatangani dan tidak dapat diubah "
                      "(%(f)s). Buat revisi lewat tombol Revisi — versi lama tetap tersimpan.")
                    % {"n": ", ".join(str(n.id) for n in signed), "f": ", ".join(sorted(forbidden))}
                )
        return super().write(vals)

    def unlink(self):
        if any(note.signed for note in self):
            raise UserError(
                _("Catatan klinis yang sudah ditandatangani tidak dapat dihapus.")
            )
        return super().unlink()

    def action_revise(self, reason=None):
        """Create the successor version and retire this one."""
        self.ensure_one()
        if not self.signed:
            raise UserError(_("Catatan yang belum ditandatangani cukup diubah langsung."))
        if self.revised_by_id:
            raise UserError(
                _("Catatan ini sudah direvisi oleh catatan #%s.") % self.revised_by_id.id
            )
        new = self.copy({
            "revises_id": self.id,
            "revision_reason": reason or self.env.context.get("hms_revision_reason"),
            "noted_at": fields.Datetime.now(),
            "signed": False,
            "signed_at": False,
            "signed_by_id": False,
            "signature_hash": False,
            "is_current": True,
        })
        # sudo() because is_current/revised_by_id are the only mutations the
        # append-only guard permits, and the guard is enforced in write().
        self.sudo().write({"is_current": False, "revised_by_id": new.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": new.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_cosign(self):
        practitioner = self._default_author()
        for note in self:
            if not note.requires_cosign:
                raise UserError(_("Catatan ini tidak memerlukan co-sign."))
            if not practitioner or practitioner != note.encounter_id.practitioner_id:
                raise UserError(_("Hanya DPJP kunjungan ini yang dapat memberi co-sign."))
            note.sudo().write({
                "cosigned_by_id": practitioner.id, "cosigned_at": fields.Datetime.now(),
            })
        return True

    @api.model
    def _hms_merge_patient(self, source, target):
        # Notes follow their encounter, which is re-pointed by hms.encounter.
        return True
