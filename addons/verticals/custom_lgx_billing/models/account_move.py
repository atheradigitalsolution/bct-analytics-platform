# -*- coding: utf-8 -*-
"""Jejak dua arah antara dokumen akuntansi dan job.

Tanpa ``lgx_job_id`` pada ``account.move`` dan ``lgx_charge_id`` pada barisnya,
pertanyaan "faktur ini menagihkan apa dari job mana" hanya bisa dijawab dengan
membaca teks keterangan — dan teks keterangan adalah hal pertama yang diubah
orang.
"""
from odoo import _, api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    lgx_job_id = fields.Many2one("lgx.job", "Job Logistik", index=True, copy=False)
    lgx_is_lgx_document = fields.Boolean("Dokumen Logistik", compute="_compute_lgx_flag", store=True)

    @api.depends("lgx_job_id")
    def _compute_lgx_flag(self):
        for move in self:
            move.lgx_is_lgx_document = bool(move.lgx_job_id)

    def _post(self, soft=True):
        """Setelah posting, nilai aktual pada baris charge menjadi diketahui.

        Dilakukan di ``_post`` dan bukan di tombol, supaya faktur yang diposting
        lewat jalur lain — impor, API, aksi massal — ikut memutakhirkan job.
        """
        posted = super()._post(soft=soft)
        posted._lgx_sync_charges()
        return posted

    # Hanya FAKTUR yang memutakhirkan nilai aktual. Entri akrual, varians dan
    # provisi juga membawa lgx_job_id dan lgx_charge_id — tanpa penyaringan ini,
    # memposting akrual akan menandai barisnya "aktual sudah diketahui" dan
    # seluruh mekanisme estimasi-versus-aktual runtuh pada langkah pertamanya.
    _LGX_INVOICE_TYPES = ("out_invoice", "out_refund", "in_invoice", "in_refund")

    def _lgx_sync_charges(self):
        for move in self:
            if not move.lgx_job_id or move.move_type not in self._LGX_INVOICE_TYPES:
                continue
            for line in move.line_ids.filtered("lgx_charge_id"):
                charge = line.lgx_charge_id
                amount = abs(line.balance)
                charge.action_record_actual(amount)
                charge.state = "invoiced"
                if move.move_type in ("out_invoice", "out_refund"):
                    charge.invoice_line_id = line
                else:
                    charge.bill_line_id = line
            move.lgx_job_id._lgx_post_variance(move)
        return True


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    lgx_charge_id = fields.Many2one("lgx.job.charge", "Baris Charge Job", index=True, copy=False)
    lgx_job_id = fields.Many2one(related="move_id.lgx_job_id", store=True, index=True)
