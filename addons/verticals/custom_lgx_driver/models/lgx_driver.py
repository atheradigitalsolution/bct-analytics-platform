# -*- coding: utf-8 -*-
"""Pengemudi sebagai pegawai, plus pelatihan dan ringkasan kepatuhannya."""
from odoo import _, api, fields, models


class LgxDriver(models.Model):
    _inherit = "lgx.driver"

    employee_id = fields.Many2one(
        "hr.employee", "Pegawai",
        help="Menautkan pengemudi ke data kepegawaian. Dibiarkan opsional karena "
             "sebagian armada dijalankan pengemudi mitra, bukan pegawai sendiri.",
    )
    is_outsourced = fields.Boolean("Pengemudi Mitra",
                                   help="Bukan pegawai sendiri; jam kerjanya tetap dicatat.")
    training_ids = fields.One2many("lgx.driver.training", "driver_id", "Pelatihan")
    duty_log_ids = fields.One2many("lgx.driver.duty.log", "driver_id", "Log Jam Kerja")
    violation_count_30d = fields.Integer("Pelanggaran 30 Hari",
                                         compute="_compute_violation_count")

    def _compute_violation_count(self):
        Log = self.env["lgx.driver.duty.log"]
        cutoff = fields.Date.subtract(fields.Date.context_today(self), days=30)
        for driver in self:
            driver.violation_count_30d = Log.search_count([
                ("driver_id", "=", driver.id),
                ("date", ">=", cutoff),
                ("has_violation", "=", True),
            ])

    def action_view_duty_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Log Jam Kerja — %s", self.name),
            "res_model": "lgx.driver.duty.log",
            "view_mode": "list,form",
            "domain": [("driver_id", "=", self.id)],
        }


class LgxDriverTraining(models.Model):
    _name = "lgx.driver.training"
    _description = "Pelatihan Pengemudi"
    _order = "date desc"

    driver_id = fields.Many2one("lgx.driver", "Pengemudi", required=True,
                                ondelete="cascade", index=True)
    name = fields.Char("Nama Pelatihan", required=True)
    training_type = fields.Selection(
        [("defensive", "Defensive Driving"), ("dangerous_goods", "Barang Berbahaya"),
         ("first_aid", "P3K"), ("induction", "Induksi"), ("other", "Lainnya")],
        string="Jenis", default="defensive", required=True,
    )
    date = fields.Date("Tanggal", required=True, default=fields.Date.context_today)
    valid_until = fields.Date("Berlaku Sampai")
    provider = fields.Char("Penyelenggara")
    certificate_no = fields.Char("Nomor Sertifikat")
    attachment_ids = fields.Many2many("ir.attachment", string="Lampiran")
