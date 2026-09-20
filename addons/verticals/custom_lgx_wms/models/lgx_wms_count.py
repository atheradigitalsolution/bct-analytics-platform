# -*- coding: utf-8 -*-
"""Stock opname siklus: menjaga akurasi tanpa menghentikan operasi.

Frekuensi hitung ditentukan per kelas ABC — barang yang cepat bergerak dihitung
lebih sering, bukan semuanya sama. Stock opname tahunan yang menghentikan gudang
selama dua hari adalah cara akurasi dijaga di gudang milik sendiri; di 3PL, dua
hari berhenti adalah pelanggaran SLA.

Selisih di atas ambang menuntut HITUNG ULANG sebelum penyesuaian. Penyesuaian
yang langsung diposting dari hitungan pertama adalah cara kesalahan hitung
menjadi kesalahan stok.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxWmsCountProgram(models.Model):
    _name = "lgx.wms.count.program"
    _description = "Program Stock Opname Siklus"
    _order = "name"

    name = fields.Char("Nama", required=True)
    client_id = fields.Many2one("lgx.wms.client", "Klien", index=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    abc_class = fields.Selection(
        [("a", "A — cepat bergerak"), ("b", "B — sedang"), ("c", "C — lambat")],
        string="Kelas ABC", required=True, default="a",
    )
    frequency_days = fields.Integer("Frekuensi (hari)", required=True, default=30)
    location_ids = fields.Many2many("stock.location", string="Lokasi")
    product_ids = fields.Many2many("product.product", string="Produk")
    discrepancy_threshold_pct = fields.Float(
        "Ambang Selisih (%)", default=2.0,
        help="Selisih di atas ambang menuntut hitung ulang sebelum penyesuaian.",
    )
    last_run_date = fields.Date("Terakhir Dijalankan", readonly=True)
    next_run_date = fields.Date("Berikutnya", compute="_compute_next_run", store=True)
    task_ids = fields.One2many("lgx.wms.count.task", "program_id", "Tugas Hitung")
    active = fields.Boolean(default=True)

    _frequency_positive = models.Constraint(
        "check(frequency_days > 0)", "Frekuensi hitung harus lebih dari nol hari.",
    )

    @api.depends("last_run_date", "frequency_days")
    def _compute_next_run(self):
        for program in self:
            base = program.last_run_date or fields.Date.context_today(program)
            program.next_run_date = fields.Date.add(base, days=program.frequency_days or 30)

    def action_generate_tasks(self):
        """Buat tugas hitung terjadwal. Idempoten untuk tanggal yang sama."""
        Task = self.env["lgx.wms.count.task"]
        created = Task.browse()
        today = fields.Date.context_today(self)
        for program in self:
            existing = Task.search([
                ("program_id", "=", program.id),
                ("scheduled_date", "=", today),
                ("state", "!=", "cancelled"),
            ])
            if existing:
                continue
            locations = program.location_ids or self.env["stock.location"].search([
                ("usage", "=", "internal"),
                ("warehouse_id", "=", program.client_id.warehouse_id.id),
            ]) if program.client_id.warehouse_id else program.location_ids
            for location in locations:
                created |= Task.create({
                    "program_id": program.id,
                    "client_id": program.client_id.id,
                    "location_id": location.id,
                    "scheduled_date": today,
                })
            program.last_run_date = today
        return created

    @api.model
    def _cron_generate_count_tasks(self):
        today = fields.Date.context_today(self)
        due = self.search([("next_run_date", "<=", today)])
        due.action_generate_tasks()
        return len(due)


class LgxWmsCountTask(models.Model):
    _name = "lgx.wms.count.task"
    _description = "Tugas Hitung Stok"
    _order = "scheduled_date desc, id desc"

    program_id = fields.Many2one("lgx.wms.count.program", "Program", ondelete="cascade", index=True)
    client_id = fields.Many2one("lgx.wms.client", "Klien", index=True)
    company_id = fields.Many2one(related="program_id.company_id", store=True, index=True)
    location_id = fields.Many2one("stock.location", "Lokasi", required=True)
    scheduled_date = fields.Date("Tanggal Rencana", required=True, index=True,
                                 default=fields.Date.context_today)
    counted_date = fields.Date("Tanggal Hitung")
    counter_id = fields.Many2one("res.users", "Penghitung")
    line_ids = fields.One2many("lgx.wms.count.line", "task_id", "Baris Hitung")
    discrepancy_count = fields.Integer("Baris Selisih", compute="_compute_discrepancy", store=True)
    max_discrepancy_pct = fields.Float("Selisih Terbesar (%)", compute="_compute_discrepancy",
                                       store=True)
    needs_recount = fields.Boolean("Butuh Hitung Ulang", compute="_compute_discrepancy", store=True)
    recount_of_id = fields.Many2one("lgx.wms.count.task", "Hitung Ulang Dari", readonly=True)
    adjustment_reason = fields.Char("Alasan Penyesuaian")
    approved_by_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True)
    state = fields.Selection(
        [("draft", "Draf"), ("counting", "Dihitung"), ("review", "Ditinjau"),
         ("adjusted", "Disesuaikan"), ("cancelled", "Batal")],
        string="Status", default="draft", required=True, index=True,
    )

    @api.depends("line_ids.discrepancy_pct", "program_id.discrepancy_threshold_pct")
    def _compute_discrepancy(self):
        for task in self:
            deviating = task.line_ids.filtered(lambda l: l.discrepancy_qty)
            task.discrepancy_count = len(deviating)
            task.max_discrepancy_pct = max(
                (abs(line.discrepancy_pct) for line in task.line_ids), default=0.0)
            threshold = task.program_id.discrepancy_threshold_pct or 0.0
            task.needs_recount = bool(threshold) and task.max_discrepancy_pct > threshold

    def action_start_count(self):
        self.filtered(lambda t: t.state == "draft").write({
            "state": "counting", "counter_id": self.env.user.id,
        })
        return True

    def action_submit(self):
        for task in self:
            if not task.line_ids:
                raise UserError(_("Tugas hitung %s belum punya baris.", task.display_name))
            task.write({"state": "review", "counted_date": fields.Date.context_today(task)})
        return True

    def action_create_recount(self):
        """Selisih di atas ambang: hitung ulang dulu, jangan langsung menyesuaikan."""
        self.ensure_one()
        recount = self.copy({
            "recount_of_id": self.id,
            "state": "draft",
            "counted_date": False,
            "counter_id": False,
            "line_ids": [(0, 0, {
                "product_id": line.product_id.id,
                "lot_id": line.lot_id.id,
                "owner_id": line.owner_id.id,
                "quantity_expected": line.quantity_expected,
            }) for line in self.line_ids],
        })
        return {
            "type": "ir.actions.act_window",
            "res_model": "lgx.wms.count.task",
            "res_id": recount.id,
            "view_mode": "form",
        }

    def action_approve_adjustment(self):
        for task in self:
            if task.needs_recount and not task.recount_of_id:
                raise UserError(_(
                    "Selisih terbesar %.2f%% melewati ambang program (%.2f%%). "
                    "Lakukan hitung ulang lebih dulu — penyesuaian yang diposting dari "
                    "hitungan pertama adalah cara kesalahan hitung menjadi kesalahan stok.",
                    task.max_discrepancy_pct, task.program_id.discrepancy_threshold_pct,
                ))
            if not task.adjustment_reason:
                raise UserError(_("Isi alasan penyesuaian lebih dulu."))
            task.write({"state": "adjusted", "approved_by_id": self.env.user.id})
        return True


class LgxWmsCountLine(models.Model):
    _name = "lgx.wms.count.line"
    _description = "Baris Hitung Stok"
    _order = "task_id, id"

    task_id = fields.Many2one("lgx.wms.count.task", "Tugas", required=True,
                              ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", "Produk", required=True)
    lot_id = fields.Many2one("stock.lot", "Lot / Serial")
    owner_id = fields.Many2one("res.partner", "Pemilik")
    quantity_expected = fields.Float("Jumlah Sistem")
    quantity_counted = fields.Float("Jumlah Hitung")
    discrepancy_qty = fields.Float("Selisih", compute="_compute_discrepancy", store=True)
    discrepancy_pct = fields.Float("Selisih (%)", compute="_compute_discrepancy", store=True)
    note = fields.Char("Catatan")

    @api.depends("quantity_expected", "quantity_counted")
    def _compute_discrepancy(self):
        for line in self:
            line.discrepancy_qty = (line.quantity_counted or 0.0) - (line.quantity_expected or 0.0)
            line.discrepancy_pct = (
                line.discrepancy_qty / line.quantity_expected * 100.0
                if line.quantity_expected else (100.0 if line.discrepancy_qty else 0.0)
            )
