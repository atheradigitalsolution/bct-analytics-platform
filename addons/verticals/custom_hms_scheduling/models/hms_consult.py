# -*- coding: utf-8 -*-
"""Consultation requests between doctors."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsConsultRequest(models.Model):
    _name = "hms.consult.request"
    _description = "Permintaan Konsul"
    _inherit = ["mail.thread"]
    _order = "requested_at desc"

    encounter_id = fields.Many2one("hms.encounter", required=True, ondelete="cascade", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    from_practitioner_id = fields.Many2one("hms.practitioner", "Dokter Pemohon", required=True,
                                           default=lambda s: s._default_practitioner())
    to_practitioner_id = fields.Many2one("hms.practitioner", "Dokter Tujuan", index=True)
    to_specialty_id = fields.Many2one("hms.specialty", "Spesialisasi Tujuan")
    question = fields.Text("Pertanyaan Klinis", required=True)
    urgency = fields.Selection(
        [("routine", "Rutin"), ("urgent", "Segera"), ("cito", "CITO")],
        default="routine", required=True, tracking=True,
    )
    state = fields.Selection(
        [("requested", "Diminta"), ("accepted", "Diterima"), ("answered", "Dijawab"),
         ("declined", "Ditolak"), ("cancelled", "Dibatalkan")],
        default="requested", required=True, tracking=True, index=True,
    )
    answer_note_id = fields.Many2one("hms.clinical.note", "Jawaban (CPPT)", readonly=True)
    tariff_id = fields.Many2one("hms.tariff", "Tarif Konsul")
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True)
    answered_at = fields.Datetime(readonly=True)
    decline_reason = fields.Char()

    @api.model
    def _default_practitioner(self):
        return self.env["hms.practitioner"].search([("user_id", "=", self.env.uid)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for req in requests:
            req.env["hms.event"].emit("consult.requested", {
                "consult_id": req.id,
                "encounter_id": req.encounter_id.id,
                "to_practitioner_id": req.to_practitioner_id.id,
                "urgency": req.urgency,
                "patient": req.patient_id.name,
            })
        return requests

    def action_accept(self):
        for req in self:
            if req.state != "requested":
                raise UserError(_("Konsul sudah diproses."))
            req.write({"state": "accepted"})
            self.env["hms.care.team"].create({
                "encounter_id": req.encounter_id.id,
                "practitioner_id": req.to_practitioner_id.id,
                "role": "consultant",
                "reason": _("Menerima permintaan konsul #%s") % req.id,
            })
        return True

    def action_answer(self, answer_text):
        """The answer lands in the chart as a signed note, not as a message."""
        self.ensure_one()
        if self.state not in ("requested", "accepted"):
            raise UserError(_("Konsul tidak dalam status yang dapat dijawab."))
        note = self.env["hms.clinical.note"].create({
            "encounter_id": self.encounter_id.id,
            "author_id": self.to_practitioner_id.id,
            "author_role": "doctor",
            "note_type": "consult_answer",
            "subjective": self.question,
            "assessment": answer_text,
        })
        note.action_sign()
        self.write({
            "state": "answered",
            "answer_note_id": note.id,
            "answered_at": fields.Datetime.now(),
        })
        self._charge_consult()
        self.env["hms.event"].emit("consult.answered", {
            "consult_id": self.id, "encounter_id": self.encounter_id.id,
        })
        return note

    def _charge_consult(self):
        """Bill the consultation when a tariff is configured for it."""
        self.ensure_one()
        tariff = self.tariff_id or self.to_practitioner_id.default_consult_tariff_id
        if not tariff or "hms.bill" not in self.env:
            return False
        # System bookkeeping following an authorised clinical act; see
        # custom_hms_billing/models/hms_charge_sources.py for the reasoning.
        bill = self.env["hms.bill"].sudo().get_or_create_for(self.encounter_id)
        if bill.state == "closed":
            return False
        return self.env["hms.bill.line"].sudo().charge(
            bill, tariff, qty=1.0, source=self,
            practitioner=self.to_practitioner_id,
            name=_("Konsul %s") % self.to_practitioner_id.display_name,
        )

    def action_decline(self):
        for req in self:
            if not req.decline_reason:
                raise UserError(_("Alasan penolakan konsul wajib diisi."))
            req.write({"state": "declined"})
        return True
