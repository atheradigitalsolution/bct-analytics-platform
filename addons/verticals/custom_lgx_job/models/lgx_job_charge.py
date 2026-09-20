# -*- coding: utf-8 -*-
"""lgx.job.charge — model terpenting di seluruh desain.

Setiap baris pendapatan dan biaya, dengan nilai ESTIMASI dan AKTUAL
berdampingan. Bukan dua field yang kebetulan ada, melainkan jawaban atas
masalah struktural forwarding: pendapatan diketahui saat job berjalan, tagihan
vendor baru datang dua sampai enam minggu kemudian.

``nature`` menghubungkan pajak langsung ke model data. PMK 141/2015 menyatakan
jumlah bruto dasar pemotongan PPh 23 TIDAK termasuk reimbursement yang dapat
dibuktikan dengan faktur tagihan dan/atau bukti pembayaran dari pihak ketiga.
Kalau pemisahan jasa-sendiri versus talangan tidak ada di model data sejak awal,
tidak ada cara memperbaikinya di lapisan pelaporan — angkanya sudah tercampur.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.custom_lgx_base.models.lgx_charge_code import CHARGE_NATURES, WHT_TYPES


class LgxJobCharge(models.Model):
    _name = "lgx.job.charge"
    _description = "Baris Charge Job"
    _order = "job_id, kind desc, sequence, id"

    sequence = fields.Integer(default=10)
    job_id = fields.Many2one("lgx.job", "Job", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="job_id.company_id", store=True, index=True)
    charge_code_id = fields.Many2one("lgx.charge.code", "Kode Charge", required=True, index=True)
    name = fields.Char("Keterangan")
    kind = fields.Selection(
        [("revenue", "Pendapatan"), ("cost", "Biaya")], string="Jenis", required=True, default="revenue", index=True,
    )
    nature = fields.Selection(
        CHARGE_NATURES, string="Sifat", required=True, default="service", index=True,
        help="Jasa sendiri masuk dasar pemotongan PPh 23. Talangan pihak ketiga "
             "dikeluarkan — dan hanya boleh dikeluarkan bila bukti pihak ketiga "
             "terlampir.",
    )
    is_freight_charge = fields.Boolean(
        "Biaya Transportasi",
        help="Menentukan kelayakan PPN besaran tertentu pada faktur yang memuat baris ini.",
    )
    partner_id = fields.Many2one(
        "res.partner", "Vendor / Pihak", index=True,
        help="Vendor untuk baris biaya. Wajib sebelum baris dikonfirmasi: akrual "
             "tanpa pihak adalah utang yang tidak bisa ditagih ke siapa pun.",
    )

    quantity = fields.Float("Kuantitas", default=1.0, digits="Product Unit of Measure")
    uom_id = fields.Many2one("uom.uom", "Satuan")
    unit_price = fields.Monetary("Harga Satuan", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    company_currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)

    fx_rate_book = fields.Float("Kurs Pembukuan", digits=(16, 6), default=1.0)
    fx_rate_tax = fields.Float("Kurs Pajak (KMK)", digits=(16, 6), default=1.0)
    fx_rate_source = fields.Char("Sumber Kurs")
    fx_rate_date = fields.Date("Tanggal Kurs")

    amount_estimated = fields.Monetary("Estimasi", currency_field="currency_id",
                                       help="Diisi saat job dibuat. Langsung membentuk akrual.")
    amount_actual = fields.Monetary("Aktual", currency_field="currency_id",
                                    help="Diisi saat faktur vendor atau faktur pelanggan terbit.")
    is_actual_known = fields.Boolean(
        "Aktual Diketahui", default=False, copy=False,
        help="Flag eksplisit, bukan 'amount_actual != 0'. Tagihan vendor yang "
             "ternyata nol adalah fakta yang berbeda dari tagihan yang belum datang, "
             "dan keduanya harus bisa dibedakan.",
    )
    amount_effective = fields.Monetary("Nilai Berlaku", compute="_compute_amounts", store=True,
                                       currency_field="currency_id")
    amount_variance = fields.Monetary("Varians", compute="_compute_amounts", store=True,
                                      currency_field="currency_id")
    amount_company = fields.Monetary("Nilai (mata uang perusahaan)", compute="_compute_amounts",
                                     store=True, currency_field="company_currency_id")

    tax_ids = fields.Many2many("account.tax", string="Pajak")
    wht_type = fields.Selection(WHT_TYPES, string="Pot-Put", default="none",
                                help="Kunci netral terhadap angka; tarif dan sifat final berasal "
                                     "dari parameter pajak, bukan dari nama kunci ini.")
    wht_override_reason = fields.Char("Alasan Menimpa Pot-Put")

    third_party_proof_ids = fields.Many2many(
        "ir.attachment", "lgx_job_charge_proof_rel", "charge_id", "attachment_id",
        string="Bukti Pihak Ketiga",
        help="WAJIB bila sifat = talangan. Inilah dasar pengecualian PPh 23; "
             "tanpa lampiran, pengecualian itu tidak dapat dipertahankan saat pemeriksaan.",
    )
    invoice_line_id = fields.Many2one("account.move.line", "Baris Faktur Pelanggan", copy=False, index=True)
    bill_line_id = fields.Many2one("account.move.line", "Baris Tagihan Vendor", copy=False, index=True)

    state = fields.Selection(
        [
            ("estimated", "Estimasi"),
            ("confirmed", "Dikonfirmasi"),
            ("invoiced", "Difakturkan"),
            ("provisioned", "Diprovisikan"),
            ("closed", "Tutup"),
            ("cancelled", "Batal"),
        ],
        string="Status", default="estimated", required=True, index=True,
    )
    note = fields.Char("Catatan")

    _amounts_non_negative = models.Constraint(
        "check(amount_estimated >= 0 and amount_actual >= 0)",
        "Nilai estimasi dan aktual tidak boleh negatif. Koreksi turun dibukukan "
        "sebagai baris terpisah, bukan sebagai nilai negatif.",
    )
    _quantity_non_negative = models.Constraint(
        "check(quantity >= 0)", "Kuantitas tidak boleh negatif.",
    )
    _fx_positive = models.Constraint(
        "check(fx_rate_book > 0 and fx_rate_tax > 0)", "Kurs harus lebih besar dari nol.",
    )

    # --- computes ----------------------------------------------------------
    @api.depends("amount_estimated", "amount_actual", "is_actual_known", "fx_rate_book")
    def _compute_amounts(self):
        for line in self:
            line.amount_effective = line.amount_actual if line.is_actual_known else line.amount_estimated
            line.amount_variance = (line.amount_actual - line.amount_estimated) if line.is_actual_known else 0.0
            line.amount_company = line.amount_effective * (line.fx_rate_book or 1.0)

    # --- onchange ----------------------------------------------------------
    @api.onchange("charge_code_id")
    def _onchange_charge_code(self):
        """Warisi keputusan pajak dari master, sekali, saat kode dipilih."""
        for line in self:
            code = line.charge_code_id
            if not code:
                continue
            line.name = line.name or code.name
            line.nature = code.default_nature
            line.is_freight_charge = code.is_freight_charge
            line.wht_type = code.default_wht_type
            line.uom_id = code.uom_id or line.uom_id
            if line.kind == "revenue":
                line.tax_ids = [(6, 0, code.sale_tax_ids.ids)]
            else:
                line.tax_ids = [(6, 0, code.purchase_tax_ids.ids)]

    @api.onchange("quantity", "unit_price")
    def _onchange_amount(self):
        for line in self:
            if line.state == "estimated":
                line.amount_estimated = (line.quantity or 0.0) * (line.unit_price or 0.0)

    @api.onchange("job_id")
    def _onchange_job(self):
        for line in self:
            if line.job_id:
                line.currency_id = line.job_id.currency_id
                line.fx_rate_book = line.job_id.fx_rate_book or 1.0
                line.fx_rate_tax = line.job_id.fx_rate_tax or 1.0
                line.fx_rate_date = line.job_id.fx_rate_date

    # --- validasi ----------------------------------------------------------
    @api.constrains("nature", "third_party_proof_ids", "state", "kind")
    def _check_disbursement_proof(self):
        """Talangan yang DITAGIHKAN ke pelanggan tidak boleh tanpa bukti pihak ketiga.

        Validasi keras, bukan pengingat: pengecualian PPh 23 atas reimbursement
        bergantung pada adanya faktur tagihan dan/atau bukti pembayaran dari
        pihak ketiga. Tanpa itu barisnya tetap masuk jumlah bruto, dan
        pemotongan yang terlanjur kurang menjadi kewajiban yang baru ketahuan
        saat pemeriksaan.

        Hanya sisi PENDAPATAN yang diuji. Pada sisi biaya, tagihan vendor ITU
        SENDIRI adalah dokumen pihak ketiganya — menuntut lampiran tambahan di
        sana berarti meminta orang memindai ulang faktur yang sudah ada di
        sistem, dan aturan yang terasa sia-sia adalah aturan yang dicarikan jalan
        memutar.
        """
        for line in self:
            if line.nature != "disbursement" or line.kind != "revenue":
                continue
            if line.state in ("invoiced", "closed") and not line.third_party_proof_ids:
                raise ValidationError(_(
                    "Baris talangan '%s' pada job %s tidak dapat difakturkan tanpa "
                    "lampiran bukti pihak ketiga (faktur tagihan atau bukti pembayaran).",
                    line.charge_code_id.code, line.job_id.name,
                ))

    @api.constrains("kind", "partner_id", "state")
    def _check_cost_partner(self):
        for line in self:
            if line.kind == "cost" and line.state not in ("estimated", "cancelled") and not line.partner_id:
                raise ValidationError(_(
                    "Baris biaya '%s' pada job %s harus menunjuk vendor sebelum dikonfirmasi.",
                    line.charge_code_id.code, line.job_id.name,
                ))

    # --- aksi --------------------------------------------------------------
    def action_confirm(self):
        for line in self:
            if line.state != "estimated":
                continue
            if line.kind == "cost" and not line.partner_id:
                raise UserError(_(
                    "Baris biaya '%s' belum menunjuk vendor.", line.charge_code_id.code,
                ))
            line.state = "confirmed"
        return True

    def action_record_actual(self, amount=None):
        """Tandai nilai aktual sudah diketahui.

        Dipanggil custom_lgx_billing saat tagihan vendor atau faktur pelanggan
        diposting. Disediakan terpisah supaya membuka kembali sebuah baris tidak
        memerlukan penulisan langsung ke tiga field sekaligus.
        """
        for line in self:
            vals = {"is_actual_known": True}
            if amount is not None:
                vals["amount_actual"] = amount
            line.write(vals)
        return True

    def action_cancel(self):
        for line in self:
            if line.state in ("invoiced", "closed"):
                raise UserError(_(
                    "Baris '%s' sudah difakturkan dan tidak dapat dibatalkan begitu saja.",
                    line.charge_code_id.code,
                ))
            line.state = "cancelled"
        return True

    @api.model_create_multi
    def create(self, vals_list):
        """Warisi keputusan pajak dari master juga saat baris dibuat dari kode.

        `_onchange_charge_code` hanya berjalan di formulir. Setiap baris yang
        lahir dari API, impor, konversi penawaran, billing gudang, atau data
        demo karena itu melewatinya sama sekali — dan yang hilang bukan
        kosmetik: `wht_type` jatuh ke "none" sehingga PPh 23 tidak pernah
        terhitung, dan `nature` jatuh ke "service" sehingga baris talangan ikut
        masuk jumlah bruto pemotongan.

        Terukur di athera_lgx sebelum perbaikan ini: baris TRK menyimpan
        wht_type='none' padahal masternya 'pph23', dan is_freight_charge kosong
        padahal masternya benar.

        `setdefault` dan bukan penimpaan: pemanggil yang menyebut nilainya
        secara eksplisit tetap menang. Billing gudang memang sengaja memaksa
        nature='service', dan kepabeanan memaksa nature='disbursement'.
        """
        Code = self.env["lgx.charge.code"]
        for vals in vals_list:
            code = Code.browse(vals["charge_code_id"]) if vals.get("charge_code_id") else Code
            if code:
                if not vals.get("name"):
                    vals["name"] = code.name
                vals.setdefault("nature", code.default_nature)
                vals.setdefault("is_freight_charge", code.is_freight_charge)
                vals.setdefault("wht_type", code.default_wht_type)
                if code.uom_id:
                    vals.setdefault("uom_id", code.uom_id.id)
                if "tax_ids" not in vals:
                    taxes = (code.sale_tax_ids if vals.get("kind") == "revenue"
                             else code.purchase_tax_ids)
                    if taxes:
                        vals["tax_ids"] = [(6, 0, taxes.ids)]
            if not vals.get("amount_estimated") and vals.get("quantity") and vals.get("unit_price"):
                vals["amount_estimated"] = vals["quantity"] * vals["unit_price"]
        return super().create(vals_list)
