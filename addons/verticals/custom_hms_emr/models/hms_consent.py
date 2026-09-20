# -*- coding: utf-8 -*-
"""General and procedure-specific consent."""
from odoo import _, fields, models
from odoo.exceptions import UserError


class HmsConsentTemplate(models.Model):
    _name = "hms.consent.template"
    _description = "Template Persetujuan"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    type = fields.Selection(
        [("general", "Persetujuan Umum"), ("procedure", "Informed Consent Tindakan"),
         ("anesthesia", "Persetujuan Anestesi"), ("refusal", "Penolakan Tindakan"),
         ("dnr", "Do Not Resuscitate"), ("data", "Persetujuan Pengolahan Data")],
        required=True, default="procedure",
    )
    body = fields.Html("Isi", sanitize=False)
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode template persetujuan harus unik.")


class HmsConsent(models.Model):
    _name = "hms.consent"
    _description = "Persetujuan Pasien"
    _inherit = ["hms.audited"]
    _order = "signed_at desc, id desc"

    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", ondelete="cascade", index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, index=True,
                                 ondelete="restrict")
    template_id = fields.Many2one("hms.consent.template", "Template", required=True)
    type = fields.Selection(related="template_id.type", store=True)
    body_snapshot = fields.Html(
        "Isi Saat Ditandatangani", readonly=True,
        help="Salinan teks persetujuan pada saat penandatanganan. Template boleh "
             "berubah kemudian; yang mengikat adalah teks yang benar-benar dibaca pasien.",
    )
    tariff_id = fields.Many2one("hms.tariff", "Tindakan")
    explained_by_id = fields.Many2one("hms.practitioner", "Dijelaskan Oleh")
    signer_type = fields.Selection(
        [("patient", "Pasien Sendiri"), ("guardian", "Wali/Keluarga"),
         ("witness_only", "Saksi (pasien tidak mampu)")],
        default="patient", required=True,
    )
    signer_name = fields.Char("Nama Penanda Tangan")
    signer_relation = fields.Char("Hubungan")
    signer_identity_no = fields.Char("No. Identitas Penanda Tangan")
    witness_name = fields.Char("Saksi")
    state = fields.Selection(
        [("draft", "Draf"), ("signed", "Ditandatangani"), ("refused", "Ditolak"),
         ("withdrawn", "Dicabut")],
        default="draft", required=True,
    )
    signed_at = fields.Datetime("Waktu Tanda Tangan", readonly=True)
    signature = fields.Binary("Tanda Tangan", attachment=True)
    refusal_reason = fields.Text("Alasan Penolakan")

    def action_sign(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Persetujuan sudah diproses."))
            if not rec.signer_name:
                raise UserError(_("Nama penanda tangan wajib diisi."))
            rec.write({
                "state": "signed",
                "signed_at": fields.Datetime.now(),
                "body_snapshot": rec.template_id.body,
            })
        return True

    def action_refuse(self):
        for rec in self:
            if not rec.refusal_reason:
                raise UserError(_("Alasan penolakan wajib dicatat."))
            rec.write({"state": "refused", "signed_at": fields.Datetime.now()})
        return True

    def action_withdraw(self):
        self.write({"state": "withdrawn"})
        return True
