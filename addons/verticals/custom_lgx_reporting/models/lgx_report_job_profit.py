# -*- coding: utf-8 -*-
"""Laba per job dan per segmen, sebagai view SQL.

View dan bukan model terisi: laporan yang punya salinan datanya sendiri adalah
laporan yang suatu saat berbeda dari sumbernya, dan pada saat itu tidak ada cara
memutuskan mana yang benar tanpa menghitung ulang keduanya dengan tangan.

Talangan DIPISAHKAN dari jasa di sini juga. Menggabungkannya membuat margin
persen job impor menjadi angka yang tidak berarti, karena bea masuk saja bisa
berkali lipat nilai jasanya.
"""
from odoo import api, fields, models, tools


class LgxReportJobProfit(models.Model):
    _name = "lgx.report.job.profit"
    _description = "Laporan Laba per Job"
    _auto = False
    _rec_name = "job_name"
    _order = "etd desc"

    job_id = fields.Many2one("lgx.job", "Job", readonly=True)
    job_name = fields.Char("Nomor Job", readonly=True)
    job_type = fields.Char("Jenis Job", readonly=True)
    segment = fields.Char("Segmen", readonly=True)
    transport_mode = fields.Char("Moda", readonly=True)
    customer_id = fields.Many2one("res.partner", "Pelanggan", readonly=True)
    salesperson_id = fields.Many2one("res.users", "Penjual", readonly=True)
    operating_unit_id = fields.Many2one("operating.unit", "Cabang", readonly=True)
    origin_id = fields.Many2one("lgx.location", "Asal", readonly=True)
    destination_id = fields.Many2one("lgx.location", "Tujuan", readonly=True)
    company_id = fields.Many2one("res.company", "Perusahaan", readonly=True)
    currency_id = fields.Many2one("res.currency", "Mata Uang", readonly=True)
    etd = fields.Date("ETD", readonly=True)
    state = fields.Char("Status", readonly=True)

    revenue_service = fields.Monetary("Pendapatan Jasa", readonly=True)
    cost_service = fields.Monetary("Biaya Jasa", readonly=True)
    margin = fields.Monetary("Margin", readonly=True)
    margin_pct = fields.Float("Margin (%)", readonly=True)
    disbursement_billed = fields.Monetary("Talangan Ditagihkan", readonly=True)
    disbursement_incurred = fields.Monetary("Talangan Dikeluarkan", readonly=True)
    accrual_open = fields.Monetary("Estimasi Belum Aktual", readonly=True)
    accrual_share_pct = fields.Float(
        "Porsi Estimasi Belum Aktual (%)", readonly=True,
        help="Ukuran seberapa dipercaya angka margin hari ini. Margin tanpa angka "
             "ini adalah setengah kalimat.",
    )

    @property
    def _table_query(self):
        return """
            SELECT
                j.id                                   AS id,
                j.id                                   AS job_id,
                j.name                                 AS job_name,
                j.job_type                             AS job_type,
                CASE
                    WHEN j.job_type LIKE 'ff_%%'      THEN 'forwarding'
                    WHEN j.job_type = 'customs_only'  THEN 'kepabeanan'
                    WHEN j.job_type = 'trucking'      THEN 'trucking'
                    WHEN j.job_type = 'warehouse'     THEN 'gudang'
                    ELSE 'lainnya'
                END                                    AS segment,
                j.transport_mode                       AS transport_mode,
                j.customer_id                          AS customer_id,
                j.salesperson_id                       AS salesperson_id,
                j.operating_unit_id                    AS operating_unit_id,
                j.origin_location_id                   AS origin_id,
                j.destination_location_id              AS destination_id,
                j.company_id                           AS company_id,
                j.currency_id                          AS currency_id,
                j.etd                                  AS etd,
                j.state                                AS state,
                j.revenue_total                        AS revenue_service,
                j.cost_total                           AS cost_service,
                j.margin                               AS margin,
                j.margin_pct                           AS margin_pct,
                j.disbursement_billed                  AS disbursement_billed,
                j.disbursement_incurred                AS disbursement_incurred,
                j.cost_accrual_open                    AS accrual_open,
                CASE WHEN j.cost_total <> 0
                     THEN j.cost_accrual_open / j.cost_total * 100.0
                     ELSE 0.0
                END                                    AS accrual_share_pct
            FROM lgx_job j
            WHERE j.state NOT IN ('cancelled')
        """
