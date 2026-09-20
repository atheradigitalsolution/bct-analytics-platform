# -*- coding: utf-8 -*-
"""Trucking menambahkan penghalang penyelesaian job."""
from odoo import _, api, fields, models


class LgxJob(models.Model):
    _inherit = "lgx.job"

    trip_ids = fields.One2many("lgx.trip", "job_id", "Trip")
    trip_count = fields.Integer("Jumlah Trip", compute="_compute_trip_stats")
    trip_open_count = fields.Integer("Trip Belum Tutup", compute="_compute_trip_stats", store=True)
    pod_missing_total = fields.Integer("Stop Tanpa POD", compute="_compute_trip_stats", store=True)

    @api.depends("trip_ids.state", "trip_ids.pod_missing_count")
    def _compute_trip_stats(self):
        for job in self:
            job.trip_count = len(job.trip_ids)
            job.trip_open_count = len(job.trip_ids.filtered(
                lambda t: t.state not in ("closed", "cancelled")))
            job.pod_missing_total = sum(job.trip_ids.mapped("pod_missing_count"))

    def _lgx_completion_blockers(self):
        """POD yang hilang dan uang jalan yang belum ditutup MENAHAN job.

        Keduanya adalah kebocoran yang khas trucking: POD hilang berarti
        pendapatan hilang, uang jalan yang tidak pernah ditutup berarti kas yang
        tidak pernah dipertanggungjawabkan. Keduanya baru terlihat kalau sistem
        menolak menutup job.
        """
        blockers = super()._lgx_completion_blockers()
        self.ensure_one()
        missing_pod = self.trip_ids.filtered(lambda t: t.pod_missing_count and t.state != "cancelled")
        if missing_pod:
            blockers.append(_(
                "%s trip masih punya stop bongkar tanpa POD: %s.",
                len(missing_pod), ", ".join(missing_pod.mapped("name")),
            ))
        open_advances = self.trip_ids.mapped("advance_id").filtered(
            lambda a: a.state in ("approved", "paid"))
        if open_advances:
            blockers.append(_(
                "%s uang jalan belum dipertanggungjawabkan: %s.",
                len(open_advances), ", ".join(open_advances.mapped("name")),
            ))
        return blockers

    def action_view_trips(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Trip Job %s", self.name),
            "res_model": "lgx.trip",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
            "context": {"default_job_id": self.id},
        }
