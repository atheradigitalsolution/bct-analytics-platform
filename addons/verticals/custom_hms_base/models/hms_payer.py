# -*- coding: utf-8 -*-
"""Guarantors: self-pay, BPJS, private insurance, corporate.

The payer decides three things at once — which price column applies, how much
of the bill the patient owes, and which documents the claim needs. Keeping all
three on one model is what lets the cashier answer "berapa yang saya bayar?"
without a human looking anything up.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsPayerPlan(models.Model):
    _name = "hms.payer.plan"
    _description = "Produk/Plan Penjamin"

    payer_id = fields.Many2one("hms.payer", required=True, ondelete="cascade")
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    class_id = fields.Many2one("hms.care.class", "Hak Kelas Perawatan")
    coverage_percent = fields.Float("Persentase Ditanggung (%)", default=100.0)
    plafon_per_visit = fields.Monetary("Plafon per Kunjungan", currency_field="currency_id")
    plafon_per_year = fields.Monetary("Plafon per Tahun", currency_field="currency_id")
    copay_amount = fields.Monetary("Iuran Biaya (copay)", currency_field="currency_id")
    excluded_category_ids = fields.Many2many(
        "hms.tariff.category", string="Kategori Tarif Dikecualikan",
        help="Kategori yang tidak ditanggung sama sekali dan otomatis menjadi porsi pasien.",
    )
    upgrade_class_rule = fields.Selection(
        [("not_allowed", "Tidak boleh naik kelas"),
         ("pay_difference", "Bayar selisih tarif"),
         ("pay_full", "Bayar penuh kelas baru")],
        default="pay_difference", string="Aturan Naik Kelas",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(payer_id, code)",
        "Kode plan harus unik per penjamin.",
    )

    @api.constrains("coverage_percent")
    def _check_coverage(self):
        for rec in self:
            if not 0.0 <= rec.coverage_percent <= 100.0:
                raise ValidationError(_("Persentase ditanggung harus antara 0 dan 100."))


class HmsPayer(models.Model):
    _name = "hms.payer"
    _description = "Penjamin"
    _order = "sequence, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    type = fields.Selection(
        [("self", "Umum / Bayar Sendiri"), ("bpjs", "BPJS Kesehatan"),
         ("insurance", "Asuransi Swasta"), ("company", "Perusahaan"),
         ("government", "Program Pemerintah"), ("charity", "Bantuan Sosial")],
        required=True, default="self",
    )
    partner_id = fields.Many2one(
        "res.partner", "Kontak Piutang",
        help="Lawan transaksi invoice untuk porsi yang ditanggung penjamin. "
             "Kosong untuk penjamin tipe Umum: tagihannya atas nama pasien.",
    )
    payment_term_id = fields.Many2one("account.payment.term", "Termin Pembayaran")
    requires_guarantee_letter = fields.Boolean("Perlu surat jaminan")
    requires_sep = fields.Boolean("Perlu SEP")
    plan_ids = fields.One2many("hms.payer.plan", "payer_id", "Plan")
    claim_document_checklist = fields.Text(
        "Checklist Dokumen Klaim", help="Satu dokumen per baris."
    )
    cob_order = fields.Integer(
        "Urutan COB", default=0,
        help="Urutan penjamin dalam Coordination of Benefit: 0 = penjamin utama, "
             "1 = penjamin kedua yang menanggung sisa, dan seterusnya.",
    )
    aps_covered = fields.Boolean(
        "Menanggung Atas Permintaan Sendiri (APS)", default=False,
        help="Penjamin ini bersedia menanggung selisih layanan yang diminta "
             "sendiri oleh pasien (naik kelas, dokter pilihan). Daftar layanan APS "
             "berasal dari pengumuman rumah sakit, BUKAN dari norma nasional — "
             "isinya menjadi tanggung jawab RS.",
    )
    contract_no = fields.Char("Nomor Kontrak")
    contract_valid_to = fields.Date("Kontrak Berlaku Sampai")
    contact_person = fields.Char("Narahubung")
    contact_phone = fields.Char("Telepon Narahubung")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode penjamin harus unik.",
    )

    @api.onchange("type")
    def _onchange_type(self):
        if self.type == "bpjs":
            self.requires_sep = True
        elif self.type == "insurance":
            self.requires_guarantee_letter = True
