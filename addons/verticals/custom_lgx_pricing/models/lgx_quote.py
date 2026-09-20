# -*- coding: utf-8 -*-
"""Penawaran, dan konversinya menjadi job.

Keputusan 7 di Fase 0 bertanya: ``lgx.quote`` model sendiri, atau pakai
``sale.order`` langsung? Jawabannya model sendiri, dengan satu alasan yang
menentukan: setiap baris penawaran logistik membawa harga BELI dan harga JUAL
berdampingan, dan ``sale.order.line`` tidak punya tempat untuk harga beli.
Menempelkannya sebagai field tambahan berarti setiap laporan penjualan standar
Odoo diam-diam salah menjumlahkan.

Konversi membuat DUA baris charge per baris penawaran. Itulah yang membuat
akrual biaya terbentuk sejak job lahir.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.custom_lgx_job.models.lgx_job import JOB_TYPES, TRANSPORT_MODES


class LgxQuote(models.Model):
    _name = "lgx.quote"
    _description = "Penawaran Logistik"
    _order = "create_date desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread", "mail.activity.mixin"]
    _lgx_sequence_code = "lgx.quote"

    customer_id = fields.Many2one("res.partner", "Pelanggan", required=True, tracking=True, index=True)
    salesperson_id = fields.Many2one("res.users", "Penjual", default=lambda s: s.env.user, tracking=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    operating_unit_id = fields.Many2one("operating.unit", "Cabang")
    date = fields.Date("Tanggal", default=fields.Date.context_today, required=True)
    validity_date = fields.Date("Berlaku Sampai", required=True,
                                default=lambda s: fields.Date.add(fields.Date.context_today(s), days=14))

    job_type = fields.Selection(JOB_TYPES, "Jenis Job", required=True, default="ff_import")
    transport_mode = fields.Selection(TRANSPORT_MODES, "Moda", required=True, default="sea")
    load_type = fields.Selection(
        [("fcl", "FCL"), ("lcl", "LCL"), ("bulk", "Bulk"), ("breakbulk", "Breakbulk"),
         ("air", "Air Cargo"), ("courier", "Courier"), ("ftl", "FTL"), ("ltl", "LTL"), ("any", "Lainnya")],
        string="Jenis Muatan", default="fcl", required=True,
    )
    origin_id = fields.Many2one("lgx.location", "Asal")
    destination_id = fields.Many2one("lgx.location", "Tujuan")
    incoterm_id = fields.Many2one("account.incoterms", "Incoterm")
    commodity_id = fields.Many2one("lgx.commodity", "Komoditas")

    sell_rate_card_id = fields.Many2one("lgx.rate.card", "Rate Card Jual",
                                        domain="[('direction','=','sell')]")
    buy_rate_card_id = fields.Many2one("lgx.rate.card", "Rate Card Beli",
                                       domain="[('direction','=','buy')]")
    contract_id = fields.Many2one("lgx.contract", "Kontrak", domain="[('partner_id','=',customer_id)]")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)

    line_ids = fields.One2many("lgx.quote.line", "quote_id", "Baris")
    revenue_total = fields.Monetary("Total Jual", compute="_compute_totals", store=True)
    cost_total = fields.Monetary("Total Beli", compute="_compute_totals", store=True)
    margin = fields.Monetary("Margin", compute="_compute_totals", store=True)
    margin_pct = fields.Float("Margin (%)", compute="_compute_totals", store=True, digits=(16, 2))
    has_manual_price = fields.Boolean("Ada Harga Manual", compute="_compute_totals", store=True)

    approval_user_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True, copy=False)
    approval_reason = fields.Char("Alasan Persetujuan Margin", copy=False)

    state = fields.Selection(
        [("draft", "Draf"), ("sent", "Terkirim"), ("accepted", "Diterima"),
         ("rejected", "Ditolak"), ("expired", "Kedaluwarsa")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    job_id = fields.Many2one("lgx.job", "Job", readonly=True, copy=False,
                             help="Terisi setelah konversi; mencegah konversi ganda.")
    note = fields.Text("Catatan")

    _validity_after_date = models.Constraint(
        "check(validity_date >= date)", "Masa berlaku penawaran tidak boleh sebelum tanggalnya.",
    )

    @api.depends("line_ids.sell_amount", "line_ids.buy_amount", "line_ids.manual_price")
    def _compute_totals(self):
        for quote in self:
            quote.revenue_total = sum(quote.line_ids.mapped("sell_amount"))
            quote.cost_total = sum(quote.line_ids.mapped("buy_amount"))
            quote.margin = quote.revenue_total - quote.cost_total
            quote.margin_pct = (quote.margin / quote.revenue_total * 100.0) if quote.revenue_total else 0.0
            quote.has_manual_price = any(quote.line_ids.mapped("manual_price"))

    # --- pengisian dari rate card ------------------------------------------
    def action_load_rates(self):
        """Isi baris dari rate card yang berlaku pada tanggal penawaran.

        Bila tidak ada rate card yang cocok, katakan itu secara EKSPLISIT dan
        biarkan harga diisi tangan dengan penanda ``manual_price``. Diam-diam
        mengisi nol adalah cara tercepat mengirim penawaran yang salah.
        """
        self.ensure_one()
        Card = self.env["lgx.rate.card"]
        contract = self.contract_id or self.env["lgx.contract"].lgx_find_active(self.customer_id, self.date)
        sell_cards = contract.rate_card_ids.filtered(
            lambda c: c.state == "active"
            and c.valid_from <= self.date
            and (not c.valid_to or c.valid_to >= self.date)
        ) if contract else Card.browse()
        if not sell_cards:
            sell_cards = Card.lgx_find_applicable(
                "sell", self.date, partner=self.customer_id, transport_mode=self.transport_mode,
                load_type=self.load_type, origin=self.origin_id, destination=self.destination_id,
            )
        buy_cards = Card.lgx_find_applicable(
            "buy", self.date, transport_mode=self.transport_mode, load_type=self.load_type,
            origin=self.origin_id, destination=self.destination_id, any_partner=True,
        )
        if not sell_cards:
            raise UserError(_(
                "Tidak ada rate card jual yang berlaku pada %s untuk rute %s → %s, moda %s.\n\n"
                "Isi baris secara manual — setiap baris akan ditandai 'harga manual' "
                "sehingga terlihat di laporan bahwa penawaran ini tidak bersandar pada tarif.",
                self.date, self.origin_id.display_name or "?",
                self.destination_id.display_name or "?", self.transport_mode,
            ))
        sell = sell_cards[0]
        buy = buy_cards[:1]
        self.sell_rate_card_id = sell
        self.buy_rate_card_id = buy
        buy_prices = {l.charge_code_id.id: l for l in buy.line_ids} if buy else {}
        vals = []
        for line in sell.line_ids:
            buy_line = buy_prices.get(line.charge_code_id.id)
            vals.append({
                "quote_id": self.id,
                "charge_code_id": line.charge_code_id.id,
                "basis": line.basis,
                "container_type_id": line.container_type_id.id,
                "quantity": 1.0,
                "sell_price": line.price,
                "buy_price": buy_line.price if buy_line else 0.0,
                # Vendor diambil dari rate card BELI, karena di situlah ia
                # sebenarnya diketahui. Tanpa ini, baris biaya hasil konversi
                # lahir tanpa pihak, dan job menolak dikonfirmasi — akrual yang
                # tidak bisa ditagih ke siapa pun memang tidak boleh terbentuk.
                "vendor_id": (buy.partner_id.id if buy_line and buy.partner_id else False),
                "manual_price": not buy_line,
            })
        self.line_ids.unlink()
        self.env["lgx.quote.line"].create(vals)
        return True

    # --- alur --------------------------------------------------------------
    def _min_margin_pct(self):
        return float(self.env["ir.config_parameter"].sudo().get_param("lgx.min_margin_pct", 10.0))

    def action_send(self):
        for quote in self:
            if quote.state != "draft":
                raise UserError(_("Hanya penawaran draf yang dapat dikirim."))
            if not quote.line_ids:
                raise UserError(_("Penawaran %s belum punya baris.", quote.name))
            threshold = quote._min_margin_pct()
            if quote.margin_pct < threshold and not quote.approval_user_id:
                raise UserError(_(
                    "Margin penawaran %s adalah %.2f%%, di bawah ambang %.2f%%.\n\n"
                    "Minta persetujuan manajer penjualan dengan tombol 'Setujui Margin' "
                    "dan catat alasannya. Ambangnya adalah parameter sistem "
                    "'lgx.min_margin_pct', bukan konstanta di kode.",
                    quote.name, quote.margin_pct, threshold,
                ))
            quote.state = "sent"
        return True

    def action_approve_margin(self):
        """Persetujuan manajer atas margin di bawah ambang, dengan alasan tercatat."""
        for quote in self:
            if not self.env.user.has_group("custom_lgx_base.group_lgx_sales_manager"):
                raise UserError(_("Hanya manajer penjualan yang dapat menyetujui margin di bawah ambang."))
            if not quote.approval_reason:
                raise UserError(_(
                    "Isi alasan persetujuan lebih dulu. Persetujuan tanpa alasan tercatat "
                    "tidak dapat ditinjau kemudian, dan itu justru yang membuat ambang "
                    "margin berhenti berarti.",
                ))
            quote.approval_user_id = self.env.user
        return True

    def action_accept(self):
        for quote in self:
            if quote.state != "sent":
                raise UserError(_("Hanya penawaran terkirim yang dapat diterima."))
            quote.state = "accepted"
        return True

    def action_reject(self):
        self.filtered(lambda q: q.state == "sent").write({"state": "rejected"})
        return True

    def action_create_job(self):
        """Konversi ke job: setiap baris menjadi DUA baris charge.

        Satu ``revenue`` dari harga jual dan satu ``cost`` dari harga beli,
        keduanya ``estimated``. Membuat hanya baris pendapatan akan menghasilkan
        job yang labanya tampak 100% sampai tagihan vendor datang.
        """
        self.ensure_one()
        if self.job_id:
            raise UserError(_(
                "Penawaran %s sudah dikonversi menjadi job %s.", self.name, self.job_id.name,
            ))
        if self.state != "accepted":
            raise UserError(_("Hanya penawaran yang diterima yang dapat dikonversi menjadi job."))
        job = self.env["lgx.job"].create({
            "job_type": self.job_type,
            "transport_mode": self.transport_mode,
            "customer_id": self.customer_id.id,
            "salesperson_id": self.salesperson_id.id,
            "operating_unit_id": self.operating_unit_id.id,
            "company_id": self.company_id.id,
            "currency_id": self.currency_id.id,
            "origin_location_id": self.origin_id.id,
            "destination_location_id": self.destination_id.id,
            "incoterm_id": self.incoterm_id.id,
            "description": self.note or self.title_hint(),
            "quote_id": self.id,
            "contract_id": self.contract_id.id,
        })
        Charge = self.env["lgx.job.charge"]
        charge_vals = []
        for line in self.line_ids:
            code = line.charge_code_id
            common = {
                "job_id": job.id,
                "charge_code_id": code.id,
                "name": code.name,
                "nature": code.default_nature,
                "is_freight_charge": code.is_freight_charge,
                "quantity": line.quantity,
                "uom_id": line.uom_id.id or code.uom_id.id,
                "currency_id": self.currency_id.id,
                "wht_type": code.default_wht_type,
                "state": "estimated",
            }
            charge_vals.append(dict(
                common, kind="revenue", unit_price=line.sell_price,
                amount_estimated=line.sell_amount,
                tax_ids=[(6, 0, code.sale_tax_ids.ids)],
            ))
            if line.buy_price or line.buy_amount:
                charge_vals.append(dict(
                    common, kind="cost", unit_price=line.buy_price,
                    amount_estimated=line.buy_amount,
                    partner_id=line.vendor_id.id or False,
                    tax_ids=[(6, 0, code.purchase_tax_ids.ids)],
                ))
        Charge.create(charge_vals)
        job._generate_milestones()
        self.job_id = job
        return {
            "type": "ir.actions.act_window",
            "res_model": "lgx.job",
            "res_id": job.id,
            "view_mode": "form",
        }

    def title_hint(self):
        self.ensure_one()
        return "%s → %s" % (
            self.origin_id.display_name or "?", self.destination_id.display_name or "?",
        )

    def action_view_price_history(self):
        """Lima penawaran terakhir untuk kombinasi pelanggan + rute + moda."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Riwayat Harga"),
            "res_model": "lgx.quote",
            "view_mode": "list,form",
            "domain": [
                ("id", "!=", self.id),
                ("customer_id", "=", self.customer_id.id),
                ("origin_id", "=", self.origin_id.id),
                ("destination_id", "=", self.destination_id.id),
                ("transport_mode", "=", self.transport_mode),
            ],
            "context": {"create": False},
        }

    @api.model
    def _cron_expire_quotes(self):
        today = fields.Date.context_today(self)
        stale = self.search([("state", "in", ("draft", "sent")), ("validity_date", "<", today)])
        stale.write({"state": "expired"})
        return len(stale)


class LgxQuoteLine(models.Model):
    _name = "lgx.quote.line"
    _description = "Baris Penawaran"
    _order = "quote_id, sequence, id"

    sequence = fields.Integer(default=10)
    quote_id = fields.Many2one("lgx.quote", "Penawaran", required=True, ondelete="cascade", index=True)
    charge_code_id = fields.Many2one("lgx.charge.code", "Kode Charge", required=True)
    name = fields.Char("Keterangan")
    basis = fields.Selection(
        [("per_kg", "Per Kg"), ("per_cbm", "Per CBM"), ("per_container", "Per Kontainer"),
         ("per_shipment", "Per Shipment"), ("per_bl", "Per B/L"), ("per_trip", "Per Trip"),
         ("per_ton", "Per Ton"), ("per_km", "Per Km"), ("per_ritase", "Per Ritase"),
         ("per_pallet", "Per Pallet"), ("per_order_line", "Per Baris Order"), ("flat", "Flat")],
        string="Dasar", default="per_container",
    )
    container_type_id = fields.Many2one("lgx.container.type", "Tipe Kontainer")
    quantity = fields.Float("Kuantitas", default=1.0)
    uom_id = fields.Many2one("uom.uom", "Satuan")
    sell_price = fields.Monetary("Harga Jual", currency_field="currency_id")
    buy_price = fields.Monetary("Harga Beli", currency_field="currency_id")
    sell_amount = fields.Monetary("Jumlah Jual", compute="_compute_amounts", store=True,
                                  currency_field="currency_id")
    buy_amount = fields.Monetary("Jumlah Beli", compute="_compute_amounts", store=True,
                                 currency_field="currency_id")
    margin = fields.Monetary("Margin", compute="_compute_amounts", store=True, currency_field="currency_id")
    margin_pct = fields.Float("Margin (%)", compute="_compute_amounts", store=True, digits=(16, 2))
    vendor_id = fields.Many2one("res.partner", "Vendor")
    manual_price = fields.Boolean(
        "Harga Manual",
        help="True bila tidak ada rate card yang cocok dan harga diisi tangan. "
             "Dilaporkan supaya terlihat penawaran mana yang tidak bersandar pada tarif.",
    )
    currency_id = fields.Many2one(related="quote_id.currency_id", readonly=True)

    @api.depends("quantity", "sell_price", "buy_price")
    def _compute_amounts(self):
        for line in self:
            line.sell_amount = (line.quantity or 0.0) * (line.sell_price or 0.0)
            line.buy_amount = (line.quantity or 0.0) * (line.buy_price or 0.0)
            line.margin = line.sell_amount - line.buy_amount
            line.margin_pct = (line.margin / line.sell_amount * 100.0) if line.sell_amount else 0.0

    @api.onchange("charge_code_id")
    def _onchange_charge_code(self):
        for line in self:
            if line.charge_code_id:
                line.name = line.name or line.charge_code_id.name
                line.uom_id = line.charge_code_id.uom_id
