# -*- coding: utf-8 -*-
"""Master pengemudi dan masa berlaku SIM-nya.

Ada di modul TMS dan bukan di `custom_lgx_driver` karena dispatch harus dapat
menolak penugasan kepada pengemudi ber-SIM mati, dan penolakan itu tidak boleh
menunggu modul berikutnya dipasang. `custom_lgx_driver` memperluas model ini
dengan tautan hr.employee, log jam kerja, dan backend aplikasi lapangan.
"""
from odoo import _, api, fields, models


class LgxDriver(models.Model):
    _name = "lgx.driver"
    _description = "Pengemudi"
    _order = "name"
    _inherit = ["mail.thread"]

    name = fields.Char("Nama", required=True)
    partner_id = fields.Many2one(
        "res.partner", "Kontak", required=True, ondelete="restrict",
        help="Dipakai sebagai pihak pada uang muka dan piutang/utang pengemudi.",
    )
    user_id = fields.Many2one("res.users", "Pengguna Odoo",
                              help="Diisi bila pengemudi memakai aplikasi lapangan.")
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    employee_code = fields.Char("Nomor Induk")
    phone = fields.Char("Telepon")

    sim_number = fields.Char("Nomor SIM")
    sim_class = fields.Selection(
        [("b1", "B I"), ("b1_umum", "B I Umum"), ("b2", "B II"), ("b2_umum", "B II Umum"),
         ("a_umum", "A Umum")],
        string="Golongan SIM",
    )
    sim_expiry_date = fields.Date("Masa Berlaku SIM", tracking=True)
    sim_is_expired = fields.Boolean("SIM Mati", compute="_compute_sim_status", store=True)
    sim_days_to_expiry = fields.Integer("Sisa Hari SIM", compute="_compute_sim_status", store=True)

    medical_check_date = fields.Date("Pemeriksaan Kesehatan Terakhir")
    medical_valid_until = fields.Date("Berlaku Sampai")
    performance_score = fields.Float("Skor Kinerja", digits=(5, 2),
                                     help="Diisi dari penilaian periodik; bukan hasil hitungan otomatis.")
    home_pool_id = fields.Many2one("lgx.location", "Pool Asal")
    active = fields.Boolean(default=True)

    open_advance_count = fields.Integer("Uang Jalan Terbuka", compute="_compute_open_advance")

    _partner_uniq = models.Constraint(
        "unique(partner_id)", "Satu kontak hanya boleh menjadi satu pengemudi.",
    )

    @api.depends("sim_expiry_date")
    def _compute_sim_status(self):
        today = fields.Date.context_today(self)
        for driver in self:
            if driver.sim_expiry_date:
                driver.sim_days_to_expiry = (driver.sim_expiry_date - today).days
                driver.sim_is_expired = driver.sim_expiry_date < today
            else:
                driver.sim_days_to_expiry = 0
                driver.sim_is_expired = False

    def _compute_open_advance(self):
        Advance = self.env["lgx.trip.advance"]
        for driver in self:
            driver.open_advance_count = Advance.search_count([
                ("driver_id", "=", driver.id),
                ("state", "in", ("approved", "paid")),
            ])

    def action_view_open_advances(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Uang Jalan Terbuka — %s", self.name),
            "res_model": "lgx.trip.advance",
            "view_mode": "list,form",
            "domain": [("driver_id", "=", self.id), ("state", "in", ("approved", "paid"))],
        }
