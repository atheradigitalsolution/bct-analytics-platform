# -*- coding: utf-8 -*-
"""Penentuan perlakuan PPN, dasar PPh, dan validasi keras ekspor jasa.

ALUR KEPUTUSAN PPN (§11.1), diterapkan persis seperti tertulis
-------------------------------------------------------------
1. Kumpulkan baris charge ``kind = revenue``.
2. Ada minimal satu ``is_freight_charge`` DAN job_type termasuk kelompok JPT
   → besaran tertentu, kode faktur 05, pajak masukan terkait ditandai tidak
   dapat dikreditkan.
3. Tidak ada freight charge → **TAMPILKAN PERINGATAN**, jangan putuskan
   diam-diam. ⚠ Tidak ditemukan aturan eksplisit yang menyatakan tarif apa yang
   berlaku; praktisi umumnya kembali ke PPN normal, tetapi itu belum
   terkonfirmasi sumber resmi (butir A3). Defaultnya karena itu adalah
   PARAMETER, bukan keputusan modul ini.
4. Tujuan ekspor DAN kontrak + bukti pembayaran luar negeri terlampir
   → ekspor jasa 0%. **BLOKIR posting** bila salah satu dokumen belum ada.
5. Seluruh baris angkutan umum darat/air yang memenuhi syarat → dibebaskan,
   dan dasar keputusannya DISIMPAN.

Langkah 3 dan 5 sengaja tidak otomatis penuh. Keduanya berada di wilayah yang
belum pasti secara regulasi, dan keputusan diam-diam di sana menciptakan risiko
sengketa yang baru ketahuan saat pemeriksaan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.custom_lgx_base.models.lgx_charge_code import VAT_TREATMENTS


class AccountMove(models.Model):
    _inherit = "account.move"

    lgx_vat_treatment = fields.Selection(
        VAT_TREATMENTS, string="Perlakuan PPN Logistik",
        compute="_compute_lgx_vat_treatment", store=True, readonly=False, tracking=True,
    )
    lgx_vat_warning = fields.Char("Peringatan PPN", compute="_compute_lgx_vat_treatment", store=True)
    lgx_has_freight_charge = fields.Boolean("Memuat Freight Charge",
                                            compute="_compute_lgx_vat_treatment", store=True)
    lgx_faktur_code = fields.Char(
        "Kode Transaksi Faktur Pajak", compute="_compute_lgx_vat_treatment", store=True,
        readonly=False,
        help="05 untuk penyerahan dengan besaran tertentu; 01 untuk penyerahan normal. "
             "Bukan NSFP — NSFP datang dari respons DJP dan disimpan custom_coretax.",
    )
    lgx_input_vat_not_creditable = fields.Boolean(
        "PM Tidak Dapat Dikreditkan", compute="_compute_lgx_vat_treatment", store=True,
        help="Penyerahan dengan besaran tertentu membuat pajak masukan atas perolehan "
             "terkait tidak dapat dikreditkan.",
    )
    lgx_exemption_basis = fields.Text(
        "Dasar Keputusan Pembebasan",
        help="Wajib diisi untuk pembebasan angkutan umum: bukan sewa/charter, dan "
             "bukan mengangkut barang satu pihak dalam satu perjalanan tertentu. "
             "Praktik pemeriksaan di lapangan masih sering memakai indikator plat "
             "kuning, jadi dasar keputusannya disimpan per dokumen.",
    )
    lgx_export_contract_ids = fields.Many2many(
        "ir.attachment", "lgx_move_export_contract_rel", "move_id", "attachment_id",
        string="Kontrak Ekspor Jasa",
    )
    lgx_export_payment_proof_ids = fields.Many2many(
        "ir.attachment", "lgx_move_export_proof_rel", "move_id", "attachment_id",
        string="Bukti Pembayaran dari Luar Negeri",
    )
    lgx_wht_base = fields.Monetary("Dasar Pot-Put", compute="_compute_lgx_wht", store=True)
    lgx_wht_excluded = fields.Monetary("Dikecualikan (Reimbursement)",
                                       compute="_compute_lgx_wht", store=True)
    lgx_wht_type = fields.Char("Jenis Pot-Put Dominan", compute="_compute_lgx_wht", store=True)
    lgx_wht_rate = fields.Float("Tarif Pot-Put (%)", compute="_compute_lgx_wht", store=True,
                                digits=(5, 2))
    lgx_wht_amount = fields.Monetary("Nilai Pot-Put", compute="_compute_lgx_wht", store=True)
    lgx_nitku = fields.Char("NITKU Cabang", compute="_compute_lgx_nitku", store=True, readonly=False)

    # --- PPN ---------------------------------------------------------------
    @api.depends("lgx_job_id", "line_ids.lgx_charge_id", "move_type")
    def _compute_lgx_vat_treatment(self):
        params = self.env["ir.config_parameter"].sudo()
        default_without_freight = params.get_param("lgx.vat_default_without_freight", "standard")
        for move in self:
            move.lgx_vat_warning = False
            if not move.lgx_job_id or move.move_type not in ("out_invoice", "out_refund"):
                move.lgx_has_freight_charge = False
                move.lgx_input_vat_not_creditable = False
                if not move.lgx_vat_treatment:
                    move.lgx_vat_treatment = False
                    move.lgx_faktur_code = False
                continue
            charges = move.line_ids.mapped("lgx_charge_id").filtered(
                lambda c: c.kind == "revenue")
            has_freight = any(charges.mapped("is_freight_charge"))
            move.lgx_has_freight_charge = has_freight
            job = move.lgx_job_id

            treatments = set(charges.mapped("charge_code_id.vat_treatment"))
            if treatments == {"exempt_public_transport"}:
                move.lgx_vat_treatment = "exempt_public_transport"
                move.lgx_faktur_code = False
                move.lgx_input_vat_not_creditable = False
                move.lgx_vat_warning = _(
                    "Seluruh baris adalah angkutan umum yang dibebaskan. Isi dasar "
                    "keputusannya — pembebasan tanpa dasar tertulis adalah area "
                    "berisiko sengketa."
                )
                continue
            if job.direction == "export" and "export_service_zero" in treatments:
                move.lgx_vat_treatment = "export_service_zero"
                move.lgx_faktur_code = "06"
                move.lgx_input_vat_not_creditable = False
                continue
            if has_freight and job.lgx_is_jpt():
                move.lgx_vat_treatment = "besaran_tertentu"
                move.lgx_faktur_code = "05"
                move.lgx_input_vat_not_creditable = True
                continue
            if job.lgx_is_jpt() and not has_freight:
                move.lgx_vat_treatment = default_without_freight
                move.lgx_faktur_code = "01" if default_without_freight == "standard" else False
                move.lgx_input_vat_not_creditable = False
                move.lgx_vat_warning = _(
                    "Tagihan JPT ini TIDAK memuat satu pun freight charge, jadi syarat "
                    "penerapan PPN besaran tertentu tidak terpenuhi. Default yang dipakai "
                    "adalah '%s' dari parameter 'lgx.vat_default_without_freight'.\n\n"
                    "Tidak ditemukan aturan eksplisit yang menyatakan tarif apa yang "
                    "berlaku dalam keadaan ini; periksa ke konsultan pajak sebelum "
                    "faktur diterbitkan.", default_without_freight,
                )
                continue
            move.lgx_vat_treatment = "standard"
            move.lgx_faktur_code = "01"
            move.lgx_input_vat_not_creditable = False

    # --- pot-put -----------------------------------------------------------
    @api.depends("line_ids.lgx_charge_id", "move_type", "invoice_date", "partner_id")
    def _compute_lgx_wht(self):
        """Dasar pemotongan menjumlah HANYA baris dengan nature = service.

        Baris talangan dikeluarkan — dan pengecualian itu hanya sah bila bukti
        pihak ketiga terlampir, yang ditegakkan constraint di lgx.job.charge dan
        diperiksa lagi sebelum posting di bawah.
        """
        for move in self:
            charges = move.line_ids.mapped("lgx_charge_id")
            if not charges:
                move.lgx_wht_base = move.lgx_wht_excluded = move.lgx_wht_amount = 0.0
                move.lgx_wht_type = False
                move.lgx_wht_rate = 0.0
                continue
            relevant = charges.filtered(
                lambda c: c.kind == ("revenue" if move.move_type in ("out_invoice", "out_refund")
                                     else "cost"))
            service = relevant.filtered(lambda c: c.nature == "service")
            disbursement = relevant.filtered(lambda c: c.nature == "disbursement")
            move.lgx_wht_base = sum(service.mapped("amount_effective"))
            move.lgx_wht_excluded = sum(disbursement.mapped("amount_effective"))

            types = [t for t in service.mapped("wht_type") if t and t != "none"]
            dominant = max(set(types), key=types.count) if types else False
            move.lgx_wht_type = dominant
            if not dominant:
                move.lgx_wht_rate = 0.0
                move.lgx_wht_amount = 0.0
                continue
            rate_record = self.env["lgx.wht.rate"].lgx_find(
                dominant, move.invoice_date or fields.Date.context_today(move), move.company_id)
            if not rate_record:
                move.lgx_wht_rate = 0.0
                move.lgx_wht_amount = 0.0
                continue
            recipient = move._lgx_wht_recipient()
            has_npwp = recipient.lgx_has_valid_npwp() if recipient else False
            move.lgx_wht_rate = (rate_record.rate if has_npwp
                                 else (rate_record.rate_no_npwp or rate_record.rate))
            move.lgx_wht_amount = move.lgx_wht_base * move.lgx_wht_rate / 100.0

    def _lgx_wht_recipient(self):
        """Siapa PENERIMA PENGHASILAN pada dokumen ini.

        Pada tagihan vendor (kita memotong) penerimanya vendor; pada faktur
        penjualan (pelanggan memotong kita) penerimanya perusahaan/cabang kita
        sendiri. Menguji partner yang salah menghasilkan tarif yang salah setiap
        kali salah satu pihak tidak ber-NPWP — dan itu selisih 100%.
        """
        self.ensure_one()
        if self.move_type in ("in_invoice", "in_refund"):
            return self.partner_id
        return self.company_id.partner_id

    @api.depends("lgx_job_id", "operating_unit_id")
    def _compute_lgx_nitku(self):
        for move in self:
            unit = move.operating_unit_id or move.lgx_job_id.operating_unit_id
            move.lgx_nitku = unit.lgx_nitku if unit else False

    # --- validasi sebelum posting ------------------------------------------
    def _post(self, soft=True):
        for move in self.filtered(lambda m: m.lgx_job_id):
            move._lgx_check_export_service_documents()
            move._lgx_check_disbursement_proof()
            move._lgx_check_exemption_basis()
        return super()._post(soft=soft)

    def _lgx_check_export_service_documents(self):
        """Ekspor jasa 0%: validasi KERAS, bukan pengingat.

        PMK 32/PMK.010/2019 menuntut kontrak tertulis yang menyebut jenis jasa,
        rincian kegiatan dan nilai penyerahan, DITAMBAH bukti pembayaran dari
        penerima jasa di luar negeri. Fasilitas tarif nol yang tidak dapat
        dibuktikan akan gugur saat pemeriksaan, dan pada titik itu PPN-nya
        menjadi beban perusahaan sendiri.
        """
        self.ensure_one()
        if self.lgx_vat_treatment != "export_service_zero":
            return
        missing = []
        if not self.lgx_export_contract_ids:
            missing.append(_("kontrak tertulis"))
        if not self.lgx_export_payment_proof_ids:
            missing.append(_("bukti pembayaran dari penerima jasa di luar negeri"))
        if missing:
            raise UserError(_(
                "Faktur ekspor jasa 0% tidak dapat diposting: %s belum dilampirkan.\n\n"
                "Keduanya adalah syarat PMK 32/PMK.010/2019. Fasilitas tarif nol yang "
                "tidak dapat dibuktikan akan gugur saat pemeriksaan.",
                " dan ".join(missing),
            ))

    def _lgx_check_disbursement_proof(self):
        self.ensure_one()
        charges = self.line_ids.mapped("lgx_charge_id").filtered(
            lambda c: c.kind == "revenue" and c.nature == "disbursement")
        missing = charges.filtered(lambda c: not c.third_party_proof_ids)
        if missing:
            raise UserError(_(
                "Baris talangan berikut belum punya bukti pihak ketiga: %s.\n\n"
                "Tanpa bukti itu, pengecualiannya dari jumlah bruto PPh 23 (PMK 141/2015) "
                "tidak dapat dipertahankan.",
                ", ".join(missing.mapped("charge_code_id.code")),
            ))

    def _lgx_check_exemption_basis(self):
        self.ensure_one()
        if self.lgx_vat_treatment == "exempt_public_transport" and not self.lgx_exemption_basis:
            raise UserError(_(
                "Pembebasan PPN angkutan umum menuntut dasar keputusan tertulis: "
                "bukan sewa/charter, dan bukan mengangkut barang satu pihak dalam satu "
                "perjalanan tertentu.\n\n"
                "Praktik pemeriksaan di lapangan masih sering memakai indikator plat "
                "kuning, jadi dasar ini disimpan per dokumen — bukan diasumsikan."
            ))
