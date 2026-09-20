# -*- coding: utf-8 -*-
"""Service units (poli, IGD, penunjang) and care classes.

`hms.unit` is the axis everything else reports along: queues belong to a unit,
charges are credited to the unit that delivered the service, and the P&L module
hangs one analytic account off each unit. Getting a service delivered under the
wrong unit is not a cosmetic error — it silently moves revenue between cost
centres.
"""
from odoo import api, fields, models


class HmsCareClass(models.Model):
    _name = "hms.care.class"
    _description = "Kelas Perawatan"
    _order = "sequence, id"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10, help="Urutan dari kelas tertinggi ke terendah.")
    rank = fields.Integer(
        "Peringkat", default=0,
        help="Angka lebih besar berarti kelas lebih tinggi. Dipakai untuk "
             "menentukan naik/turun kelas dan selisih tarif.",
    )
    is_intensive = fields.Boolean("Perawatan intensif")
    jkn_class_code = fields.Char(
        "Kode Kelas JKN",
        help="Kode kelas yang dikirim ke BPJS (SEP/E-Klaim) untuk kelas perawatan "
             "ini. Dibuat parametrik karena KRIS (Kelas Rawat Inap Standar) masih "
             "dalam masa transisi: pemetaan kelas 1/2/3 ke kode JKN dapat berubah "
             "tanpa perubahan kode program.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode kelas perawatan harus unik.",
    )


class HmsUnit(models.Model):
    _name = "hms.unit"
    _description = "Unit Layanan"
    _inherit = ["mail.thread"]
    _order = "sequence, code"

    code = fields.Char(required=True, tracking=True)
    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    type = fields.Selection(
        [("outpatient_clinic", "Poliklinik"), ("emergency", "IGD"),
         ("inpatient", "Rawat Inap"), ("ok", "Kamar Operasi"), ("icu", "Intensif"),
         ("lab", "Laboratorium"), ("radiology", "Radiologi"), ("pharmacy", "Farmasi"),
         ("rehab", "Rehabilitasi"), ("hemodialysis", "Hemodialisa"), ("mcu", "MCU"),
         ("admin", "Administrasi"), ("support", "Penunjang Lain")],
        required=True, default="outpatient_clinic", tracking=True,
    )
    specialty_id = fields.Many2one("hms.specialty", "Spesialisasi")
    bpjs_poli_code = fields.Char("Kode Poli BPJS")
    ihs_location_id = fields.Char("ID Lokasi SATUSEHAT")
    building = fields.Char("Gedung")
    floor = fields.Char("Lantai")
    phone_ext = fields.Char("Ekstensi Telepon")
    head_id = fields.Many2one("hms.practitioner", "Kepala Unit")
    practitioner_ids = fields.Many2many(
        "hms.practitioner", "hms_unit_practitioner_rel", "unit_id", "practitioner_id",
        string="Praktisi",
    )
    default_consult_tariff_id = fields.Many2one(
        "hms.tariff", "Tarif Konsultasi Default",
        domain="[('category_id.code', '=', 'CONSULT')]",
    )
    operating_hours = fields.Text(
        "Jam Operasional",
        help="JSON per hari, mis. {\"mon\": [\"08:00\", \"14:00\"]}. Informasional; "
             "kuota sebenarnya berasal dari jadwal praktik dokter.",
    )
    queue_mode = fields.Selection(
        [("per_unit", "Satu antrian per unit"), ("per_practitioner", "Antrian per dokter")],
        default="per_unit", required=True,
    )
    requires_referral = fields.Boolean("Wajib rujukan")
    is_revenue_unit = fields.Boolean(
        "Unit penghasil pendapatan", default=True,
        help="Unit non-pendapatan (manajemen, IT, laundry) menjadi pool overhead di P&L.",
    )
    area_m2 = fields.Float("Luas (m²)", help="Driver alokasi overhead berbasis luas.")
    color = fields.Integer("Warna")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode unit harus unik.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"
