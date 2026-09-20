# -*- coding: utf-8 -*-
"""Forwarding menambah penghalang penutupan job, dan bagian agen sebagai biaya."""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxJob(models.Model):
    _inherit = "lgx.job"

    shipment_ids = fields.One2many("lgx.shipment", "job_id", "Shipment")
    shipment_count = fields.Integer("Jumlah Shipment", compute="_compute_ff_stats")
    container_ids = fields.One2many("lgx.container", "job_id", "Kontainer")
    container_open_count = fields.Integer("Kontainer Belum Kembali", compute="_compute_ff_stats",
                                          store=True)
    demurrage_days_total = fields.Integer("Total Hari Demurrage", compute="_compute_ff_stats",
                                          store=True)
    detention_days_total = fields.Integer("Total Hari Detensi", compute="_compute_ff_stats",
                                          store=True)

    @api.depends("shipment_ids", "container_ids.is_returned",
                 "container_ids.demurrage_days", "container_ids.detention_days")
    def _compute_ff_stats(self):
        for job in self:
            job.shipment_count = len(job.shipment_ids)
            open_containers = job.container_ids.filtered(lambda c: not c.is_returned)
            job.container_open_count = len(open_containers)
            job.demurrage_days_total = sum(job.container_ids.mapped("demurrage_days"))
            job.detention_days_total = sum(job.container_ids.mapped("detention_days"))

    def _lgx_completion_blockers(self):
        """Kontainer yang belum kembali MENAHAN penyelesaian operasional job.

        Ini aturan yang menutup kebocoran paling umum di forwarding: demurrage
        dan detensi ditagihkan carrier beberapa minggu setelahnya, dan kalau job
        sudah ditutup, biaya itu tidak pernah diteruskan ke pelanggan.
        """
        blockers = super()._lgx_completion_blockers()
        self.ensure_one()
        open_containers = self.container_ids.filtered(lambda c: not c.is_returned)
        if open_containers:
            blockers.append(_(
                "%s kontainer belum dikembalikan ke depo: %s. Selama belum kembali, "
                "detensi masih berjalan dan belum bisa ditagihkan.",
                len(open_containers), ", ".join(open_containers.mapped("container_no")),
            ))
        open_shipments = self.shipment_ids.filtered(
            lambda s: s.state not in ("completed", "cancelled"))
        if open_shipments:
            blockers.append(_(
                "%s shipment belum selesai: %s.",
                len(open_shipments), ", ".join(open_shipments.mapped("name")),
            ))
        return blockers

    def action_generate_agent_share(self):
        """Bentuk baris biaya bagian agen dari job nominasi.

        Dijadikan tombol dan bukan otomatis saat konfirmasi, karena skema bagi
        hasil sering dinegosiasikan per job dan angka yang muncul sendiri tanpa
        diminta adalah angka yang tidak diperiksa siapa pun.
        """
        charge_code = self.env.ref("custom_lgx_base.charge_agn")
        created = self.env["lgx.job.charge"].browse()
        for job in self:
            if not job.is_nomination or not job.agent_id:
                raise UserError(_(
                    "Job %s bukan job nominasi atau belum menunjuk agen.", job.name,
                ))
            share_pct = job.agent_id.lgx_agent_profit_share
            if not share_pct:
                raise UserError(_(
                    "Agen %s belum punya persentase bagi hasil. Isi 'Bagi Hasil Agen' "
                    "di kartu partner — angka bagi hasil yang ditebak sistem adalah "
                    "angka yang akan dipersoalkan agen.", job.agent_id.display_name,
                ))
            existing = job.charge_ids.filtered(
                lambda c: c.charge_code_id == charge_code and c.state != "cancelled")
            if existing:
                raise UserError(_(
                    "Bagian agen untuk job %s sudah dibentuk.", job.name,
                ))
            amount = job.margin * share_pct / 100.0
            if amount <= 0:
                raise UserError(_(
                    "Margin job %s belum positif, jadi bagian agen belum dapat dihitung.", job.name,
                ))
            created |= self.env["lgx.job.charge"].create({
                "job_id": job.id,
                "charge_code_id": charge_code.id,
                "kind": "cost",
                "nature": "service",
                "partner_id": job.agent_id.id,
                "quantity": 1.0,
                "unit_price": amount,
                "amount_estimated": amount,
                "currency_id": job.currency_id.id,
                "name": _("Bagi hasil agen %s%%", share_pct),
            })
        return created

    def action_view_containers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Kontainer Job %s", self.name),
            "res_model": "lgx.container",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
        }
