# -*- coding: utf-8 -*-
"""Proses penagihan periodik gudang, dengan pratinjau dan jejak ke potret harian.

Dua hal yang membuat tagihan gudang bertahan di rapat bulanan:

1. **Dapat dipratinjau sebelum diposting, dan dibatalkan selama belum
   difakturkan.** Tagihan yang langsung menjadi faktur begitu tombol ditekan
   adalah tagihan yang dikoreksi dengan nota kredit, dan nota kredit adalah
   percakapan yang tidak perlu.
2. **Dapat ditelusuri kembali ke potret harian yang menjadi dasarnya.** Setiap
   baris hasil menunjuk hari-hari okupansi yang membentuknya. Tagihan gudang yang
   tidak bisa ditelusuri adalah tagihan yang diperdebatkan setiap bulan.

Masa bebas diterapkan DI SINI, bukan saat memotret: potret merekam apa yang ada,
penagihan memutuskan apa yang ditagihkan. Dengan begitu perubahan masa bebas di
kontrak dapat diterapkan surut tanpa memotret ulang.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxWmsBillingRun(models.Model):
    _name = "lgx.wms.billing.run"
    _description = "Proses Penagihan Gudang"
    _order = "date_from desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread"]
    _lgx_sequence_code = "lgx.wms.billing.run"

    client_id = fields.Many2one("lgx.wms.client", "Klien", required=True, index=True)
    company_id = fields.Many2one(related="client_id.company_id", store=True, index=True)
    currency_id = fields.Many2one(related="client_id.currency_id", readonly=True)
    job_id = fields.Many2one("lgx.job", "Job Gudang", related="client_id.job_id", store=True)
    date_from = fields.Date("Dari Tanggal", required=True)
    date_to = fields.Date("Sampai Tanggal", required=True)

    line_ids = fields.One2many("lgx.wms.billing.run.line", "run_id", "Baris Hasil")
    snapshot_ids = fields.One2many("lgx.wms.occupancy.snapshot", "billing_run_id",
                                   "Potret yang Dipakai")
    snapshot_count = fields.Integer("Jumlah Potret", compute="_compute_totals")
    amount_storage = fields.Monetary("Penyimpanan", compute="_compute_totals", store=True)
    amount_handling = fields.Monetary("Handling", compute="_compute_totals", store=True)
    amount_minimum_topup = fields.Monetary("Penyesuaian Tagihan Minimum",
                                           compute="_compute_totals", store=True)
    amount_total = fields.Monetary("Total", compute="_compute_totals", store=True)
    charge_ids = fields.One2many("lgx.job.charge", "wms_billing_run_id", "Baris Charge")

    state = fields.Selection(
        [("draft", "Draf"), ("preview", "Pratinjau"), ("posted", "Diposting ke Job"),
         ("cancelled", "Batal")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Text("Catatan")

    _period_valid = models.Constraint(
        "check(date_to >= date_from)", "Periode penagihan tidak boleh berakhir sebelum dimulai.",
    )

    @api.depends("line_ids.amount", "line_ids.category", "snapshot_ids")
    def _compute_totals(self):
        for run in self:
            run.amount_storage = sum(
                run.line_ids.filtered(lambda l: l.category == "storage").mapped("amount"))
            run.amount_handling = sum(
                run.line_ids.filtered(lambda l: l.category == "handling").mapped("amount"))
            run.amount_minimum_topup = sum(
                run.line_ids.filtered(lambda l: l.category == "minimum").mapped("amount"))
            run.amount_total = sum(run.line_ids.mapped("amount"))
            run.snapshot_count = len(run.snapshot_ids)

    # --- perhitungan -------------------------------------------------------
    def action_compute(self):
        """Hitung ulang pratinjau dari potret harian. Tidak memposting apa pun."""
        for run in self:
            if run.state == "posted":
                raise UserError(_(
                    "Proses %s sudah diposting ke job. Batalkan lebih dulu bila "
                    "perhitungannya harus diulang.", run.name,
                ))
            run.line_ids.unlink()
            run.snapshot_ids.write({"billing_run_id": False, "is_free_period": False})
            run._compute_storage_lines()
            run._compute_minimum_line()
            run.state = "preview"
        return True

    def _compute_storage_lines(self):
        """Satu baris per aturan tarif, dari potret harian dalam periode."""
        self.ensure_one()
        Snapshot = self.env["lgx.wms.occupancy.snapshot"]
        Line = self.env["lgx.wms.billing.run.line"]
        rules = self.client_id.storage_rule_ids.filtered(
            lambda r: r.valid_from <= self.date_to and (not r.valid_to or r.valid_to >= self.date_from)
        )
        if not rules:
            return
        snapshots = Snapshot.search([
            ("client_id", "=", self.client_id.id),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("billing_run_id", "=", False),
        ])
        if not snapshots:
            return
        # Masa bebas: hari-hari PERTAMA sebuah produk/lot berada di gudang tidak
        # ditagihkan. Dihitung dari tanggal potret paling awal untuk kombinasi itu,
        # bukan dari awal periode — kalau tidak, barang yang menginap berbulan-bulan
        # akan mendapat masa bebas baru setiap bulan.
        first_seen = {}
        for snapshot in Snapshot.search([
            ("client_id", "=", self.client_id.id),
            ("date", "<=", self.date_to),
        ], order="date asc"):
            key = (snapshot.product_id.id, snapshot.lot_id.id or 0)
            first_seen.setdefault(key, snapshot.date)

        for rule in rules:
            scoped = snapshots
            if rule.product_category_id:
                scoped = scoped.filtered(
                    lambda s: s.product_id.categ_id == rule.product_category_id)
            if not scoped:
                continue
            billable, free = Snapshot.browse(), Snapshot.browse()
            for snapshot in scoped:
                key = (snapshot.product_id.id, snapshot.lot_id.id or 0)
                start = first_seen.get(key, snapshot.date)
                free_until = fields.Date.add(start, days=rule.free_days or 0)
                if rule.free_days and snapshot.date < free_until:
                    free |= snapshot
                else:
                    billable |= snapshot
            free.write({"is_free_period": True, "billing_run_id": self.id})
            if not billable:
                continue
            if rule.basis == "per_pallet_day":
                volume = sum(billable.mapped("pallet_count"))
                unit = _("pallet-hari")
            elif rule.basis == "per_cbm_day":
                volume = sum(billable.mapped("volume_cbm"))
                unit = _("CBM-hari")
            elif rule.basis == "per_kg_day":
                volume = sum(billable.mapped("weight_kg"))
                unit = _("kg-hari")
            else:  # per_sku_month
                volume = len(set(billable.mapped("product_id").ids))
                unit = _("SKU-bulan")
            rate = rule.lgx_rate_for(volume)
            Line.create({
                "run_id": self.id,
                "category": "storage",
                "name": _("%s — %.2f %s @ %s", rule.name, volume, unit, rate),
                "storage_rule_id": rule.id,
                "quantity": volume,
                "rate": rate,
                "amount": volume * rate,
                "snapshot_count": len(billable),
            })
            billable.write({"billing_run_id": self.id, "is_free_period": False})

    def _compute_minimum_line(self):
        """Tagihan minimum: SELISIHNYA, bukan penggantinya.

        Menampilkan minimum sebagai baris pengganti akan menyembunyikan berapa
        sebenarnya okupansi klien itu, dan itu angka yang dibawa ke negosiasi
        perpanjangan kontrak.
        """
        self.ensure_one()
        minimum = self.client_id.minimum_monthly_charge
        if not minimum:
            return
        current = sum(self.line_ids.mapped("amount"))
        if current >= minimum:
            return
        self.env["lgx.wms.billing.run.line"].create({
            "run_id": self.id,
            "category": "minimum",
            "name": _("Penyesuaian tagihan minimum bulanan (%s - %s)", minimum, current),
            "quantity": 1.0,
            "rate": minimum - current,
            "amount": minimum - current,
        })

    # --- posting -----------------------------------------------------------
    def action_post_to_job(self):
        """Buat baris charge pada job gudang klien. Belum memfakturkan."""
        for run in self:
            if run.state != "preview":
                raise UserError(_("Hitung pratinjau %s lebih dulu.", run.name))
            if not run.job_id:
                raise UserError(_(
                    "Klien %s belum punya job gudang. Tanpa job, biaya penyimpanan tidak "
                    "punya tempat berkumpul dan tidak akan pernah difakturkan.",
                    run.client_id.name,
                ))
            if not run.line_ids:
                raise UserError(_("Proses %s tidak menghasilkan satu pun baris.", run.name))
            Charge = self.env["lgx.job.charge"]
            for line in run.line_ids:
                Charge.create({
                    "job_id": run.job_id.id,
                    "charge_code_id": line._lgx_charge_code().id,
                    "wms_billing_run_id": run.id,
                    "kind": "revenue",
                    "nature": "service",
                    "quantity": line.quantity or 1.0,
                    "unit_price": line.rate,
                    "amount_estimated": line.amount,
                    "amount_actual": line.amount,
                    "is_actual_known": True,
                    "currency_id": run.currency_id.id,
                    "name": line.name,
                    "state": "confirmed",
                })
            run.state = "posted"
        return True

    def action_cancel(self):
        """Batalkan selama belum difakturkan.

        Baris charge yang sudah difakturkan menolak pembatalan — bukan karena
        teknis, melainkan karena membatalkan dasar sebuah faktur yang sudah
        terbit adalah cara faktur dan pembukuan berhenti sepakat.
        """
        for run in self:
            invoiced = run.charge_ids.filtered(lambda c: c.state == "invoiced")
            if invoiced:
                raise UserError(_(
                    "Proses %s sudah menghasilkan %s baris yang difakturkan. "
                    "Terbitkan nota kredit lewat jalur akuntansi, jangan membatalkan "
                    "dasar faktur yang sudah terbit.", run.name, len(invoiced),
                ))
            run.charge_ids.unlink()
            run.snapshot_ids.write({"billing_run_id": False, "is_free_period": False})
            run.state = "cancelled"
        return True

    def action_view_snapshots(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Potret Okupansi — %s", self.name),
            "res_model": "lgx.wms.occupancy.snapshot",
            "view_mode": "list,form",
            "domain": [("billing_run_id", "=", self.id)],
        }


class LgxWmsBillingRunLine(models.Model):
    _name = "lgx.wms.billing.run.line"
    _description = "Baris Hasil Penagihan Gudang"
    _order = "run_id, category, id"

    run_id = fields.Many2one("lgx.wms.billing.run", "Proses", required=True,
                             ondelete="cascade", index=True)
    company_id = fields.Many2one(related="run_id.company_id", store=True, index=True)
    category = fields.Selection(
        [("storage", "Penyimpanan"), ("handling", "Handling"), ("vas", "VAS"),
         ("minimum", "Tagihan Minimum")],
        string="Kategori", required=True, default="storage",
    )
    name = fields.Char("Keterangan", required=True)
    storage_rule_id = fields.Many2one("lgx.wms.storage.rule", "Tarif Penyimpanan")
    handling_rule_id = fields.Many2one("lgx.wms.handling.rule", "Tarif Handling")
    quantity = fields.Float("Kuantitas")
    rate = fields.Monetary("Tarif", currency_field="currency_id")
    amount = fields.Monetary("Jumlah", currency_field="currency_id")
    currency_id = fields.Many2one(related="run_id.currency_id", readonly=True)
    snapshot_count = fields.Integer("Hari Potret",
                                    help="Berapa baris potret harian yang membentuk baris ini.")

    def _lgx_charge_code(self):
        """Kode charge yang cocok dengan dasar tarifnya."""
        self.ensure_one()
        mapping = {
            "per_pallet_day": "custom_lgx_base.charge_sto_pal",
            "per_cbm_day": "custom_lgx_base.charge_sto_cbm",
            "per_sku_month": "custom_lgx_base.charge_sto_sku",
            "per_kg_day": "custom_lgx_base.charge_sto_kg",
        }
        if self.category == "storage" and self.storage_rule_id:
            return self.env.ref(mapping.get(self.storage_rule_id.basis,
                                            "custom_lgx_base.charge_sto_pal"))
        if self.category == "handling" and self.handling_rule_id:
            xmlid = ("custom_lgx_base.charge_hnd_in"
                     if self.handling_rule_id.operation == "inbound"
                     else "custom_lgx_base.charge_hnd_out")
            return self.env.ref(xmlid)
        if self.category == "vas":
            return self.env.ref("custom_lgx_base.charge_vas")
        return self.env.ref("custom_lgx_base.charge_adm")


class LgxJobCharge(models.Model):
    _inherit = "lgx.job.charge"

    wms_billing_run_id = fields.Many2one("lgx.wms.billing.run", "Proses Penagihan Gudang",
                                         index=True, ondelete="set null")
