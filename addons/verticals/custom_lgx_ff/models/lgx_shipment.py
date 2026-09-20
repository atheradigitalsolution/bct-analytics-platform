# -*- coding: utf-8 -*-
"""Shipment: satu pengangkutan, dan kemungkinan induk dari banyak shipment lain.

KONSOLIDASI
-----------
`is_master` + `parent_shipment_id` memodelkan dua lapis dokumen yang membuat
forwarding menguntungkan. Master memegang MBL dan biaya freight yang DIBELI dari
carrier; house memegang HBL dan pendapatan per pelanggan. P&L konsol karena itu
adalah pendapatan seluruh house dikurangi biaya pada master — bukan penjumlahan
margin masing-masing, yang akan menghitung biaya master sebanyak jumlah house-nya.

BERAT YANG DITAGIH
------------------
Angkutan menagih berdasarkan yang LEBIH BESAR antara berat aktual dan berat
volumetrik, karena barang ringan yang memakan ruang tetap menghabiskan kapasitas.
Faktornya datang dari rate card, tidak pernah dari kode, dan hasilnya menyebutkan
dasar mana yang menang supaya staf yang melihat angka lebih besar dari berat
aktual tahu itu karena volume dan bukan karena salah input.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LgxShipment(models.Model):
    _name = "lgx.shipment"
    _description = "Shipment"
    _order = "etd desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread", "mail.activity.mixin"]
    _lgx_sequence_code = "lgx.shipment"

    job_id = fields.Many2one("lgx.job", "Job", required=True, ondelete="cascade",
                             index=True, tracking=True)
    company_id = fields.Many2one(related="job_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="job_id.currency_id", readonly=True)

    is_master = fields.Boolean("Master (Konsolidasi)", tracking=True)
    parent_shipment_id = fields.Many2one("lgx.shipment", "Master Shipment",
                                         domain="[('is_master','=',True)]", index=True)
    child_shipment_ids = fields.One2many("lgx.shipment", "parent_shipment_id", "House Shipment")
    house_count = fields.Integer("Jumlah House", compute="_compute_consol", store=True)

    transport_mode = fields.Selection(
        [("sea", "Laut"), ("air", "Udara"), ("land", "Darat"), ("rail", "Kereta"),
         ("multimodal", "Multimoda")],
        string="Moda", required=True, default="sea", tracking=True,
    )
    direction = fields.Selection(
        [("import", "Impor"), ("export", "Ekspor"), ("domestic", "Domestik"),
         ("cross_trade", "Cross Trade")],
        string="Arah", required=True, default="import",
    )
    load_type = fields.Selection(
        [("fcl", "FCL"), ("lcl", "LCL"), ("bulk", "Bulk"), ("breakbulk", "Breakbulk"),
         ("air", "Air Cargo"), ("courier", "Courier")],
        string="Jenis Muatan", required=True, default="fcl",
    )

    carrier_id = fields.Many2one("res.partner", "Carrier", domain="[('lgx_is_carrier','=',True)]")
    vessel_name = fields.Char("Nama Kapal")
    voyage_no = fields.Char("Nomor Voyage")
    flight_no = fields.Char("Nomor Penerbangan")

    master_doc_no = fields.Char("MBL / MAWB", tracking=True, index=True)
    house_doc_no = fields.Char("HBL / HAWB", tracking=True, index=True, copy=False)
    doc_label_master = fields.Char("Label Master", compute="_compute_doc_labels")
    doc_label_house = fields.Char("Label House", compute="_compute_doc_labels")

    pol_id = fields.Many2one("lgx.location", "Port of Loading")
    pod_id = fields.Many2one("lgx.location", "Port of Discharge")
    place_of_receipt_id = fields.Many2one("lgx.location", "Tempat Terima")
    place_of_delivery_id = fields.Many2one("lgx.location", "Tempat Serah")

    etd = fields.Date("ETD", tracking=True)
    eta = fields.Date("ETA", tracking=True)
    atd = fields.Date("ATD")
    ata = fields.Date("ATA")

    gross_weight_kg = fields.Float("Berat Kotor (kg)", compute="_compute_cargo", store=True,
                                   readonly=False)
    volume_cbm = fields.Float("Volume (CBM)", compute="_compute_cargo", store=True, readonly=False)
    volume_cm3 = fields.Float("Volume (cm³)", compute="_compute_cargo", store=True)
    package_count = fields.Integer("Jumlah Koli", compute="_compute_cargo", store=True, readonly=False)
    chargeable_weight = fields.Float("Berat yang Ditagih", compute="_compute_chargeable_weight",
                                     store=True)
    chargeable_basis = fields.Selection(
        [("berat", "Berat aktual"), ("volume", "Volume")],
        string="Dasar yang Menang", compute="_compute_chargeable_weight", store=True,
        help="Ditampilkan supaya angka yang lebih besar dari berat aktual tidak "
             "terbaca sebagai salah input.",
    )
    chargeable_uom = fields.Char("Satuan Tagih", compute="_compute_chargeable_weight", store=True)
    rate_card_id = fields.Many2one(
        "lgx.rate.card", "Rate Card Perhitungan",
        help="Sumber faktor volumetrik dan aturan pembulatan. Kosong berarti "
             "memakai parameter sistem.",
    )

    commodity_id = fields.Many2one("lgx.commodity", "Komoditas")
    hs_code_note = fields.Char("Catatan HS Code")
    marks_and_numbers = fields.Text("Marks & Numbers")
    goods_description = fields.Text("Uraian Barang")

    container_ids = fields.One2many("lgx.container", "shipment_id", "Kontainer")
    container_count = fields.Integer("Jumlah Kontainer", compute="_compute_consol", store=True)
    teu_total = fields.Float("Total TEU", compute="_compute_consol", store=True)
    package_ids = fields.One2many("lgx.package", "shipment_id", "Kemasan")
    milestone_ids = fields.One2many("lgx.milestone", "shipment_id", "Milestone")

    consol_revenue = fields.Monetary("Pendapatan Konsol", compute="_compute_consol_pnl")
    consol_cost = fields.Monetary("Biaya Konsol", compute="_compute_consol_pnl")
    consol_margin = fields.Monetary("Margin Konsol", compute="_compute_consol_pnl")
    fill_rate = fields.Float("Tingkat Pengisian (%)", compute="_compute_consol_pnl")

    state = fields.Selection(
        [("draft", "Draf"), ("booked", "Di-booking"), ("in_transit", "Dalam Perjalanan"),
         ("arrived", "Tiba"), ("released", "Dikeluarkan"), ("completed", "Selesai"),
         ("cancelled", "Batal")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )

    _eta_after_etd = models.Constraint(
        "check(etd is null or eta is null or eta >= etd)",
        "ETA shipment tidak boleh lebih awal dari ETD.",
    )

    # --- computes ----------------------------------------------------------
    @api.depends("transport_mode")
    def _compute_doc_labels(self):
        for shipment in self:
            if shipment.transport_mode == "air":
                shipment.doc_label_master = "MAWB"
                shipment.doc_label_house = "HAWB"
            else:
                shipment.doc_label_master = "Master B/L"
                shipment.doc_label_house = "House B/L"

    @api.depends("package_ids.gross_weight_kg", "package_ids.volume_cbm",
                 "package_ids.volume_cm3", "package_ids.quantity")
    def _compute_cargo(self):
        for shipment in self:
            if not shipment.package_ids:
                continue
            shipment.gross_weight_kg = sum(shipment.package_ids.mapped("gross_weight_kg"))
            shipment.volume_cbm = sum(shipment.package_ids.mapped("volume_cbm"))
            shipment.volume_cm3 = sum(shipment.package_ids.mapped("volume_cm3"))
            shipment.package_count = sum(shipment.package_ids.mapped("quantity"))

    @api.depends("gross_weight_kg", "volume_cbm", "volume_cm3", "transport_mode",
                 "load_type", "rate_card_id")
    def _compute_chargeable_weight(self):
        for shipment in self:
            card = shipment.rate_card_id
            if card:
                weight, basis = card.lgx_chargeable_weight(
                    shipment.gross_weight_kg, shipment.volume_cbm,
                    shipment.volume_cm3, mode=shipment.transport_mode,
                )
            else:
                weight, basis = shipment._fallback_chargeable_weight()
            shipment.chargeable_weight = weight
            shipment.chargeable_basis = basis
            shipment.chargeable_uom = "kg" if shipment.transport_mode == "air" else "W/M"

    def _fallback_chargeable_weight(self):
        """Perhitungan tanpa rate card, memakai PARAMETER SISTEM.

        Bukan konstanta di kode: pembagi 6000 dan pembulatan 0,5 kg adalah default
        IATA yang boleh berbeda per carrier, dan setiap carrier baru tidak boleh
        menjadi rilis modul.
        """
        self.ensure_one()
        import math
        params = self.env["ir.config_parameter"].sudo()
        if self.transport_mode == "air":
            divisor = float(params.get_param("lgx.volumetric_divisor_air", 6000.0)) or 6000.0
            rounding = float(params.get_param("lgx.air_weight_rounding_kg", 0.5))
            volumetric = (self.volume_cm3 or (self.volume_cbm or 0.0) * 1_000_000.0) / divisor
            weight = max(self.gross_weight_kg or 0.0, volumetric)
            basis = "volume" if volumetric > (self.gross_weight_kg or 0.0) else "berat"
            if rounding:
                weight = math.ceil(weight / rounding) * rounding
            return weight, basis
        tonnage = (self.gross_weight_kg or 0.0) / 1000.0
        cbm = self.volume_cbm or 0.0
        return max(tonnage, cbm), ("volume" if cbm > tonnage else "berat")

    @api.depends("child_shipment_ids", "container_ids", "container_ids.container_type_id")
    def _compute_consol(self):
        for shipment in self:
            shipment.house_count = len(shipment.child_shipment_ids)
            shipment.container_count = len(shipment.container_ids)
            shipment.teu_total = sum(shipment.container_ids.mapped("container_type_id.teu"))

    @api.depends("is_master", "child_shipment_ids.job_id", "job_id.charge_ids.amount_effective")
    def _compute_consol_pnl(self):
        """P&L konsol: pendapatan SELURUH house dikurangi biaya pada MASTER.

        Bukan penjumlahan margin per house — itu akan menghitung biaya master
        sebanyak jumlah house-nya, dan konsol yang sebenarnya rugi akan tampak
        untung berlipat.
        """
        for shipment in self:
            if not shipment.is_master:
                shipment.consol_revenue = shipment.consol_cost = 0.0
                shipment.consol_margin = shipment.fill_rate = 0.0
                continue
            house_jobs = shipment.child_shipment_ids.mapped("job_id")
            revenue = sum(house_jobs.mapped("revenue_total"))
            cost = sum(shipment.job_id.charge_ids.filtered(
                lambda c: c.kind == "cost" and c.nature == "service"
            ).mapped("amount_effective"))
            capacity = sum(shipment.container_ids.mapped("container_type_id.internal_volume_cbm"))
            used = sum(shipment.child_shipment_ids.mapped("volume_cbm"))
            shipment.consol_revenue = revenue
            shipment.consol_cost = cost
            shipment.consol_margin = revenue - cost
            shipment.fill_rate = (used / capacity * 100.0) if capacity else 0.0

    # --- validasi ----------------------------------------------------------
    @api.constrains("is_master", "parent_shipment_id")
    def _check_consolidation(self):
        for shipment in self:
            if shipment.is_master and shipment.parent_shipment_id:
                raise ValidationError(_(
                    "Shipment %s ditandai master sekaligus menggantung pada master lain. "
                    "Konsolidasi berlapis dua tidak dimodelkan di sini.", shipment.name,
                ))
            if shipment.parent_shipment_id == shipment:
                raise ValidationError(_("Shipment tidak boleh menjadi master bagi dirinya sendiri."))

    @api.constrains("direction", "load_type", "container_ids", "state")
    def _check_vgm_for_sea_export(self):
        """VGM wajib untuk ekspor laut — diperiksa saat shipment dinyatakan berangkat."""
        for shipment in self:
            if shipment.transport_mode != "sea" or shipment.direction != "export":
                continue
            if shipment.state not in ("in_transit", "arrived", "released", "completed"):
                continue
            missing = shipment.container_ids.filtered(lambda c: not c.vgm_weight)
            if missing:
                raise ValidationError(_(
                    "Ekspor laut menuntut VGM untuk setiap kontainer. Belum terisi: %s.",
                    ", ".join(missing.mapped("container_no")),
                ))

    # --- alur --------------------------------------------------------------
    def action_book(self):
        self.filtered(lambda s: s.state == "draft").write({"state": "booked"})
        return True

    def action_depart(self):
        for shipment in self:
            shipment.write({"state": "in_transit", "atd": shipment.atd or fields.Date.context_today(shipment)})
            code = "flight_departed" if shipment.transport_mode == "air" else "vessel_departed"
            shipment.job_id.lgx_log_milestone(code, source="manual")
        return True

    def action_arrive(self):
        for shipment in self:
            shipment.write({"state": "arrived", "ata": shipment.ata or fields.Date.context_today(shipment)})
            code = "flight_arrived" if shipment.transport_mode == "air" else "vessel_arrived"
            shipment.job_id.lgx_log_milestone(code, source="manual")
        return True

    def action_complete(self):
        for shipment in self:
            if shipment.is_master:
                pending = shipment.child_shipment_ids.filtered(
                    lambda s: s.state not in ("completed", "cancelled"))
                if pending:
                    raise UserError(_(
                        "Master shipment %s tidak dapat ditutup selama %s house belum selesai: %s.",
                        shipment.name, len(pending), ", ".join(pending.mapped("name")),
                    ))
            shipment.state = "completed"
        return True

    @api.onchange("job_id")
    def _onchange_job(self):
        for shipment in self:
            job = shipment.job_id
            if not job:
                continue
            shipment.transport_mode = job.transport_mode
            shipment.direction = job.direction or "import"
            shipment.etd = job.etd
            shipment.eta = job.eta

    @api.depends("name", "master_doc_no", "house_doc_no")
    def _compute_display_name(self):
        for shipment in self:
            doc = shipment.house_doc_no or shipment.master_doc_no
            shipment.display_name = f"{shipment.name} — {doc}" if doc else shipment.name
