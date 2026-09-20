# -*- coding: utf-8 -*-
"""Waktu siklus per tahap, dari selisih tanggal aktual antar milestone.

Disajikan sebagai baris per (job, milestone) supaya median dan persentil dapat
dihitung di lapisan pivot Odoo. Rata-rata sengaja BUKAN satu-satunya ukuran yang
ditawarkan: distribusi waktu bongkar pelabuhan berekor panjang, dan rata-rata
pada distribusi berekor panjang menyembunyikan justru kasus yang membuat
pelanggan menelepon.
"""
from odoo import fields, models


class LgxReportCycleTime(models.Model):
    _name = "lgx.report.cycle.time"
    _description = "Laporan Waktu Siklus"
    _auto = False
    _order = "job_id, sequence"

    job_id = fields.Many2one("lgx.job", "Job", readonly=True)
    job_type = fields.Char("Jenis Job", readonly=True)
    transport_mode = fields.Char("Moda", readonly=True)
    customer_id = fields.Many2one("res.partner", "Pelanggan", readonly=True)
    origin_id = fields.Many2one("lgx.location", "Asal", readonly=True)
    destination_id = fields.Many2one("lgx.location", "Tujuan", readonly=True)
    company_id = fields.Many2one("res.company", "Perusahaan", readonly=True)
    milestone_type_id = fields.Many2one("lgx.milestone.type", "Milestone", readonly=True)
    milestone_code = fields.Char("Kode Milestone", readonly=True)
    sequence = fields.Integer("Urutan", readonly=True)
    planned_date = fields.Datetime("Rencana", readonly=True)
    actual_date = fields.Datetime("Aktual", readonly=True)
    delay_days = fields.Float("Selisih dari Rencana (hari)", readonly=True)
    elapsed_days = fields.Float("Hari sejak Milestone Sebelumnya", readonly=True)

    @property
    def _table_query(self):
        return """
            SELECT
                m.id                          AS id,
                m.job_id                      AS job_id,
                j.job_type                    AS job_type,
                j.transport_mode              AS transport_mode,
                j.customer_id                 AS customer_id,
                j.origin_location_id          AS origin_id,
                j.destination_location_id     AS destination_id,
                j.company_id                  AS company_id,
                m.milestone_type_id           AS milestone_type_id,
                mt.code                       AS milestone_code,
                m.sequence                    AS sequence,
                m.planned_date                AS planned_date,
                m.actual_date                 AS actual_date,
                m.delay_days                  AS delay_days,
                EXTRACT(EPOCH FROM (
                    m.actual_date - LAG(m.actual_date) OVER (
                        PARTITION BY m.job_id ORDER BY m.sequence, m.id
                    )
                )) / 86400.0                  AS elapsed_days
            FROM lgx_milestone m
            JOIN lgx_job j       ON j.id = m.job_id
            JOIN lgx_milestone_type mt ON mt.id = m.milestone_type_id
            WHERE m.actual_date IS NOT NULL
        """
