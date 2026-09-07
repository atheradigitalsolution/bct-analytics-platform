# -*- coding: utf-8 -*-
"""Kategori produk NDI (pasal 5), anak dari :class:`ndi.division`.

Terpisah dari ``product.category`` untuk alasan yang sama seperti
``ndi.division``: ini sumbu komersial ("Sumber Energi", "Sumber Protein Nabati",
"Pakan Komplit Broiler", ...), bukan sumbu valuasi persediaan.
"""

from odoo import api, fields, models


class NdiProductCategory(models.Model):
    _name = "ndi.product.category"
    _description = "NDI Kategori Produk"
    _order = "division_id, sequence, name, id"

    name = fields.Char(required=True, index=True)
    code = fields.Char(index=True)
    division_id = fields.Many2one("ndi.division", string="Divisi", ondelete="restrict", index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    product_count = fields.Integer(compute="_compute_product_count")
    note = fields.Text()

    _name_division_uniq = models.Constraint(
        "UNIQUE (division_id, name)",
        "Nama kategori harus unik dalam satu divisi.",
    )

    @api.depends("name", "division_id")
    def _compute_display_name(self):
        for record in self:
            if record.division_id:
                record.display_name = f"{record.division_id.name} / {record.name}"
            else:
                record.display_name = record.name or ""

    def _compute_product_count(self):
        data = self.env["product.template"]._read_group(
            [("ndi_kategori_id", "in", self.ids)], ["ndi_kategori_id"], ["__count"]
        )
        mapped = {category.id: count for category, count in data}
        for record in self:
            record.product_count = mapped.get(record.id, 0)
