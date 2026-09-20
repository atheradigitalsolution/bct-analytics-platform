# -*- coding: utf-8 -*-
"""Pencatatan pengunduhan dokumen oleh pelanggan.

Bukan untuk mengawasi pelanggan. Pertanyaan "apakah mereka sudah menerima
B/L-nya" muncul setiap minggu di operasi, dan menjawabnya dengan tebakan adalah
cara dokumen dikirim ulang berkali-kali lewat surel — lalu versi mana yang
dipegang pelanggan menjadi tidak diketahui siapa pun.
"""
from odoo import _, api, fields, models


class LgxDocument(models.Model):
    _inherit = "lgx.document"

    download_log_ids = fields.One2many("lgx.document.download.log", "document_id",
                                       "Riwayat Unduh")
    download_count = fields.Integer("Jumlah Unduh", compute="_compute_download_stats", store=True)
    last_downloaded_at = fields.Datetime("Terakhir Diunduh", compute="_compute_download_stats",
                                         store=True)

    @api.depends("download_log_ids.downloaded_at")
    def _compute_download_stats(self):
        for document in self:
            logs = document.download_log_ids
            document.download_count = len(logs)
            document.last_downloaded_at = max(logs.mapped("downloaded_at")) if logs else False

    def lgx_log_download(self, partner=None, source="portal", remote_addr=None):
        """Catat satu pengunduhan. Dipanggil controller, bukan dari UI."""
        self.ensure_one()
        return self.env["lgx.document.download.log"].sudo().create({
            "document_id": self.id,
            "partner_id": (partner or self.env.user.partner_id).id,
            "user_id": self.env.uid,
            "source": source,
            "remote_addr": remote_addr,
        })


class LgxDocumentDownloadLog(models.Model):
    _name = "lgx.document.download.log"
    _description = "Riwayat Unduh Dokumen"
    _order = "downloaded_at desc, id desc"

    document_id = fields.Many2one("lgx.document", "Dokumen", required=True,
                                  ondelete="cascade", index=True)
    job_id = fields.Many2one(related="document_id.job_id", store=True, index=True)
    company_id = fields.Many2one(related="document_id.company_id", store=True, index=True)
    partner_id = fields.Many2one("res.partner", "Diunduh Oleh", index=True)
    user_id = fields.Many2one("res.users", "Pengguna")
    downloaded_at = fields.Datetime("Waktu", default=fields.Datetime.now, required=True, index=True)
    source = fields.Selection(
        [("portal", "Portal Pelanggan"), ("public_link", "Tautan Pelacakan Publik"),
         ("backend", "Backend"), ("api", "API")],
        string="Jalur", default="portal", required=True,
    )
    remote_addr = fields.Char("Alamat IP")
