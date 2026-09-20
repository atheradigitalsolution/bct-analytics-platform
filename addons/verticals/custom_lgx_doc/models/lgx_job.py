# -*- coding: utf-8 -*-
"""Job memperoleh checklist dokumen, dan milestone yang tertahan olehnya."""
from odoo import _, api, fields, models


class LgxJob(models.Model):
    _inherit = "lgx.job"

    document_ids = fields.One2many("lgx.document", "job_id", "Dokumen")
    checklist_ids = fields.One2many("lgx.document.checklist", "job_id", "Checklist Dokumen")
    checklist_missing_count = fields.Integer("Dokumen Wajib Kurang",
                                             compute="_compute_checklist", store=True)

    @api.depends("checklist_ids.is_satisfied", "checklist_ids.is_mandatory")
    def _compute_checklist(self):
        for job in self:
            job.checklist_missing_count = len(job.checklist_ids.filtered(
                lambda c: c.is_mandatory and not c.is_satisfied))

    def action_generate_checklist(self):
        """Isi checklist dari template. Idempoten."""
        Template = self.env["lgx.document.checklist.template"]
        Checklist = self.env["lgx.document.checklist"]
        for job in self:
            existing = set(job.checklist_ids.mapped("document_type_id").ids)
            templates = Template.search([
                ("job_type", "=", job.job_type),
                ("transport_mode", "in", (job.transport_mode, "any")),
            ], order="sequence")
            values = []
            for template in templates:
                if template.document_type_id.id in existing:
                    continue
                values.append({
                    "job_id": job.id,
                    "sequence": template.sequence,
                    "document_type_id": template.document_type_id.id,
                    "is_mandatory": template.is_mandatory,
                    "blocks_milestone_code": (template.blocks_milestone_code
                                              or template.document_type_id.blocks_milestone_code),
                })
                existing.add(template.document_type_id.id)
            if values:
                Checklist.create(values)
        return True

    def action_confirm(self):
        result = super().action_confirm()
        self.action_generate_checklist()
        return result

    def lgx_log_milestone(self, code, actual_date=None, location=None, source="manual", note=None):
        """Milestone yang dihalangi dokumen tidak dapat dicatat tercapai.

        Ini yang membedakan checklist dari pengingat: ia menahan alur, bukan
        menyarankan. Dilewati untuk sumber `system` dan `nle` supaya kenyataan
        dari luar tetap dapat dicatat — menolak fakta yang sudah terjadi hanya
        membuat data berhenti mencerminkan lapangan.
        """
        self.ensure_one()
        if source in ("manual", "api"):
            # sudo(): checklist dibaca sebagai ATURAN SISTEM, bukan sebagai data
            # yang ditelusuri pengguna.
            #
            # Ditemukan saat menguji aplikasi pengemudi: pengemudi menekan
            # "Berangkat", alur memanggil lgx_log_milestone, dan ia ditolak
            # karena tidak berhak MEMBACA checklist yang seharusnya MENAHANNYA.
            # Menuntut hak baca di sini berarti setiap peran yang bisa memicu
            # milestone harus diberi akses ke checklist — dan memberi akses baca
            # hanya supaya sebuah larangan bisa dijalankan adalah cara larangan
            # itu akhirnya dilonggarkan.
            blocking = self.sudo().checklist_ids.filtered(
                lambda c: c.is_mandatory and not c.is_satisfied
                and c.blocks_milestone_code == code
            )
            if blocking:
                from odoo.exceptions import UserError
                raise UserError(_(
                    "Milestone '%s' tertahan: dokumen wajib berikut belum ada — %s.\n\n"
                    "Dokumen yang baru ketahuan kurang saat barang sudah di pelabuhan "
                    "adalah demurrage yang sudah berjalan.",
                    code, ", ".join(blocking.mapped("document_type_id.name")),
                ))
        return super().lgx_log_milestone(code, actual_date, location, source, note)
