# -*- coding: utf-8 -*-
"""Incoming referral letters (rujukan)."""
from odoo import fields, models


class HmsReferral(models.Model):
    _name = "hms.referral"
    _description = "Rujukan Masuk"
    _order = "referral_date desc"

    name = fields.Char("Nomor Rujukan", required=True, index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, ondelete="cascade")
    source_type = fields.Selection(
        [("fktp", "FKTP (Puskesmas/Klinik/DPP)"), ("hospital", "Rumah Sakit"),
         ("internal", "Internal"), ("other", "Lainnya")],
        required=True, default="fktp",
    )
    source_name = fields.Char("Asal Perujuk", required=True)
    source_code = fields.Char("Kode PPK Perujuk")
    referral_date = fields.Date("Tanggal Rujukan", required=True,
                                default=lambda s: fields.Date.context_today(s))
    valid_until = fields.Date("Berlaku Sampai")
    diagnosis_text = fields.Char("Diagnosis Rujukan")
    diagnosis_icd10_id = fields.Many2one("hms.icd10", "Diagnosis (ICD-10)")
    to_unit_id = fields.Many2one("hms.unit", "Tujuan Poli")
    to_practitioner_id = fields.Many2one("hms.practitioner", "Tujuan Dokter")
    note = fields.Text()
    document = fields.Binary("Berkas Rujukan", attachment=True)
    document_name = fields.Char()
