# -*- coding: utf-8 -*-
"""Checklist dokumen per jenis jasa, dan pengaruhnya pada milestone.

Dokumen yang belum ada MENGHALANGI milestone tertentu, bukan sekadar menjadi
pengingat. Alasannya operasional: dokumen yang baru ketahuan kurang saat barang
sudah di pelabuhan adalah demurrage yang sudah berjalan, dan biaya itu tidak
dapat ditarik kembali dengan melengkapi dokumennya kemudian.
"""
from odoo import _, api, fields, models


class LgxDocumentChecklistTemplate(models.Model):
    _name = "lgx.document.checklist.template"
    _description = "Template Checklist Dokumen"
    _order = "job_type, sequence"

    job_type = fields.Char("Jenis Job", required=True, index=True)
    transport_mode = fields.Selection(
        [("any", "Semua"), ("sea", "Laut"), ("air", "Udara"), ("land", "Darat"), ("rail", "Kereta")],
        string="Moda", default="any", required=True,
    )
    sequence = fields.Integer(default=10)
    document_type_id = fields.Many2one("lgx.document.type", "Jenis Dokumen", required=True)
    is_mandatory = fields.Boolean("Wajib", default=True)
    blocks_milestone_code = fields.Char(
        "Menghalangi Milestone",
        help="Kosong berarti memakai nilai dari jenis dokumennya.",
    )
    active = fields.Boolean(default=True)

    _template_uniq = models.Constraint(
        "unique(job_type, transport_mode, document_type_id)",
        "Jenis dokumen ini sudah ada pada checklist untuk jenis job dan moda yang sama.",
    )


class LgxDocumentChecklist(models.Model):
    _name = "lgx.document.checklist"
    _description = "Checklist Dokumen Job"
    _order = "job_id, sequence, id"

    job_id = fields.Many2one("lgx.job", "Job", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="job_id.company_id", store=True, index=True)
    sequence = fields.Integer(default=10)
    document_type_id = fields.Many2one("lgx.document.type", "Jenis Dokumen", required=True)
    is_mandatory = fields.Boolean("Wajib", default=True)
    blocks_milestone_code = fields.Char("Menghalangi Milestone")
    document_id = fields.Many2one("lgx.document", "Dokumen")
    is_satisfied = fields.Boolean("Terpenuhi", compute="_compute_satisfied", store=True)
    note = fields.Char("Catatan")

    _job_type_uniq = models.Constraint(
        "unique(job_id, document_type_id)",
        "Jenis dokumen ini sudah ada di checklist job tersebut.",
    )

    @api.depends("document_id", "document_id.status")
    def _compute_satisfied(self):
        for item in self:
            item.is_satisfied = bool(item.document_id) and item.document_id.status != "expired"
