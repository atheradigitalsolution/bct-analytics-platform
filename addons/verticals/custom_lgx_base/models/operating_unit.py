# -*- coding: utf-8 -*-
"""Cabang = operating.unit, plus identitas pajaknya.

Keputusan A24 di spesifikasi menanyakan: cabang sebagai ``res.company`` atau
model ``lgx.branch`` sendiri? Jawabannya di repo ini adalah tidak keduanya.
``custom_operating_unit`` sudah menstempel ``operating_unit_id`` pada
``account.move``, ``sale.order`` dan ``stock.picking``, lengkap dengan record
rule dan klaim JWT ``allowed_ou``. Dimensi cabang pada jurnal — bagian yang
membuat opsi ``lgx.branch`` mahal — karenanya sudah ada.

Yang belum ada, dan ditambahkan di sini, adalah identitas pajak per cabang:
NITKU 22 digit yang menggantikan NPWP cabang sejak Coretax, NPWP 16 digit
(bukan 15), kantor pabean pengampu, dan KBLI dua versi selama masa transisi
KBLI 2020 -> 2025.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OperatingUnit(models.Model):
    _inherit = "operating.unit"

    lgx_nitku = fields.Char(
        "NITKU", size=22,
        help="22 digit: 16 digit NPWP/NIK + 6 digit urut TKU. Faktur pajak dan "
             "bukti potong cabang ini harus mereferensikannya.",
    )
    lgx_npwp = fields.Char("NPWP", size=16, help="16 digit sejak Coretax, bukan 15.")
    lgx_customs_office_id = fields.Many2one("lgx.customs.office", "Kantor Pabean Pengampu")
    lgx_address_id = fields.Many2one("res.partner", "Alamat Cabang")
    lgx_kbli_2020 = fields.Char("KBLI 2020", size=5)
    lgx_kbli_2025 = fields.Char("KBLI 2025", size=5)
    lgx_is_logistics_branch = fields.Boolean(
        "Cabang Logistik", default=False,
        help="Menandai unit yang benar-benar menjalankan operasi logistik, "
             "supaya unit administratif tidak ikut muncul di pemilihan job.",
    )

    @api.constrains("lgx_nitku")
    def _check_lgx_nitku(self):
        for rec in self:
            if rec.lgx_nitku and (not rec.lgx_nitku.isdigit() or len(rec.lgx_nitku) != 22):
                raise ValidationError(_("NITKU harus 22 digit angka. Nilai: %s", rec.lgx_nitku))

    @api.constrains("lgx_npwp")
    def _check_lgx_npwp(self):
        for rec in self:
            if rec.lgx_npwp and (not rec.lgx_npwp.isdigit() or len(rec.lgx_npwp) != 16):
                raise ValidationError(_(
                    "NPWP harus 16 digit angka sejak Coretax (bukan 15). Nilai: %s", rec.lgx_npwp,
                ))
