# -*- coding: utf-8 -*-
"""Master milestone dan template-nya per jenis job.

Satu mesin pelacakan untuk ketiga segmen. Yang membedakan forwarding dari
trucking bukan mekanismenya, melainkan daftar kodenya — jadi daftar itu yang
dijadikan data, bukan kode program.

``lgx.milestone.template`` memegang rangkaian yang diharapkan per ``job_type``,
sehingga job baru langsung lahir dengan milestone bertanggal rencana kosong.
Tanpa itu, pelacakan pelanggan hanya bisa menampilkan apa yang kebetulan sudah
terjadi, bukan apa yang seharusnya terjadi berikutnya.
"""
from odoo import api, fields, models


class LgxMilestoneType(models.Model):
    _name = "lgx.milestone.type"
    _description = "Jenis Milestone"
    _order = "sequence, code"

    sequence = fields.Integer(default=10)
    code = fields.Char("Kode", required=True, index=True)
    name = fields.Char("Nama", required=True, translate=True)
    segment = fields.Selection(
        [("common", "Umum"), ("ff", "Forwarding"), ("customs", "Kepabeanan"),
         ("tms", "Trucking"), ("wms", "Gudang")],
        string="Segmen", required=True, default="common",
    )
    is_customer_visible = fields.Boolean(
        "Terlihat Pelanggan", default=True,
        help="Milestone internal (mis. biaya vendor diterima) tidak boleh muncul di portal.",
    )
    is_exception = fields.Boolean(
        "Kejadian Pengecualian",
        help="Menandai milestone yang menyatakan sesuatu berjalan tidak semestinya: "
             "tertahan pabean, kontainer roll-over, pengiriman ditolak.",
    )
    active = fields.Boolean(default=True)

    _code_uniq = models.Constraint("unique(code)", "Kode milestone harus unik.")

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name}" if rec.name else rec.code


class LgxMilestoneTemplate(models.Model):
    _name = "lgx.milestone.template"
    _description = "Template Milestone per Jenis Job"
    _order = "job_type, sequence"

    job_type = fields.Char(
        "Jenis Job", required=True, index=True,
        help="Nilai selection lgx.job.job_type. Char, bukan Selection, supaya "
             "modul segmen dapat menambah jenis job tanpa memigrasi tabel ini.",
    )
    transport_mode = fields.Selection(
        [("any", "Semua"), ("sea", "Laut"), ("air", "Udara"), ("land", "Darat"), ("rail", "Kereta")],
        string="Moda", default="any", required=True,
    )
    sequence = fields.Integer(default=10)
    milestone_type_id = fields.Many2one("lgx.milestone.type", "Milestone", required=True, ondelete="cascade")
    offset_days = fields.Integer(
        "Selisih Hari dari ETD", default=0,
        help="Dipakai mengisi tanggal rencana saat job dibuat. Negatif berarti sebelum ETD.",
    )
    is_mandatory = fields.Boolean(
        "Wajib", default=False,
        help="Milestone wajib yang belum tercapai menghalangi job masuk 'completed'.",
    )
    active = fields.Boolean(default=True)

    _template_uniq = models.Constraint(
        "unique(job_type, transport_mode, milestone_type_id)",
        "Milestone ini sudah ada pada template untuk jenis job dan moda yang sama.",
    )
