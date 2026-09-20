# -*- coding: utf-8 -*-
"""Kontrak pelanggan — tarif dan syarat yang mengikat lebih dulu dari rate card umum.

Job yang dibuat untuk pelanggan berkontrak mengambil tarif dari sini sebelum
jatuh ke rate card umum. Urutannya begitu dan bukan sebaliknya, karena kontrak
adalah janji tertulis: rate card umum yang naik tidak boleh diam-diam menaikkan
harga pelanggan yang tarifnya sudah dikunci.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxContract(models.Model):
    _name = "lgx.contract"
    _description = "Kontrak Pelanggan Logistik"
    _order = "valid_from desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread"]
    _lgx_sequence_code = "lgx.contract"

    partner_id = fields.Many2one("res.partner", "Pelanggan", required=True, index=True, tracking=True)
    title = fields.Char("Judul", required=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    rate_card_ids = fields.Many2many(
        "lgx.rate.card", "lgx_contract_rate_card_rel", "contract_id", "rate_card_id",
        string="Rate Card Kontrak",
        help="Hanya rate card arah 'jual'. Tarif di sini dipakai lebih dulu "
             "sebelum rate card umum.",
    )
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today)
    valid_to = fields.Date("Berlaku Sampai")
    payment_term_id = fields.Many2one("account.payment.term", "Termin Pembayaran")
    credit_limit = fields.Monetary("Batas Kredit", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    free_days_demurrage = fields.Integer("Masa Bebas Demurrage (hari)")
    free_days_detention = fields.Integer("Masa Bebas Detensi (hari)")
    free_days_storage = fields.Integer("Masa Bebas Penyimpanan Gudang (hari)")
    volume_commitment = fields.Float("Komitmen Volume",
                                     help="Satuan mengikuti kesepakatan: TEU, ton, atau pallet per periode.")
    volume_commitment_uom = fields.Char("Satuan Komitmen")
    minimum_monthly_charge = fields.Monetary("Tagihan Minimum Bulanan", currency_field="currency_id")
    document_ids = fields.Many2many("ir.attachment", string="Dokumen Kontrak")
    requires_stamp_duty = fields.Boolean(
        "Perlu Meterai", default=True,
        help="Kontrak jasa logistik adalah objek bea meterai; konosemen dan surat "
             "angkutan barang tidak (UU 10/2020 Pasal 7).",
    )
    sla_note = fields.Text("Ringkasan SLA")
    state = fields.Selection(
        [("draft", "Draf"), ("active", "Aktif"), ("expired", "Berakhir"), ("terminated", "Diputus")],
        string="Status", default="draft", required=True, tracking=True,
    )
    note = fields.Text("Catatan")

    _valid_period = models.Constraint(
        "check(valid_to is null or valid_to >= valid_from)",
        "Tanggal 'berlaku sampai' tidak boleh lebih awal dari 'berlaku dari'.",
    )

    @api.constrains("rate_card_ids")
    def _check_rate_card_direction(self):
        for contract in self:
            wrong = contract.rate_card_ids.filtered(lambda c: c.direction != "sell")
            if wrong:
                raise ValidationError(_(
                    "Kontrak pelanggan hanya boleh memuat rate card arah 'jual'. "
                    "Rate card beli %s adalah harga dari carrier, bukan janji ke pelanggan.",
                    ", ".join(wrong.mapped("name")),
                ))

    def action_activate(self):
        self.write({"state": "active"})
        return True

    def action_terminate(self):
        self.write({"state": "terminated"})
        return True

    @api.model
    def lgx_find_active(self, partner, on_date=None):
        on_date = on_date or fields.Date.context_today(self)
        return self.search([
            ("partner_id", "=", partner.id),
            ("state", "=", "active"),
            ("valid_from", "<=", on_date),
            "|", ("valid_to", "=", False), ("valid_to", ">=", on_date),
        ], limit=1)
