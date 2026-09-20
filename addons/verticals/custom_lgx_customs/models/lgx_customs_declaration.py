# -*- coding: utf-8 -*-
"""Deklarasi pabean: PIB, PEB, dan dokumen TPB/PLB.

Perhitungan bea masuk dan pajak impor dilakukan PER BARIS dan dijumlahkan ke
kepala dokumen, bukan sebaliknya. Alasannya bukan kerapian: tarif berbeda per HS
code, dan satu PIB rutin memuat puluhan pos tarif. Menghitung di kepala dokumen
dengan satu tarif rata-rata adalah cara menghasilkan angka yang selalu sedikit
salah dan tidak pernah bisa dijelaskan ke Bea Cukai.

Nilai pabean dihitung dalam mata uang asing lalu dikonversi dengan **kurs pajak
(KMK)**, bukan kurs pembukuan. Memakai kurs pembukuan di sini menghasilkan nilai
rupiah PIB yang salah — kategori kesalahan yang langsung terlihat saat
pemeriksaan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

DOC_TYPES = [
    ("bc20_pib", "BC 2.0 — PIB"),
    ("bc30_peb", "BC 3.0 — PEB"),
    ("bc11_manifest", "BC 1.1 — Manifes"),
    ("bc23_tpb_in", "BC 2.3 — Pemasukan TPB"),
    ("bc25_tpb_out", "BC 2.5 — Pengeluaran TPB"),
    ("bc16_plb_in", "BC 1.6 — Pemasukan PLB"),
    ("bc28_plb_out", "BC 2.8 — Pengeluaran PLB"),
    ("ppftz", "PPFTZ"),
]


class LgxCustomsDeclaration(models.Model):
    _name = "lgx.customs.declaration"
    _description = "Deklarasi Pabean"
    _order = "registration_date desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread", "mail.activity.mixin"]
    _lgx_sequence_code = "lgx.customs.declaration"

    job_id = fields.Many2one("lgx.job", "Job", required=True, ondelete="cascade",
                             index=True, tracking=True)
    shipment_id = fields.Many2one("lgx.shipment", "Shipment", index=True,
                                  domain="[('job_id','=',job_id)]")
    company_id = fields.Many2one(related="job_id.company_id", store=True, index=True)
    doc_type = fields.Selection(DOC_TYPES, "Jenis Dokumen", required=True,
                                default="bc20_pib", tracking=True, index=True)

    aju_number = fields.Char("Nomor Pengajuan (AJU)", copy=False, index=True)
    registration_number = fields.Char("Nomor Pendaftaran", copy=False, index=True, tracking=True)
    registration_date = fields.Date("Tanggal Pendaftaran", copy=False, tracking=True)

    principal_id = fields.Many2one("res.partner", "Importir / Eksportir", required=True,
                                   tracking=True)
    principal_nib = fields.Char("NIB Prinsipal", compute="_compute_principal_identity",
                                store=True, readonly=False)
    principal_npwp = fields.Char("NPWP Prinsipal", compute="_compute_principal_identity",
                                 store=True, readonly=False)
    customs_access_type = fields.Selection(
        related="principal_id.lgx_customs_access_type", string="Jenis Akses Kepabeanan",
        store=True, readonly=False,
    )
    ppjk_id = fields.Many2one("res.partner", "PPJK", domain="[('lgx_is_ppjk','=',True)]")
    customs_expert_id = fields.Many2one(
        "lgx.customs.expert", "Ahli Kepabeanan",
        help="Wajib bersertifikat dan masih berlaku. Deklarasi tidak dapat "
             "disubmit bila sertifikatnya sudah lewat masa berlaku.",
    )
    customs_office_id = fields.Many2one("lgx.customs.office", "Kantor Pabean", required=True)

    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    company_currency_id = fields.Many2one(related="company_id.currency_id", readonly=True)
    fx_rate_tax = fields.Float(
        "Kurs KMK", digits=(16, 6), default=1.0, required=True,
        help="Kurs Menteri Keuangan yang berlaku pada tanggal PIB. BUKAN kurs pembukuan.",
    )
    fx_rate_kmk_status = fields.Selection(
        [("ok", "Cocok dengan KMK"), ("unknown", "KMK belum tercatat"),
         ("mismatch", "Berbeda dari KMK")],
        string="Status Kurs KMK", compute="_compute_fx_rate_kmk", store=True,
    )
    fx_rate_kmk_message = fields.Char(
        "Keterangan Kurs KMK", compute="_compute_fx_rate_kmk", store=True)
    fx_rate_kmk_id = fields.Many2one(
        "lgx.kmk.rate", "KMK Acuan", compute="_compute_fx_rate_kmk", store=True)
    fx_rate_override_reason = fields.Char(
        "Alasan Kurs Berbeda dari KMK",
        help="Wajib bila kurs yang dipakai berbeda dari KMK yang berlaku. "
             "Selisih kurs mengalikan SELURUH pungutan, jadi ia tidak boleh "
             "lewat tanpa jejak.",
    )

    line_ids = fields.One2many("lgx.customs.declaration.line", "declaration_id", "Baris Barang")
    total_cif = fields.Monetary("Nilai Pabean (CIF)", compute="_compute_totals", store=True,
                                currency_field="currency_id")
    total_cif_idr = fields.Monetary("Nilai Pabean (Rp)", compute="_compute_totals", store=True,
                                    currency_field="company_currency_id")
    total_bm = fields.Monetary("Total Bea Masuk", compute="_compute_totals", store=True,
                               currency_field="company_currency_id")
    total_ppn_impor = fields.Monetary("Total PPN Impor", compute="_compute_totals", store=True,
                                      currency_field="company_currency_id")
    total_ppnbm = fields.Monetary("Total PPnBM", compute="_compute_totals", store=True,
                                  currency_field="company_currency_id")
    total_pph22 = fields.Monetary("Total PPh 22", compute="_compute_totals", store=True,
                                  currency_field="company_currency_id")
    total_duty_tax = fields.Monetary("Total Pungutan", compute="_compute_totals", store=True,
                                     currency_field="company_currency_id")
    has_lartas = fields.Boolean("Ada Lartas", compute="_compute_totals", store=True)
    importer_has_api = fields.Boolean(
        "Importir ber-API", default=True,
        help="Tanpa Angka Pengenal Importir, tarif PPh 22 lebih tinggi.",
    )

    channel = fields.Selection(
        [("green", "Jalur Hijau"), ("yellow", "Jalur Kuning"), ("red", "Jalur Merah")],
        string="Jalur Respons", tracking=True,
    )
    guarantee_id = fields.Many2one("lgx.customs.guarantee", "Jaminan")
    charge_ids = fields.One2many("lgx.job.charge", "customs_declaration_id", "Baris Talangan")
    submission_mode = fields.Selection(
        [("ceisa", "CEISA 4.0 (host-to-host)"), ("manual", "Manual / Portal")],
        string="Cara Kirim", compute="_compute_submission_mode", store=True, readonly=False,
        help="Kantor pabean yang belum wajib CEISA 4.0 dikerjakan manual; sistem "
             "tidak mencoba mengirim otomatis ke sana.",
    )
    state = fields.Selection(
        [("draft", "Draf"), ("submitted", "Diajukan"), ("received", "Diterima"),
         ("responded", "Direspons"), ("released", "Dikeluarkan"), ("done", "Selesai"),
         ("rejected", "Ditolak")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Text("Catatan")

    _registration_uniq = models.Constraint(
        "unique(registration_number, customs_office_id)",
        "Nomor pendaftaran ini sudah tercatat untuk kantor pabean yang sama.",
    )
    _fx_positive = models.Constraint("check(fx_rate_tax > 0)", "Kurs KMK harus lebih besar dari nol.")

    # --- computes ----------------------------------------------------------
    @api.depends("principal_id")
    def _compute_principal_identity(self):
        for declaration in self:
            declaration.principal_nib = declaration.principal_id.lgx_nib
            declaration.principal_npwp = declaration.principal_id.vat

    @api.depends("customs_office_id.ceisa_mandatory")
    def _compute_submission_mode(self):
        for declaration in self:
            declaration.submission_mode = (
                "ceisa" if declaration.customs_office_id.ceisa_mandatory else "manual"
            )

    @api.depends("line_ids.customs_value", "line_ids.bm_amount", "line_ids.ppn_amount",
                 "line_ids.ppnbm_amount", "line_ids.pph22_amount", "line_ids.hs_code_id",
                 "fx_rate_tax")
    def _compute_totals(self):
        for declaration in self:
            declaration.total_cif = sum(declaration.line_ids.mapped("customs_value"))
            declaration.total_cif_idr = declaration.total_cif * (declaration.fx_rate_tax or 1.0)
            declaration.total_bm = sum(declaration.line_ids.mapped("bm_amount"))
            declaration.total_ppn_impor = sum(declaration.line_ids.mapped("ppn_amount"))
            declaration.total_ppnbm = sum(declaration.line_ids.mapped("ppnbm_amount"))
            declaration.total_pph22 = sum(declaration.line_ids.mapped("pph22_amount"))
            declaration.total_duty_tax = (
                declaration.total_bm + declaration.total_ppn_impor
                + declaration.total_ppnbm + declaration.total_pph22
            )
            declaration.has_lartas = any(declaration.line_ids.mapped("hs_code_id.lartas_flag"))

    # --- validasi ----------------------------------------------------------
    @api.constrains("principal_id", "state")
    def _check_principal_identity(self):
        """NIB dan NPWP, tanpa NIK. Diperiksa saat diajukan, bukan saat diketik.

        Memeriksa terlalu awal membuat orang tidak bisa menyimpan draf sambil
        menunggu dokumen prinsipal datang — dan draf yang tidak bisa disimpan
        akan dikerjakan di luar sistem.
        """
        for declaration in self:
            if declaration.state == "draft":
                continue
            missing = []
            if not declaration.principal_nib:
                missing.append(_("NIB"))
            if not declaration.principal_npwp:
                missing.append(_("NPWP"))
            if not declaration.customs_access_type:
                missing.append(_("jenis Akses Kepabeanan"))
            if missing:
                raise ValidationError(_(
                    "Prinsipal %s belum lengkap identitas kepabeanannya: %s. "
                    "PMK 219/2019 mengganti NIK dengan Akses Kepabeanan yang melekat "
                    "pada NIB dan NPWP.",
                    declaration.principal_id.display_name, ", ".join(missing),
                ))

    # --- alur --------------------------------------------------------------
    @api.depends("fx_rate_tax", "currency_id", "registration_date", "company_id")
    def _compute_fx_rate_kmk(self):
        """Bandingkan kurs yang diketik dengan KMK yang berlaku pada tanggalnya.

        Butir A26: kurs KMK ditetapkan mingguan, berlaku Rabu 00.00 sampai
        Selasa. Yang diperiksa adalah kurs pada TANGGAL PENDAFTARAN, bukan hari
        ini — deklarasi yang dibuka kembali tiga minggu kemudian harus tetap
        menunjukkan kurs yang dipakai saat itu.

        `unknown` bukan `ok`. Selama tabel KMK belum diisi, setiap deklarasi
        menyatakan dirinya tidak dapat diverifikasi — dan itu memang keadaannya.
        Melaporkannya "cocok" karena tidak ada pembanding adalah cara tabel itu
        tidak pernah diisi.
        """
        Kmk = self.env["lgx.kmk.rate"]
        for declaration in self:
            on_date = declaration.registration_date or fields.Date.context_today(declaration)
            kmk = Kmk.lgx_find(declaration.currency_id, on_date, declaration.company_id)
            declaration.fx_rate_kmk_id = kmk
            if declaration.currency_id == declaration.company_currency_id:
                declaration.fx_rate_kmk_status = "ok"
                declaration.fx_rate_kmk_message = _("Mata uang sama dengan mata uang perusahaan.")
                continue
            if not kmk:
                declaration.fx_rate_kmk_status = "unknown"
                declaration.fx_rate_kmk_message = _(
                    "Belum ada kurs KMK tercatat untuk %s pada %s, jadi kurs yang "
                    "dipakai tidak dapat diverifikasi. Sumber resmi: "
                    "fiskal.kemenkeu.go.id, ditetapkan mingguan (Rabu-Selasa).",
                    declaration.currency_id.name, on_date,
                )
                continue
            if float_compare(declaration.fx_rate_tax, kmk.rate, precision_digits=6) == 0:
                declaration.fx_rate_kmk_status = "ok"
                declaration.fx_rate_kmk_message = _(
                    "Cocok dengan %s.", kmk.kmk_number)
                continue
            declaration.fx_rate_kmk_status = "mismatch"
            declaration.fx_rate_kmk_message = _(
                "Kurs yang dipakai %s berbeda dari KMK %s yang menetapkan %s untuk "
                "periode %s sampai %s. Seluruh pungutan berskala linear terhadap "
                "angka ini.",
                declaration.fx_rate_tax, kmk.kmk_number, kmk.rate,
                kmk.valid_from, kmk.valid_to,
            )

    def action_submit(self):
        for declaration in self:
            if declaration.state != "draft":
                raise UserError(_("Hanya deklarasi draf yang dapat diajukan."))
            if not declaration.line_ids:
                raise UserError(_("Deklarasi %s belum punya baris barang.", declaration.name))
            if not declaration.customs_expert_id:
                raise UserError(_(
                    "Deklarasi %s harus menunjuk satu Ahli Kepabeanan bersertifikat "
                    "(PMK 219/2019).", declaration.name,
                ))
            expert = declaration.customs_expert_id
            if expert.certificate_expiry and expert.is_expired:
                raise UserError(_(
                    "Sertifikat Ahli Kepabeanan %s sudah lewat masa berlaku pada %s. "
                    "Deklarasi tidak dapat diajukan dengan ahli yang sertifikatnya mati.",
                    expert.name, expert.certificate_expiry,
                ))
            if declaration.fx_rate_kmk_status == "mismatch" and not declaration.fx_rate_override_reason:
                raise UserError(_(
                    "%s\n\nIsi 'Alasan Kurs Berbeda dari KMK' bila ini memang "
                    "disengaja. Kurs yang salah tidak membuat satu angka pun "
                    "terlihat ganjil — semuanya ikut bergerak, konsisten dan salah.",
                    declaration.fx_rate_kmk_message,
                ))
            if declaration.fx_rate_kmk_status == "unknown":
                declaration.message_post(body=declaration.fx_rate_kmk_message)
            lartas_lines = declaration.line_ids.filtered(lambda l: l.hs_code_id.lartas_flag)
            if lartas_lines:
                declaration.message_post(body=_(
                    "Deklarasi memuat %s pos tarif berstatus lartas. Izin yang dibutuhkan: %s",
                    len(lartas_lines),
                    "; ".join(filter(None, lartas_lines.mapped("hs_code_id.permit_note"))) or _("belum dicatat"),
                ))
            declaration.state = "submitted"
            declaration.job_id.lgx_log_milestone("customs_submitted", source="manual")
        return True

    def action_receive(self):
        self.filtered(lambda d: d.state == "submitted").write({"state": "received"})
        return True

    def action_respond(self, channel=None):
        for declaration in self:
            vals = {"state": "responded"}
            if channel:
                vals["channel"] = channel
            declaration.write(vals)
            declaration.job_id.lgx_log_milestone("customs_responded", source="manual")
            if declaration.channel == "red":
                declaration.job_id.lgx_log_milestone("customs_red_lane", source="manual")
        return True

    def action_release(self):
        for declaration in self:
            declaration.write({"state": "released"})
            declaration.job_id.lgx_log_milestone("customs_released", source="manual")
        return True

    def action_generate_job_charges(self):
        """Salin pungutan ke job sebagai baris TALANGAN.

        Bea masuk, PPN impor, PPnBM dan PPh 22 dibayarkan atas nama importir dan
        ditagihkan kembali apa adanya. Melewatkannya ke akun beban akan
        menggelembungkan HPP berkali lipat pada job impor dan membuat margin
        job kehilangan arti.
        """
        Charge = self.env["lgx.job.charge"]
        mapping = [
            ("custom_lgx_base.charge_bm", "total_bm"),
            ("custom_lgx_base.charge_ppnimp", "total_ppn_impor"),
            ("custom_lgx_base.charge_ppnbm", "total_ppnbm"),
            ("custom_lgx_base.charge_pph22", "total_pph22"),
        ]
        created = Charge.browse()
        for declaration in self:
            if declaration.charge_ids:
                raise UserError(_(
                    "Pungutan deklarasi %s sudah disalin ke job. Hapus baris lamanya "
                    "lebih dulu bila perhitungannya berubah.", declaration.name,
                ))
            payee = declaration.customs_office_id.partner_id
            if not payee:
                raise UserError(_(
                    "Kantor pabean %s belum menunjuk partner penerima pembayaran. "
                    "Baris talangan tanpa pihak adalah utang yang tidak dapat "
                    "direkonsiliasi, jadi ia ditolak di sini dan bukan ditambal "
                    "dengan menunjuk importir sebagai vendornya.",
                    declaration.customs_office_id.display_name,
                ))
            for xmlid, field_name in mapping:
                amount = declaration[field_name]
                if not amount:
                    continue
                charge_code = self.env.ref(xmlid)
                created |= Charge.create({
                    "job_id": declaration.job_id.id,
                    "charge_code_id": charge_code.id,
                    "customs_declaration_id": declaration.id,
                    "kind": "cost",
                    "nature": "disbursement",
                    "partner_id": payee.id,
                    "quantity": 1.0,
                    "unit_price": amount,
                    "amount_estimated": amount,
                    "currency_id": declaration.company_currency_id.id,
                    "name": _("%s — deklarasi %s", charge_code.name, declaration.name),
                })
        return created

    @api.model
    def lgx_ppjk_exposure(self, date_from=None, date_to=None, office=None):
        """Eksposur PPJK per prinsipal, untuk deklarasi yang belum selesai.

        PMK 219/2019 Pasal 24 ayat 2: PPJK bertanggung jawab atas bea masuk
        terutang bila importir tidak ditemukan. Angka ini karena itu bukan
        statistik — ia nilai risiko yang benar-benar bisa ditagihkan ke perusahaan.
        """
        domain = [("state", "in", ("submitted", "received", "responded", "released"))]
        if date_from:
            domain.append(("registration_date", ">=", date_from))
        if date_to:
            domain.append(("registration_date", "<=", date_to))
        if office:
            domain.append(("customs_office_id", "=", office.id if hasattr(office, "id") else office))
        result = {}
        for declaration in self.search(domain):
            key = declaration.principal_id
            entry = result.setdefault(key, {"partner": key, "count": 0, "bm": 0.0, "total": 0.0})
            entry["count"] += 1
            entry["bm"] += declaration.total_bm
            entry["total"] += declaration.total_duty_tax
        return list(result.values())


class LgxCustomsDeclarationLine(models.Model):
    _name = "lgx.customs.declaration.line"
    _description = "Baris Deklarasi Pabean"
    _order = "declaration_id, sequence, id"

    sequence = fields.Integer(default=10)
    declaration_id = fields.Many2one("lgx.customs.declaration", "Deklarasi", required=True,
                                     ondelete="cascade", index=True)
    hs_code_id = fields.Many2one("lgx.hs.code", "HS Code", required=True)
    description = fields.Char("Uraian Barang", required=True)
    quantity = fields.Float("Kuantitas", default=1.0)
    uom_id = fields.Many2one("uom.uom", "Satuan")
    country_of_origin_id = fields.Many2one("res.country", "Negara Asal")
    net_weight_kg = fields.Float("Berat Bersih (kg)")

    customs_value = fields.Monetary("Nilai Pabean (CIF)", currency_field="currency_id")
    currency_id = fields.Many2one(related="declaration_id.currency_id", readonly=True)
    company_currency_id = fields.Many2one(related="declaration_id.company_currency_id", readonly=True)
    customs_value_idr = fields.Monetary("Nilai Pabean (Rp)", compute="_compute_duty",
                                        store=True, currency_field="company_currency_id")

    bm_rate = fields.Float("BM (%)", digits=(5, 2), compute="_compute_rates",
                           store=True, readonly=False)
    ppn_rate = fields.Float("PPN (%)", digits=(5, 2), compute="_compute_rates",
                            store=True, readonly=False)
    ppnbm_rate = fields.Float("PPnBM (%)", digits=(5, 2), compute="_compute_rates",
                              store=True, readonly=False)
    pph22_rate = fields.Float("PPh 22 (%)", digits=(5, 2), compute="_compute_rates",
                              store=True, readonly=False)

    bm_amount = fields.Monetary("Bea Masuk", compute="_compute_duty", store=True,
                                currency_field="company_currency_id")
    ppn_amount = fields.Monetary("PPN Impor", compute="_compute_duty", store=True,
                                 currency_field="company_currency_id")
    ppnbm_amount = fields.Monetary("PPnBM", compute="_compute_duty", store=True,
                                   currency_field="company_currency_id")
    pph22_amount = fields.Monetary("PPh 22", compute="_compute_duty", store=True,
                                   currency_field="company_currency_id")
    import_tax_base = fields.Monetary("Nilai Impor (DPP)", compute="_compute_duty", store=True,
                                      currency_field="company_currency_id")

    _customs_value_non_negative = models.Constraint(
        "check(customs_value >= 0)", "Nilai pabean tidak boleh negatif.",
    )

    @api.depends("hs_code_id", "declaration_id.importer_has_api")
    def _compute_rates(self):
        for line in self:
            hs_code = line.hs_code_id
            line.bm_rate = hs_code.bm_rate
            line.ppn_rate = hs_code.ppn_rate
            line.ppnbm_rate = hs_code.ppnbm_rate
            line.pph22_rate = (
                hs_code.pph22_rate if line.declaration_id.importer_has_api
                else hs_code.pph22_rate_no_api
            )

    @api.depends("customs_value", "bm_rate", "ppn_rate", "ppnbm_rate", "pph22_rate",
                 "declaration_id.fx_rate_tax")
    def _compute_duty(self):
        """Urutan perhitungannya menentukan hasilnya.

            Nilai Impor (DPP) = Nilai Pabean + Bea Masuk

        PPN impor, PPnBM dan PPh 22 dihitung dari NILAI IMPOR, bukan dari nilai
        pabean. Menghitungnya langsung dari CIF adalah kesalahan yang selalu
        menghasilkan angka lebih kecil, dan selisihnya baru ketahuan saat SPPB
        tidak kunjung terbit.
        """
        for line in self:
            rate = line.declaration_id.fx_rate_tax or 1.0
            cif_idr = (line.customs_value or 0.0) * rate
            bm = cif_idr * (line.bm_rate or 0.0) / 100.0
            import_value = cif_idr + bm
            line.customs_value_idr = cif_idr
            line.bm_amount = bm
            line.import_tax_base = import_value
            line.ppn_amount = import_value * (line.ppn_rate or 0.0) / 100.0
            line.ppnbm_amount = import_value * (line.ppnbm_rate or 0.0) / 100.0
            line.pph22_amount = import_value * (line.pph22_rate or 0.0) / 100.0

    @api.onchange("hs_code_id")
    def _onchange_hs_code(self):
        for line in self:
            if line.hs_code_id and not line.description:
                line.description = line.hs_code_id.name


class LgxJobCharge(models.Model):
    _inherit = "lgx.job.charge"

    customs_declaration_id = fields.Many2one("lgx.customs.declaration", "Deklarasi Pabean",
                                             index=True, ondelete="set null")
