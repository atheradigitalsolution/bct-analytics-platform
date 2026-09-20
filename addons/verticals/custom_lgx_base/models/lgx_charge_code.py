# -*- coding: utf-8 -*-
"""Master item tagih — tempat pengetahuan pajak disimpan sekali.

Setiap baris pendapatan dan biaya pada sebuah job menunjuk ke satu kode charge,
dan mewarisi empat keputusan pajak darinya:

* ``default_nature``    jasa sendiri atau talangan pihak ketiga. Menentukan
                        apakah baris masuk dasar pemotongan PPh 23 (PMK
                        141/2015: jumlah bruto tidak termasuk reimbursement
                        yang dapat dibuktikan) dan apakah bukti pihak ketiga
                        wajib dilampirkan sebelum difakturkan.
* ``is_freight_charge`` menandai baris sebagai biaya transportasi. Syarat
                        penerapan PPN besaran tertentu untuk JPT adalah adanya
                        freight charges di dalam tagihan.
* ``vat_treatment``     kuncinya sengaja netral terhadap angka. Tarif hidup di
                        ``account.tax``, bukan di nama kunci, supaya perubahan
                        tarif tidak menjadi migrasi nilai selection.
* ``default_wht_type``  PPh 23 atau PPh 15; tarif dan sifat final berasal dari
                        master pajak, bukan dari kunci ini.

``product_id`` wajib karena ``account.move.line`` membutuhkannya. Tanpa produk,
baris charge tidak punya jalan ke akuntansi.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

VAT_TREATMENTS = [
    ("standard", "PPN normal"),
    ("besaran_tertentu", "PPN besaran tertentu (JPT)"),
    ("exempt_public_transport", "Dibebaskan — angkutan umum"),
    ("export_service_zero", "Ekspor jasa 0%"),
    ("not_collected", "Tidak dipungut"),
    ("out_of_scope", "Di luar objek PPN"),
]

WHT_TYPES = [
    ("none", "Tidak dipotong"),
    ("pph23", "PPh 23"),
    ("pph15_sea", "PPh 15 — pelayaran dalam negeri"),
    ("pph15_air", "PPh 15 — penerbangan dalam negeri"),
    ("pph15_foreign", "PPh 15 — pelayaran/penerbangan luar negeri"),
]

CHARGE_NATURES = [
    ("service", "Jasa sendiri"),
    ("disbursement", "Talangan pihak ketiga"),
]


class LgxChargeCode(models.Model):
    _name = "lgx.charge.code"
    _description = "Kode Charge"
    _order = "category, code"

    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama", required=True, translate=True)
    category = fields.Selection(
        [
            ("freight", "Freight"),
            ("thc", "Terminal Handling"),
            ("documentation", "Dokumentasi"),
            ("handling", "Handling"),
            ("customs", "Kepabeanan"),
            ("trucking", "Trucking"),
            ("storage", "Penyimpanan"),
            ("demurrage", "Demurrage"),
            ("detention", "Detensi"),
            ("insurance", "Asuransi"),
            ("vas", "Value Added Service"),
            ("other", "Lainnya"),
        ],
        string="Kategori", required=True, default="other",
    )
    default_nature = fields.Selection(CHARGE_NATURES, string="Sifat Default", required=True, default="service")
    is_freight_charge = fields.Boolean(
        "Biaya Transportasi",
        help="True bila baris ini adalah freight charge. Minimal satu baris "
             "seperti ini harus ada pada tagihan agar PPN besaran tertentu JPT "
             "dapat diterapkan.",
    )
    vat_treatment = fields.Selection(VAT_TREATMENTS, string="Perlakuan PPN", required=True, default="standard")
    default_wht_type = fields.Selection(WHT_TYPES, string="Pot-Put Default", required=True, default="none")
    product_id = fields.Many2one(
        "product.product", "Produk", required=True,
        domain="[('type','=','service')]",
        help="Wajib: account.move.line membutuhkan produk. Akun pendapatan dan "
             "beban diambil dari produk bila tidak ditimpa di sini.",
    )
    revenue_account_id = fields.Many2one(
        "account.account", "Akun Pendapatan",
        domain="[('account_type','in',('income','income_other'))]",
    )
    expense_account_id = fields.Many2one(
        "account.account", "Akun Beban",
        domain="[('account_type','in',('expense','expense_direct_cost'))]",
    )
    sale_tax_ids = fields.Many2many(
        "account.tax", "lgx_charge_code_sale_tax_rel", "charge_code_id", "tax_id",
        string="Pajak Penjualan", domain="[('type_tax_use','=','sale')]",
    )
    purchase_tax_ids = fields.Many2many(
        "account.tax", "lgx_charge_code_purchase_tax_rel", "charge_code_id", "tax_id",
        string="Pajak Pembelian", domain="[('type_tax_use','=','purchase')]",
    )
    uom_id = fields.Many2one("uom.uom", "Satuan Default")
    applies_to = fields.Selection(
        [("all", "Semua segmen"), ("ff", "Forwarding"), ("tms", "Trucking"), ("wms", "Gudang")],
        string="Berlaku Untuk", default="all",
    )
    note = fields.Text("Catatan")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode charge harus unik.")

    @api.constrains("default_nature", "vat_treatment")
    def _check_disbursement_vat(self):
        """Talangan yang dipajaki sebagai penyerahan sendiri adalah kontradiksi.

        Disbursement ditagihkan kembali apa adanya; memungut PPN atasnya berarti
        menyatakan itu penyerahan jasa kita, yang justru membatalkan dasar
        pengecualian PPh 23 atas baris yang sama.
        """
        for rec in self:
            if rec.default_nature == "disbursement" and rec.vat_treatment in ("besaran_tertentu", "standard"):
                if rec.vat_treatment == "besaran_tertentu":
                    raise ValidationError(_(
                        "Kode charge '%s' bersifat talangan pihak ketiga, jadi tidak bisa "
                        "diperlakukan sebagai penyerahan JPT besaran tertentu. Pakai "
                        "'Di luar objek PPN' atau pisahkan menjadi dua kode charge.",
                        rec.code,
                    ))

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
