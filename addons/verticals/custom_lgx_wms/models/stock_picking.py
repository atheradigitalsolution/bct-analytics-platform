# -*- coding: utf-8 -*-
"""Penerimaan gudang 3PL WAJIB menyebut pemiliknya.

Stok tanpa pemilik di gudang multi-klien adalah stok yang akan tercampur, dan
stok yang sudah tercampur tidak dapat dipisahkan kembali tanpa stock opname
penuh. Karena itu pemeriksaannya berjalan saat validasi picking — titik terakhir
sebelum barang benar-benar tercatat.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    lgx_wms_client_id = fields.Many2one("lgx.wms.client", "Klien Gudang", index=True)
    lgx_job_id = fields.Many2one("lgx.job", "Job Logistik", index=True)
    lgx_is_3pl = fields.Boolean("Operasi 3PL", compute="_compute_is_3pl", store=True)

    @api.depends("lgx_wms_client_id", "owner_id")
    def _compute_is_3pl(self):
        for picking in self:
            picking.lgx_is_3pl = bool(picking.lgx_wms_client_id or picking.owner_id)

    lgx_scan_started = fields.Boolean(
        "Pemindaian Dimulai", copy=False,
        help="Odoo mengisi kuantitas penerimaan secara otomatis dari dokumen. "
             "Pemindaian pertama menolkannya, karena yang dihitung pemindai adalah "
             "apa yang BENAR-BENAR ada di palet — bukan apa yang dijanjikan dokumen.",
    )

    def lgx_begin_scan(self):
        """Nolkan kuantitas isian-otomatis pada pemindaian PERTAMA.

        Tanpa ini, pemindaian menumpuk di atas tebakan sistem: picking dengan
        permintaan 600 yang dipindai 120 tercatat 720. Angka itu lolos validasi
        dan baru ketahuan saat stok fisik tidak cocok — dan pada titik itu tidak
        ada yang tahu mana yang dihitung orang dan mana yang diisi sistem.
        """
        self.ensure_one()
        if self.lgx_scan_started:
            return False
        self.move_line_ids.write({"quantity": 0})
        self.move_ids.write({"picked": False})
        self.lgx_scan_started = True
        return True

    @api.onchange("lgx_wms_client_id")
    def _onchange_lgx_wms_client(self):
        for picking in self:
            if picking.lgx_wms_client_id:
                picking.owner_id = picking.lgx_wms_client_id.owner_partner_id
                picking.lgx_job_id = picking.lgx_wms_client_id.job_id

    def button_validate(self):
        for picking in self:
            if not picking.lgx_wms_client_id:
                continue
            client = picking.lgx_wms_client_id
            if not picking.owner_id:
                raise UserError(_(
                    "Picking %s milik klien gudang %s tetapi tidak menyebut pemilik stok. "
                    "Stok tanpa pemilik di gudang multi-klien akan tercampur, dan stok "
                    "yang sudah tercampur tidak dapat dipisahkan tanpa stock opname penuh.",
                    picking.name, client.name,
                ))
            wrong_category = picking.move_ids.filtered(
                lambda m: m.product_id.categ_id != client.product_category_id
            )
            if wrong_category:
                raise UserError(_(
                    "Produk berikut tidak berada di kategori barang klien '%s': %s.\n\n"
                    "Barang milik klien harus memakai kategori non-valuasi, kalau tidak "
                    "penerimaannya membentuk jurnal dan memasukkan barang orang lain ke "
                    "neraca perusahaan.",
                    client.product_category_id.display_name,
                    ", ".join(wrong_category.mapped("product_id.display_name")[:5]),
                ))
        result = super().button_validate()
        for picking in self.filtered(lambda p: p.lgx_job_id and p.lgx_is_3pl):
            code = "goods_received_wh" if picking.picking_type_id.code == "incoming" else "dispatched_wh"
            picking.lgx_job_id.lgx_log_milestone(code, source="system")
        return result


class StockMove(models.Model):
    _inherit = "stock.move"

    lgx_wms_client_id = fields.Many2one(related="picking_id.lgx_wms_client_id", store=True, index=True)


class StockQuant(models.Model):
    _inherit = "stock.quant"

    lgx_wms_client_id = fields.Many2one(
        "lgx.wms.client", "Klien Gudang", compute="_compute_lgx_client", store=True, index=True,
        help="Diturunkan dari owner_id. Disimpan supaya laporan stok dapat "
             "dikelompokkan per klien tanpa join manual di setiap laporan.",
    )

    @api.depends("owner_id")
    def _compute_lgx_client(self):
        Client = self.env["lgx.wms.client"]
        for quant in self:
            quant.lgx_wms_client_id = (
                Client.search([("owner_partner_id", "=", quant.owner_id.id)], limit=1)
                if quant.owner_id else False
            )
