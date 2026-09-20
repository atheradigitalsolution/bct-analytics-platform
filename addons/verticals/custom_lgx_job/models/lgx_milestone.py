# -*- coding: utf-8 -*-
"""lgx.milestone — satu mesin pelacakan untuk semua segmen.

Inilah yang membuat pelacakan pelanggan dan analitik waktu siklus mungkin tanpa
menulis tiga sistem pelacakan berbeda. Yang membedakan segmen hanyalah daftar
kodenya, dan daftar itu adalah data (``lgx.milestone.type``), bukan program.

``source`` ada supaya milestone yang datang dari NLE atau perangkat pengemudi
dapat dibedakan dari yang diketik staf. Saat pelanggan menanyakan kenapa ETA
berubah, "siapa yang bilang" adalah setengah dari jawabannya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxMilestone(models.Model):
    _name = "lgx.milestone"
    _description = "Milestone Job"
    _order = "job_id, sequence, planned_date, id"

    sequence = fields.Integer(default=10)
    job_id = fields.Many2one("lgx.job", "Job", ondelete="cascade", index=True)
    milestone_type_id = fields.Many2one("lgx.milestone.type", "Jenis", required=True, index=True)
    code = fields.Char(related="milestone_type_id.code", store=True, index=True)
    name = fields.Char(related="milestone_type_id.name", readonly=True)
    planned_date = fields.Datetime("Tanggal Rencana")
    actual_date = fields.Datetime("Tanggal Aktual", index=True)
    delay_days = fields.Float("Selisih (hari)", compute="_compute_delay", store=True,
                              help="Aktual dikurangi rencana. Positif berarti terlambat.")
    location_id = fields.Many2one("lgx.location", "Lokasi")
    is_customer_visible = fields.Boolean(
        "Terlihat Pelanggan", compute="_compute_visibility", store=True, readonly=False,
        help="Diwarisi dari jenis milestone, tetapi dapat ditimpa per job — "
             "sebagian pelanggan kontraktual berhak melihat lebih banyak.",
    )
    is_mandatory = fields.Boolean("Wajib", help="Menghalangi job masuk 'Selesai Operasi' bila belum tercapai.")
    is_exception = fields.Boolean(related="milestone_type_id.is_exception", store=True)
    source = fields.Selection(
        [("manual", "Manual"), ("api", "API"), ("nle", "NLE"), ("ceisa", "CEISA"),
         ("device", "Perangkat Lapangan"), ("system", "Sistem")],
        string="Sumber", default="manual", required=True,
    )
    created_by_id = fields.Many2one("res.users", "Dicatat Oleh", default=lambda s: s.env.user, readonly=True)
    note = fields.Char("Catatan")
    company_id = fields.Many2one(related="job_id.company_id", store=True, index=True)

    _job_type_uniq = models.Constraint(
        "unique(job_id, milestone_type_id)",
        "Satu jenis milestone hanya boleh muncul sekali per job.",
    )

    @api.depends("milestone_type_id")
    def _compute_visibility(self):
        for ms in self:
            ms.is_customer_visible = ms.milestone_type_id.is_customer_visible

    @api.depends("planned_date", "actual_date")
    def _compute_delay(self):
        for ms in self:
            if ms.planned_date and ms.actual_date:
                ms.delay_days = (ms.actual_date - ms.planned_date).total_seconds() / 86400.0
            else:
                ms.delay_days = 0.0

    @api.constrains("job_id")
    def _check_has_owner(self):
        """Milestone harus menggantung pada sesuatu.

        Field ``job_id`` opsional karena modul segmen menambahkan
        ``shipment_id`` dan ``trip_id``; yang tidak boleh adalah milestone yang
        tidak menggantung pada apa pun, karena ia tidak akan pernah muncul di
        layar mana pun lagi.
        """
        for ms in self:
            owners = [ms.job_id]
            for fname in ("shipment_id", "trip_id"):
                if fname in ms._fields:
                    owners.append(ms[fname])
            if not any(owners):
                raise ValidationError(_("Milestone harus terkait pada job, shipment, atau trip."))
