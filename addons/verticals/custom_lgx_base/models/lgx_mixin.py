# -*- coding: utf-8 -*-
"""Mixin penomoran dokumen LGX.

Spesifikasi melarang memanggil ``ir.sequence`` langsung dari model dokumen.
Alasannya bukan gaya: nomor dokumen logistik harus reset bulanan dan berbeda
per perusahaan, dan itu perilaku yang hidup di ``custom_doc_numbering``
(``ir.sequence.x_monthly_reset``). Memanggil ``next_by_code`` sendiri dari
belasan model berarti belasan tempat yang bisa lupa melakukannya.

Nomor diambil DI DALAM transaksi ``create``, bukan lewat default, sehingga dua
pembuatan paralel serialisasi pada baris sequence alih-alih berlomba ke nomor
yang sama.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxNumberingMixin(models.AbstractModel):
    _name = "lgx.numbering.mixin"
    _description = "Mixin Penomoran Dokumen LGX"

    _lgx_sequence_code = None  # diisi model turunan

    name = fields.Char("Nomor", required=True, copy=False, readonly=True, default="/", index=True)

    def _lgx_next_number(self, sequence_code=None, date=None):
        """Nomor berikutnya dari ir.sequence, sadar perusahaan dan reset bulanan."""
        code = sequence_code or self._lgx_sequence_code
        if not code:
            raise UserError(_("Model %s tidak menyatakan _lgx_sequence_code.", self._name))
        seq = self.env["ir.sequence"].sudo()
        number = seq.with_company(self.env.company).next_by_code(code, sequence_date=date)
        if not number:
            raise UserError(_(
                "Sequence '%s' tidak ditemukan. Modul yang mendefinisikannya "
                "belum terpasang, atau datanya terhapus.", code,
            ))
        return number

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == "/":
                vals["name"] = self._lgx_next_number(date=vals.get("date") or vals.get("etd"))
        return super().create(vals_list)

    def copy_data(self, default=None):
        default = dict(default or {})
        default.setdefault("name", "/")
        return super().copy_data(default)
