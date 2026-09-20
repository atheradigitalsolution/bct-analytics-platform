# -*- coding: utf-8 -*-
"""Drug master data, layered onto product.template."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HmsMedicineIngredient(models.Model):
    _name = "hms.medicine.ingredient"
    _description = "Kandungan Zat Aktif"

    medicine_id = fields.Many2one("hms.medicine", required=True, ondelete="cascade")
    ingredient_id = fields.Many2one("hms.ingredient", "Zat Aktif", required=True)
    strength = fields.Float("Kekuatan", digits=(12, 3))
    strength_unit = fields.Char("Satuan Kekuatan", default="mg")


class HmsMedicine(models.Model):
    """Clinical attributes of a product that happens to be a medicine.

    Kept beside product.template rather than inside it: a hospital's product
    catalogue also holds linen, food and spare parts, and pushing forty drug
    columns onto every one of those makes the product form unusable.
    """
    _name = "hms.medicine"
    _description = "Obat / BHP"
    _order = "generic_name"
    _rec_names_search = ["generic_name", "brand_name"]

    product_tmpl_id = fields.Many2one("product.template", "Produk", required=True,
                                      ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", "Varian Produk",
                                 compute="_compute_product_id", store=True)
    item_type = fields.Selection(
        [("drug", "Obat"), ("consumable", "BHP"), ("medical_device", "Alat Kesehatan"),
         ("reagent", "Reagen"), ("nutrition", "Nutrisi")],
        required=True, default="drug", index=True,
    )
    generic_name = fields.Char("Nama Generik", required=True, index=True)
    brand_name = fields.Char("Nama Dagang")
    ingredient_ids = fields.One2many("hms.medicine.ingredient", "medicine_id", "Zat Aktif")
    manufacturer_id = fields.Many2one("res.partner", "Pabrikan")
    dosage_form_id = fields.Many2one("hms.dosage.form", "Bentuk Sediaan")
    route_ids = fields.Many2many("hms.route", string="Rute Pemberian")
    strength_display = fields.Char("Kekuatan", help="Contoh: 500 mg, 5 mg/5 mL")
    unit_dispense_id = fields.Many2one("uom.uom", "Satuan Penyerahan")
    pack_size = fields.Integer("Isi Kemasan", default=1)

    kfa_code = fields.Char("Kode KFA", help="Kamus Farmasi & Alkes untuk SATUSEHAT.")
    bpom_reg_no = fields.Char("NIE BPOM")
    atc_code = fields.Char("Kode ATC")
    drug_class_id = fields.Many2one("hms.drug.class", "Kelas Terapi")

    is_generic = fields.Boolean("Generik")
    is_formularium_national = fields.Boolean("Fornas")
    is_formularium_hospital = fields.Boolean("Formularium RS")
    is_high_alert = fields.Boolean(
        "High Alert",
        help="Wajib double-check oleh petugas kedua sebelum diserahkan atau diberikan.",
    )
    is_lasa = fields.Boolean("LASA", help="Look-Alike Sound-Alike.")
    lasa_group = fields.Char("Kelompok LASA")
    display_tallman = fields.Char("Penulisan Tallman", help="Contoh: hidrALAZINE vs hidrOXYzine")
    is_narcotic = fields.Boolean("Narkotika")
    is_psychotropic = fields.Boolean("Psikotropika")
    is_precursor = fields.Boolean("Prekursor")
    is_antibiotic = fields.Boolean("Antibiotik")
    antibiotic_category = fields.Selection(
        [("access", "Access"), ("watch", "Watch"), ("reserve", "Reserve")],
        string="Kategori AWaRe",
    )
    is_cold_chain = fields.Boolean("Rantai Dingin")
    storage_temp_min = fields.Float("Suhu Min (°C)")
    storage_temp_max = fields.Float("Suhu Maks (°C)")

    is_prn_allowed = fields.Boolean("Boleh PRN", default=True)
    default_sig = fields.Char("Aturan Pakai Default")
    default_dose = fields.Float("Dosis Default")
    default_frequency_id = fields.Many2one("hms.frequency", "Frekuensi Default")
    default_duration_days = fields.Integer("Durasi Default (hari)")
    max_dose_daily = fields.Float("Dosis Maksimum Harian")
    max_dose_unit = fields.Char("Satuan Dosis Maksimum")
    pregnancy_category = fields.Selection(
        [("a", "A"), ("b", "B"), ("c", "C"), ("d", "D"), ("x", "X")],
        string="Kategori Kehamilan",
    )
    contraindication_note = fields.Text("Kontraindikasi")
    renal_adjust = fields.Boolean("Perlu Penyesuaian Ginjal")
    hepatic_adjust = fields.Boolean("Perlu Penyesuaian Hati")

    requires_prescription = fields.Boolean("Perlu Resep", default=True)
    bpjs_covered = fields.Boolean("Ditanggung BPJS")
    bpjs_restriction = fields.Char("Restriksi BPJS")
    price_hna = fields.Float("HNA")
    price_het = fields.Float("HET")
    shelf_location = fields.Char("Lokasi Rak")
    label_note = fields.Char("Catatan Etiket")
    state = fields.Selection(
        [("active", "Aktif"), ("discontinued", "Tidak Dipakai Lagi")],
        default="active", required=True,
    )
    active = fields.Boolean(default=True)

    _product_uniq = models.Constraint(
        "unique(product_tmpl_id)", "Satu produk hanya boleh punya satu data obat.",
    )

    @api.depends("product_tmpl_id")
    def _compute_product_id(self):
        for rec in self:
            rec.product_id = rec.product_tmpl_id.product_variant_id

    @api.depends("generic_name", "brand_name", "strength_display")
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.display_tallman or rec.generic_name]
            if rec.strength_display:
                parts.append(rec.strength_display)
            if rec.brand_name:
                parts.append(f"({rec.brand_name})")
            rec.display_name = " ".join(p for p in parts if p)

    @api.constrains("item_type", "product_tmpl_id")
    def _check_lot_tracking(self):
        """Drugs must be lot-tracked or FEFO cannot work.

        Checked here rather than assumed: a product created through import or
        the plain product form defaults to no tracking, and the failure only
        shows up later as a dispensing that silently ignores expiry.
        """
        for rec in self:
            if rec.item_type != "drug":
                continue
            if rec.product_tmpl_id.tracking != "lot":
                raise ValidationError(
                    _("Obat '%s' harus dilacak per lot (tracking = Lot) agar penyerahan "
                      "dapat memilih lot dengan kedaluwarsa terdekat.") % rec.generic_name
                )
            if not rec.product_tmpl_id.use_expiration_date:
                raise ValidationError(
                    _("Obat '%s' harus mengaktifkan tanggal kedaluwarsa. Tanpa itu "
                      "penyerahan FEFO tidak punya dasar pengurutan.") % rec.generic_name
                )

    def ingredient_ids_all(self):
        """Ingredient records, for allergy screening."""
        self.ensure_one()
        return self.ingredient_ids.mapped("ingredient_id")


class ProductTemplate(models.Model):
    _inherit = "product.template"

    hms_medicine_id = fields.One2many("hms.medicine", "product_tmpl_id", "Data Obat")
    is_medicine = fields.Boolean("Obat / BHP", compute="_compute_is_medicine", store=True)

    @api.depends("hms_medicine_id")
    def _compute_is_medicine(self):
        for tmpl in self:
            tmpl.is_medicine = bool(tmpl.hms_medicine_id)
