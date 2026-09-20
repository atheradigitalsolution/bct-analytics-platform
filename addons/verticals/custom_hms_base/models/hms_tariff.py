# -*- coding: utf-8 -*-
"""The tariff engine.

`hms.tariff` is *what* can be charged; `hms.tariff.price` is *how much*, per
care class and per payer, with a validity window. Every module that produces a
charge asks `resolve_price()` — there is exactly one implementation of the
look-up so a lab order and an inpatient room charge can never disagree about
which price was in force on a given date.

The three-way split (jasa sarana / jasa medis / BHP) is stored on the price,
not derived later. Doctors are paid from `amount_medical`, so a bill line that
loses the split cannot be settled without re-pricing history.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_is_zero


class HmsTariffCategory(models.Model):
    _name = "hms.tariff.category"
    _description = "Kategori Tarif"
    _order = "sequence, code"

    code = fields.Char(required=True)
    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    report_section = fields.Selection(
        [("administration", "Administrasi"), ("consultation", "Konsultasi"),
         ("procedure", "Tindakan"), ("nursing", "Keperawatan"), ("room", "Kamar & Visite"),
         ("medicine", "Obat & BHP"), ("lab", "Laboratorium"), ("radiology", "Radiologi"),
         ("other", "Lain-lain")],
        required=True, default="other",
        help="Menentukan pengelompokan di rincian tagihan dan di laporan P&L unit.",
    )
    product_id = fields.Many2one(
        "product.product", "Produk Jurnal",
        help="Produk yang dipakai saat kategori ini menjadi baris invoice.",
    )
    # Keputusan tipe: Char, bukan Selection.
    #
    # Pemetaan ini menuju 18 komponen `tarif_rs` di E-Klaim, tetapi enumerasi
    # resminya BELUM TERVERIFIKASI (gap G23): manual E-Klaim 5.10.x dari klien
    # belum ada. Selection dengan kunci tebakan akan menyimpan nilai yang harus
    # dimigrasi begitu daftar resmi datang — dan migrasi diam-diam pada data
    # pemetaan klaim adalah cara yang bagus untuk salah menagih. Char menerima
    # apa pun yang tertulis di manual resmi tanpa rilis kode, dan kesalahan
    # ketiknya terlihat saat pengiriman klaim pertama, bukan terkubur di ORM.
    # Naikkan ke Selection setelah daftar 18 komponen itu terverifikasi.
    eklaim_component = fields.Char(
        "Komponen tarif_rs E-Klaim",
        help="Nama komponen `tarif_rs` di E-Klaim yang menampung kategori tarif "
             "ini (mis. prosedur_non_bedah, prosedur_bedah, konsultasi, "
             "tenaga_ahli, keperawatan, penunjang, radiologi, laboratorium, "
             "pelayanan_darah, rehabilitasi, kamar, rawat_intensif, obat, "
             "obat_kronis, obat_kemoterapi, alkes, bmhp, sewa_alat). "
             "DAFTAR DI ATAS BELUM TERVERIFIKASI — menunggu manual resmi "
             "E-Klaim 5.10.x dari klien. Isi persis seperti manual, huruf kecil.",
    )
    charge_on = fields.Selection(
        [("done", "Saat order selesai"), ("ordered", "Saat order dibuat")],
        default="done", required=True, string="Waktu Pembebanan",
        help="Kategori seperti administrasi dibebankan saat order dibuat; "
             "tindakan dan penunjang dibebankan setelah dikerjakan.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode kategori tarif harus unik.",
    )


class HmsTariff(models.Model):
    _name = "hms.tariff"
    _description = "Item Tarif"
    _order = "category_id, code"
    _rec_names_search = ["code", "name"]

    code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    category_id = fields.Many2one("hms.tariff.category", "Kategori", required=True)
    report_section = fields.Selection(
        related="category_id.report_section", store=True, readonly=True,
    )
    unit_id = fields.Many2one(
        "hms.unit", "Unit Penyedia",
        help="Unit yang dikreditkan pendapatannya — laboratorium untuk item lab, "
             "bukan poli yang memesan.",
    )
    uom_name = fields.Char("Satuan", default="kali")
    icd9_id = fields.Many2one("hms.icd9", "Kode Prosedur ICD-9-CM")
    loinc_code = fields.Char("Kode LOINC")
    bpjs_procedure_code = fields.Char("Kode Prosedur BPJS")
    duration_minutes = fields.Integer("Durasi (menit)", help="Untuk penjadwalan tindakan.")
    requires_consent = fields.Boolean("Perlu informed consent")
    requires_authorization = fields.Boolean("Perlu otorisasi")
    is_package = fields.Boolean("Paket")
    package_line_ids = fields.One2many("hms.tariff.package.line", "package_id", "Isi Paket")
    price_ids = fields.One2many("hms.tariff.price", "tariff_id", "Daftar Harga")
    product_id = fields.Many2one("product.product", "Produk Jurnal")
    description = fields.Text()
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai")
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint(
        "unique(code)",
        "Kode tarif harus unik.",
    )

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"

    def resolve_price(self, class_id=None, payer_id=None, date=None, cito=False, weekend=False):
        """Return the price row that applies, most specific first.

        Specificity order: (class, payer) → (payer) → (class) → generic. A
        hospital that has negotiated a BPJS price for kelas III expects that
        row to win over its own general kelas III price, and over the BPJS
        price that ignores class.
        """
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        candidates = self.price_ids.filtered(
            lambda p: (not p.valid_from or p.valid_from <= date)
            and (not p.valid_to or p.valid_to >= date)
        )

        def pick(cls, pay):
            return candidates.filtered(
                lambda p: (p.class_id.id or False) == (cls or False)
                and (p.payer_id.id or False) == (pay or False)
            )[:1]

        price = (
            pick(class_id, payer_id) or pick(False, payer_id)
            or pick(class_id, False) or pick(False, False)
        )
        if not price:
            raise ValidationError(
                _("Tarif %(code)s belum memiliki harga yang berlaku pada %(date)s untuk "
                  "kombinasi kelas/penjamin tersebut.")
                % {"code": self.code, "date": date}
            )
        return price.with_context(hms_cito=cito, hms_weekend=weekend)


class HmsTariffPackageLine(models.Model):
    _name = "hms.tariff.package.line"
    _description = "Isi Paket Tarif"

    package_id = fields.Many2one("hms.tariff", required=True, ondelete="cascade")
    tariff_id = fields.Many2one("hms.tariff", "Item", required=True)
    qty = fields.Float("Jumlah", default=1.0)


class HmsTariffPrice(models.Model):
    _name = "hms.tariff.price"
    _description = "Harga Tarif per Kelas & Penjamin"
    _order = "tariff_id, class_id, payer_id"

    tariff_id = fields.Many2one("hms.tariff", required=True, ondelete="cascade", index=True)
    class_id = fields.Many2one(
        "hms.care.class", "Kelas Perawatan",
        help="Kosong berarti berlaku untuk semua kelas.",
    )
    payer_id = fields.Many2one(
        "hms.payer", "Penjamin", help="Kosong berarti berlaku untuk semua penjamin.",
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, readonly=True,
    )
    price_total = fields.Monetary("Total", required=True)
    amount_facility = fields.Monetary("Jasa Sarana")
    amount_medical = fields.Monetary("Jasa Medis")
    amount_consumable = fields.Monetary("BHP")
    amount_other = fields.Monetary("Komponen Lain")
    cito_multiplier = fields.Float("Pengali CITO", default=1.0)
    weekend_multiplier = fields.Float("Pengali Akhir Pekan", default=1.0)
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai")

    _combo_uniq = models.Constraint(
        "unique(tariff_id, class_id, payer_id, valid_from)",
        "Sudah ada harga untuk kombinasi tarif/kelas/penjamin dan tanggal mulai yang sama.",
    )

    @api.constrains("price_total", "amount_facility", "amount_medical",
                    "amount_consumable", "amount_other")
    def _check_components(self):
        """Components must reconcile to the total.

        Enforced rather than computed: hospitals negotiate the total with the
        payer and the split with their doctors, and the two are entered by
        different people. A silent mismatch surfaces months later as a doctor
        fee dispute.
        """
        for rec in self:
            parts = (rec.amount_facility + rec.amount_medical
                     + rec.amount_consumable + rec.amount_other)
            if float_is_zero(parts, precision_digits=2):
                continue  # split not entered yet — allowed while setting up
            if float_compare(parts, rec.price_total, precision_digits=2) != 0:
                raise ValidationError(
                    _("Komponen tarif %(code)s berjumlah %(parts)s, tidak sama dengan total %(total)s.")
                    % {"code": rec.tariff_id.code, "parts": parts, "total": rec.price_total}
                )

    def effective_amounts(self, qty=1.0):
        """Return the amounts actually charged, multipliers applied."""
        self.ensure_one()
        factor = qty
        if self.env.context.get("hms_cito"):
            factor *= self.cito_multiplier or 1.0
        if self.env.context.get("hms_weekend"):
            factor *= self.weekend_multiplier or 1.0
        split_entered = (self.amount_facility + self.amount_medical
                         + self.amount_consumable + self.amount_other)
        if float_is_zero(split_entered, precision_digits=2):
            # No split configured: treat the whole amount as facility revenue
            # so the doctor fee accrual stays zero instead of guessing.
            facility, medical, consumable, other = self.price_total, 0.0, 0.0, 0.0
        else:
            facility = self.amount_facility
            medical = self.amount_medical
            consumable = self.amount_consumable
            other = self.amount_other
        return {
            "unit_price": self.price_total,
            "price_subtotal": self.price_total * factor,
            "amount_facility": facility * factor,
            "amount_medical": medical * factor,
            "amount_consumable": consumable * factor,
            "amount_other": other * factor,
        }
