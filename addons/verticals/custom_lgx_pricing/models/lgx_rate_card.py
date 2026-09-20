# -*- coding: utf-8 -*-
"""Rate card: satu record per kombinasi lingkup, arah harga, dan periode berlaku.

Arah harga (``buy`` / ``sell``) adalah record terpisah dengan sengaja. Tarif
beli datang dari carrier dan berubah saat kontrak carrier diperbarui; tarif jual
dimiliki penjualan. Satu record dengan dua kolom harga akan membuat pembaruan
tarif carrier menyentuh harga yang sudah dijanjikan ke pelanggan, dan tidak ada
cara memutar kembali penawaran yang sudah terkirim.

Versi tidak menimpa: ``supersedes_id`` menunjuk versi lama, yang tetap hidup
supaya penawaran yang sudah terbit dapat direkonstruksi persis seperti saat
dikirim.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PRICING_BASES = [
    ("per_kg", "Per Kg"),
    ("per_cbm", "Per CBM"),
    ("per_container", "Per Kontainer"),
    ("per_shipment", "Per Shipment"),
    ("per_bl", "Per B/L"),
    ("per_trip", "Per Trip"),
    ("per_ton", "Per Ton"),
    ("per_km", "Per Km"),
    ("per_ritase", "Per Ritase"),
    ("per_pallet", "Per Pallet"),
    ("per_order_line", "Per Baris Order"),
    ("flat", "Flat"),
]


class LgxRateCard(models.Model):
    _name = "lgx.rate.card"
    _description = "Rate Card"
    _order = "direction, valid_from desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char("Nama", required=True, tracking=True)
    code = fields.Char("Kode", index=True)
    direction = fields.Selection(
        [("buy", "Beli (dari carrier/vendor)"), ("sell", "Jual (ke pelanggan)")],
        string="Arah", required=True, default="sell", tracking=True, index=True,
    )
    partner_id = fields.Many2one(
        "res.partner", "Mitra", index=True,
        help="Carrier untuk tarif beli, pelanggan untuk tarif jual. "
             "Kosong berarti tarif umum yang berlaku bila tidak ada yang lebih khusus.",
    )
    transport_mode = fields.Selection(
        [("sea", "Laut"), ("air", "Udara"), ("land", "Darat"), ("rail", "Kereta"), ("any", "Semua")],
        string="Moda", required=True, default="sea",
    )
    load_type = fields.Selection(
        [("fcl", "FCL"), ("lcl", "LCL"), ("bulk", "Bulk"), ("breakbulk", "Breakbulk"),
         ("air", "Air Cargo"), ("courier", "Courier"), ("ftl", "FTL"), ("ltl", "LTL"), ("any", "Semua")],
        string="Jenis Muatan", default="any", required=True,
    )
    origin_id = fields.Many2one("lgx.location", "Asal")
    destination_id = fields.Many2one("lgx.location", "Tujuan")
    origin_country_id = fields.Many2one("res.country", "Negara Asal",
                                        help="Diisi untuk tarif zona, bila asal tidak spesifik simpul.")
    destination_country_id = fields.Many2one("res.country", "Negara Tujuan")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    valid_from = fields.Date("Berlaku Dari", required=True, default=fields.Date.context_today, index=True)
    valid_to = fields.Date("Berlaku Sampai", index=True)
    version = fields.Integer("Versi", default=1, readonly=True)
    supersedes_id = fields.Many2one("lgx.rate.card", "Menggantikan", readonly=True, copy=False)
    superseded_by_id = fields.Many2one("lgx.rate.card", "Digantikan Oleh", readonly=True, copy=False)

    volumetric_divisor = fields.Float(
        "Pembagi Volumetrik", default=6000.0,
        help="Berat volumetrik udara = (P × L × T dalam cm) / pembagi ini. "
             "6000 adalah standar IATA, tetapi carrier boleh berbeda — itulah "
             "sebabnya angka ini hidup di sini, bukan di kode.",
    )
    weight_rounding = fields.Float(
        "Pembulatan Berat (kg)", default=0.5,
        help="Berat yang ditagih dibulatkan NAIK ke kelipatan ini. 0 berarti tanpa pembulatan.",
    )
    minimum_charge = fields.Monetary("Tagihan Minimum Rate Card", currency_field="currency_id")

    # copy=True eksplisit: One2many di Odoo TIDAK ikut tersalin secara default,
    # dan versi baru rate card tanpa baris tarif adalah record yang tidak bisa
    # diaktifkan sama sekali.
    line_ids = fields.One2many("lgx.rate.card.line", "rate_card_id", "Baris Tarif", copy=True)
    surcharge_ids = fields.One2many("lgx.rate.surcharge", "rate_card_id", "Surcharge", copy=True)
    state = fields.Selection(
        [("draft", "Draf"), ("active", "Aktif"), ("expired", "Kedaluwarsa")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Text("Catatan")

    _valid_period = models.Constraint(
        "check(valid_to is null or valid_to >= valid_from)",
        "Tanggal 'berlaku sampai' tidak boleh lebih awal dari 'berlaku dari'.",
    )
    _divisor_positive = models.Constraint(
        "check(volumetric_divisor > 0)", "Pembagi volumetrik harus lebih besar dari nol.",
    )

    def action_activate(self):
        for card in self:
            if not card.line_ids:
                raise UserError(_("Rate card %s belum punya satu pun baris tarif.", card.name))
            card.state = "active"
        return True

    def action_expire(self):
        self.write({"state": "expired"})
        return True

    def action_new_version(self):
        """Terbitkan versi baru; versi lama TETAP hidup.

        Penawaran yang sudah terbit menyimpan referensi ke versi yang dipakainya.
        Menimpa record lama akan membuat penawaran lama tidak dapat
        direkonstruksi — dan penawaran yang tidak dapat direkonstruksi adalah
        penawaran yang tidak dapat dipertahankan saat pelanggan menagih janji.
        """
        self.ensure_one()
        new = self.copy({
            "name": f"{self.name} (v{self.version + 1})",
            "version": self.version + 1,
            "supersedes_id": self.id,
            "state": "draft",
            "valid_from": fields.Date.context_today(self),
        })
        self.superseded_by_id = new
        return {
            "type": "ir.actions.act_window",
            "res_model": "lgx.rate.card",
            "res_id": new.id,
            "view_mode": "form",
        }

    @api.model
    def lgx_find_applicable(self, direction, on_date, partner=None, transport_mode=None,
                            load_type=None, origin=None, destination=None, any_partner=False):
        """Rate card yang berlaku, yang paling khusus lebih dulu.

        Urutannya sengaja: tarif khusus mitra mengalahkan tarif umum, dan tarif
        dengan rute persis mengalahkan tarif zona. Mengembalikan recordset yang
        SUDAH terurut supaya pemanggil cukup mengambil yang pertama cocok.
        """
        domain = [
            ("direction", "=", direction),
            ("state", "=", "active"),
            ("valid_from", "<=", on_date),
            "|", ("valid_to", "=", False), ("valid_to", ">=", on_date),
        ]
        if transport_mode:
            domain += ["|", ("transport_mode", "=", transport_mode), ("transport_mode", "=", "any")]
        if load_type:
            domain += ["|", ("load_type", "=", load_type), ("load_type", "=", "any")]
        # `any_partner` ada untuk sisi BELI. Saat penawaran disusun, carrier
        # yang akan dipakai belum tentu sudah dipilih — memaksa tarif beli harus
        # tarif umum berarti setiap kontrak carrier yang benar-benar dimiliki
        # perusahaan tidak akan pernah terpakai, dan harga beli jatuh ke nol.
        # Harga beli nol membuat margin tampak 100%, dan penawaran itu dikirim.
        if any_partner:
            pass
        elif partner:
            domain += ["|", ("partner_id", "=", partner.id), ("partner_id", "=", False)]
        else:
            domain += [("partner_id", "=", False)]
        cards = self.search(domain)
        if origin:
            cards = cards.filtered(
                lambda c: not c.origin_id or c.origin_id == origin
                or (c.origin_country_id and c.origin_country_id == origin.country_id)
            )
        if destination:
            cards = cards.filtered(
                lambda c: not c.destination_id or c.destination_id == destination
                or (c.destination_country_id and c.destination_country_id == destination.country_id)
            )
        return cards.sorted(
            key=lambda c: (
                0 if c.partner_id else 1,
                0 if c.origin_id else 1,
                0 if c.destination_id else 1,
                -(c.valid_from.toordinal() if c.valid_from else 0),
            )
        )

    def lgx_chargeable_weight(self, gross_weight_kg, volume_cbm=0.0, volume_cm3=0.0, mode=None):
        """Berat yang ditagih, dan DASAR MANA YANG MENANG.

        Mengembalikan (berat, dasar) — bukan hanya angkanya — karena staf operasi
        yang melihat angka lebih besar dari berat aktual perlu tahu itu karena
        volume, bukan karena salah input.
        """
        self.ensure_one()
        mode = mode or self.transport_mode
        if mode == "air":
            volumetric = (volume_cm3 / self.volumetric_divisor) if volume_cm3 else 0.0
            if not volumetric and volume_cbm:
                volumetric = (volume_cbm * 1_000_000.0) / self.volumetric_divisor
            weight = max(gross_weight_kg or 0.0, volumetric)
            basis = "volume" if volumetric > (gross_weight_kg or 0.0) else "berat"
        else:
            # Laut LCL: W/M — ton versus CBM, mana yang lebih besar.
            tonnage = (gross_weight_kg or 0.0) / 1000.0
            weight = max(tonnage, volume_cbm or 0.0)
            basis = "volume" if (volume_cbm or 0.0) > tonnage else "berat"
        if self.weight_rounding:
            import math
            weight = math.ceil(weight / self.weight_rounding) * self.weight_rounding
        return weight, basis


class LgxRateCardLine(models.Model):
    _name = "lgx.rate.card.line"
    _description = "Baris Rate Card"
    _order = "rate_card_id, sequence, id"

    sequence = fields.Integer(default=10)
    rate_card_id = fields.Many2one("lgx.rate.card", "Rate Card", required=True,
                                   ondelete="cascade", index=True)
    charge_code_id = fields.Many2one("lgx.charge.code", "Kode Charge", required=True)
    basis = fields.Selection(PRICING_BASES, string="Dasar", required=True, default="per_container")
    container_type_id = fields.Many2one("lgx.container.type", "Tipe Kontainer",
                                        help="Diisi bila dasar per kontainer.")
    price = fields.Monetary("Harga", currency_field="currency_id")
    currency_id = fields.Many2one(related="rate_card_id.currency_id", readonly=True)
    minimum_charge = fields.Monetary("Tagihan Minimum", currency_field="currency_id")
    break_ids = fields.One2many("lgx.rate.break", "rate_line_id", "Tarif Berjenjang")

    def lgx_price_for(self, quantity):
        """Harga satuan untuk kuantitas tertentu, memperhitungkan jenjang.

        Jenjang dipilih dari ambang TERBESAR yang masih di bawah kuantitas, bukan
        yang pertama cocok — urutan baris di layar tidak boleh menentukan harga.
        """
        self.ensure_one()
        price = self.price
        applicable = self.break_ids.filtered(lambda b: quantity >= b.min_quantity)
        if applicable:
            price = applicable.sorted("min_quantity")[-1].price
        return price

    def lgx_amount_for(self, quantity):
        """Nilai baris untuk kuantitas tertentu, setelah tagihan minimum."""
        self.ensure_one()
        amount = self.lgx_price_for(quantity) * (quantity or 0.0)
        return max(amount, self.minimum_charge or 0.0)


class LgxRateBreak(models.Model):
    _name = "lgx.rate.break"
    _description = "Jenjang Tarif"
    _order = "rate_line_id, min_quantity"

    rate_line_id = fields.Many2one("lgx.rate.card.line", "Baris Tarif", required=True,
                                   ondelete="cascade", index=True)
    min_quantity = fields.Float("Kuantitas Minimum", required=True)
    price = fields.Monetary("Harga", currency_field="currency_id")
    currency_id = fields.Many2one(related="rate_line_id.currency_id", readonly=True)

    _min_qty_non_negative = models.Constraint(
        "check(min_quantity >= 0)", "Kuantitas minimum tidak boleh negatif.",
    )


class LgxRateSurcharge(models.Model):
    _name = "lgx.rate.surcharge"
    _description = "Surcharge"
    _order = "rate_card_id, sequence, id"

    sequence = fields.Integer(default=10)
    rate_card_id = fields.Many2one("lgx.rate.card", "Rate Card", required=True,
                                   ondelete="cascade", index=True)
    charge_code_id = fields.Many2one("lgx.charge.code", "Kode Charge", required=True)
    calculation = fields.Selection(
        [("fixed", "Nilai Tetap"), ("percent_of_base", "Persen dari Dasar"), ("per_unit", "Per Unit")],
        string="Perhitungan", required=True, default="fixed",
    )
    value = fields.Float("Nilai", required=True)
    applies_to_ids = fields.Many2many(
        "lgx.charge.code", "lgx_surcharge_applies_rel", "surcharge_id", "charge_code_id",
        string="Berlaku Atas",
        help="Untuk perhitungan 'persen dari dasar': baris mana yang menjadi dasarnya. "
             "Kosong berarti seluruh baris freight.",
    )
    valid_from = fields.Date("Berlaku Dari")
    valid_to = fields.Date("Berlaku Sampai")
    currency_id = fields.Many2one(related="rate_card_id.currency_id", readonly=True)

    @api.constrains("calculation", "value")
    def _check_value(self):
        for rec in self:
            if rec.calculation == "percent_of_base" and not (-100.0 <= rec.value <= 1000.0):
                raise ValidationError(_(
                    "Surcharge persentase %s%% di luar rentang yang masuk akal.", rec.value,
                ))
