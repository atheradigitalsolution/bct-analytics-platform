# -*- coding: utf-8 -*-
"""Pemilik barang di gudang 3PL.

Perbedaan fundamental dari gudang biasa: isi gudang BUKAN aset perusahaan. Yang
mengikuti dari situ ada tiga, dan ketiganya hidup di model ini:

1. Setiap penerimaan wajib menyebut pemiliknya. Penerimaan tanpa pemilik adalah
   stok yang akan tercampur, dan stok yang sudah tercampur tidak dapat dipisahkan
   kembali tanpa stock opname penuh.
2. Barang klien memakai kategori produk NON-VALUASI. `owner_id` saja tidak
   mengecualikan quant dari valuasi — ini keputusan 2 di Fase 0, dibuktikan tes
   LGX-E07, bukan diasumsikan.
3. Klien A tidak boleh melihat stok klien B. Ditegakkan record rule, dan diuji
   lewat API maupun UI.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxWmsClient(models.Model):
    _name = "lgx.wms.client"
    _description = "Pemilik Barang Gudang"
    _order = "name"
    _inherit = ["mail.thread"]

    name = fields.Char("Nama", required=True)
    code = fields.Char("Kode", required=True, index=True)
    partner_id = fields.Many2one("res.partner", "Pelanggan", required=True, index=True)
    owner_partner_id = fields.Many2one(
        "res.partner", "Pemilik Stok", required=True,
        help="Partner yang dipakai sebagai owner_id pada quant dan move line. "
             "Biasanya sama dengan pelanggan, tetapi dipisah karena sebagian "
             "kontrak 3PL menyimpan barang milik pihak ketiga atas nama pelanggan.",
    )
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    contract_id = fields.Many2one("lgx.contract", "Kontrak",
                                  domain="[('partner_id','=',partner_id)]")
    job_id = fields.Many2one("lgx.job", "Job Gudang",
                             domain="[('job_type','=','warehouse')]",
                             help="Job tempat biaya penyimpanan dan handling dikumpulkan.")
    warehouse_id = fields.Many2one("stock.warehouse", "Gudang")
    location_ids = fields.Many2many(
        "stock.location", "lgx_wms_client_location_rel", "client_id", "location_id",
        string="Zona yang Dialokasikan",
        help="Kosong berarti klien boleh menempati lokasi mana pun di gudangnya.",
    )
    product_category_id = fields.Many2one(
        "product.category", "Kategori Produk Barang Klien", required=True,
        help="HARUS kategori non-valuasi. Barang milik klien tidak boleh masuk "
             "neraca perusahaan.",
        default=lambda s: s.env.ref("custom_lgx_wms.product_category_client_goods",
                                    raise_if_not_found=False),
    )
    sla_id = fields.Many2one("lgx.wms.sla", "SLA")
    free_days_storage = fields.Integer("Masa Bebas Penyimpanan (hari)")
    minimum_monthly_charge = fields.Monetary("Tagihan Minimum Bulanan", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    portal_user_ids = fields.Many2many(
        "res.users", "lgx_wms_client_user_rel", "client_id", "user_id",
        string="Pengguna Portal Klien",
        help="Pengguna ini hanya boleh melihat stok kliennya sendiri.",
    )
    state = fields.Selection(
        [("draft", "Draf"), ("active", "Aktif"), ("suspended", "Ditangguhkan"),
         ("closed", "Berakhir")],
        string="Status", default="draft", required=True, tracking=True,
    )
    note = fields.Text("Catatan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code, company_id)",
                                   "Kode pemilik barang harus unik per perusahaan.")
    _owner_uniq = models.Constraint("unique(owner_partner_id, company_id)",
                                    "Satu pemilik stok hanya boleh terdaftar sekali per perusahaan.")

    @api.constrains("product_category_id")
    def _check_category_not_valued(self):
        """Kategori barang klien HARUS non-valuasi.

        Ini pemeriksaan yang menutup risiko paling mahal di lapisan gudang:
        barang milik klien yang ikut dinilai sebagai persediaan perusahaan baru
        ketahuan saat tutup buku pertama, dan pada titik itu koreksinya menyentuh
        seluruh periode.
        """
        for client in self:
            category = client.product_category_id
            if not category:
                continue
            valuation = category.with_company(client.company_id).property_valuation
            if valuation == "real_time":
                raise ValidationError(_(
                    "Kategori '%s' memakai valuasi otomatis (real time), jadi menerima "
                    "barang klien ke dalamnya AKAN membentuk jurnal dan memasukkan "
                    "barang orang lain ke neraca perusahaan.\n\n"
                    "Pakai kategori dengan valuasi periodik ('periodic'). owner_id saja tidak "
                    "mengecualikan quant dari valuasi.",
                    category.display_name,
                ))

    @api.onchange("partner_id")
    def _onchange_partner(self):
        for client in self:
            if client.partner_id and not client.owner_partner_id:
                client.owner_partner_id = client.partner_id

    def action_activate(self):
        for client in self:
            if not client.job_id:
                raise ValidationError(_(
                    "Klien gudang %s belum punya job gudang. Tanpa job, biaya penyimpanan "
                    "dan handling tidak punya tempat berkumpul dan tidak akan pernah "
                    "difakturkan.", client.name,
                ))
            client.state = "active"
        return True

    @api.model
    def lgx_find_by_owner(self, owner):
        return self.search([("owner_partner_id", "=", owner.id if hasattr(owner, "id") else owner)],
                           limit=1)
