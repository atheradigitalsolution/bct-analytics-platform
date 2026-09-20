# -*- coding: utf-8 -*-
"""Issued SEP documents.

A SEP is the guarantee letter the claim is built on. It is kept as its own
record rather than only as a number on the encounter because a claim audit
asks for the document as issued — including the class and the referral it
quoted at the time, which the encounter may have moved on from.
"""
from odoo import api, fields, models


class HmsSep(models.Model):
    _name = "hms.sep"
    _description = "SEP BPJS"
    _order = "issued_at desc, id desc"

    name = fields.Char("Nomor SEP", required=True, index=True)
    encounter_id = fields.Many2one("hms.encounter", required=True, ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    card_no = fields.Char("No. Kartu")
    service_type = fields.Selection(
        [("1", "Rawat Inap"), ("2", "Rawat Jalan")], string="Jenis Pelayanan",
    )
    entitled_class = fields.Char("Hak Kelas")
    treated_class = fields.Char("Kelas Dirawat")
    diagnosis = fields.Char("Diagnosis Awal")
    referral_no = fields.Char("No. Rujukan")
    referral_source = fields.Char("PPK Perujuk")
    poli = fields.Char("Poli Tujuan")
    dpjp_code = fields.Char("Kode DPJP")
    issued_at = fields.Datetime("Terbit", default=fields.Datetime.now)
    cancelled_at = fields.Datetime("Dibatalkan")
    raw_response = fields.Text("Balasan Mentah", readonly=True)
    state = fields.Selection(
        [("issued", "Terbit"), ("cancelled", "Dibatalkan")], default="issued", required=True,
    )

    _name_uniq = models.Constraint("unique(name)", "Nomor SEP harus unik.")

    @api.model
    def record_from_response(self, encounter, sep_no, response):
        """Persist what BPJS actually returned."""
        import json
        return self.create({
            "name": sep_no,
            "encounter_id": encounter.id,
            "card_no": encounter.patient_id.bpjs_no,
            "service_type": "1" if encounter.type == "inpatient" else "2",
            "entitled_class": encounter.patient_id.bpjs_class,
            "poli": encounter.unit_id.bpjs_poli_code,
            "dpjp_code": encounter.practitioner_id.bpjs_doctor_code,
            "referral_no": encounter.referral_id.name,
            "referral_source": encounter.referral_id.source_code,
            "raw_response": json.dumps(response, default=str),
        })
