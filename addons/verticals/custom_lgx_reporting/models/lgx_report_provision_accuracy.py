# -*- coding: utf-8 -*-
"""Akurasi provisi: selisih provisi terhadap tagihan yang akhirnya datang.

Inilah ukuran seberapa dipercaya angka margin bulan berjalan — dan itu yang
dipakai manajemen, bukan janji bahwa estimasi selalu benar. Dipecah per kategori
charge, karena akurasi biasanya berbeda tajam antar kategori: freight yang
dikontrakkan hampir selalu tepat, demurrage hampir selalu meleset.
"""
from odoo import fields, models


class LgxReportProvisionAccuracy(models.Model):
    _name = "lgx.report.provision.accuracy"
    _description = "Laporan Akurasi Provisi"
    _auto = False
    _order = "category"

    charge_id = fields.Many2one("lgx.job.charge", "Baris Charge", readonly=True)
    job_id = fields.Many2one("lgx.job", "Job", readonly=True)
    charge_code_id = fields.Many2one("lgx.charge.code", "Kode Charge", readonly=True)
    category = fields.Char("Kategori", readonly=True)
    nature = fields.Char("Sifat", readonly=True)
    partner_id = fields.Many2one("res.partner", "Vendor", readonly=True)
    company_id = fields.Many2one("res.company", "Perusahaan", readonly=True)
    currency_id = fields.Many2one("res.currency", "Mata Uang", readonly=True)
    provision_date = fields.Date("Tanggal Provisi", readonly=True)
    provision_age_days = fields.Integer("Umur Provisi (hari)", readonly=True)
    amount_estimated = fields.Monetary("Estimasi / Provisi", readonly=True)
    amount_actual = fields.Monetary("Tagihan Sesungguhnya", readonly=True)
    amount_variance = fields.Monetary("Selisih", readonly=True)
    accuracy_pct = fields.Float("Akurasi (%)", readonly=True)
    state = fields.Char("Status", readonly=True)

    @property
    def _table_query(self):
        return """
            SELECT
                c.id                                    AS id,
                c.id                                    AS charge_id,
                c.job_id                                AS job_id,
                c.charge_code_id                        AS charge_code_id,
                cc.category                             AS category,
                c.nature                                AS nature,
                c.partner_id                            AS partner_id,
                c.company_id                            AS company_id,
                c.currency_id                           AS currency_id,
                c.provision_date                        AS provision_date,
                CASE WHEN c.provision_date IS NOT NULL
                     THEN (CURRENT_DATE - c.provision_date)
                     ELSE 0
                END                                     AS provision_age_days,
                c.amount_estimated                      AS amount_estimated,
                c.amount_actual                         AS amount_actual,
                c.amount_variance                       AS amount_variance,
                CASE WHEN c.amount_estimated <> 0
                     THEN (1 - ABS(c.amount_actual - c.amount_estimated)
                                / NULLIF(c.amount_estimated, 0)) * 100.0
                     ELSE 0.0
                END                                     AS accuracy_pct,
                c.state                                 AS state
            FROM lgx_job_charge c
            JOIN lgx_charge_code cc ON cc.id = c.charge_code_id
            WHERE c.kind = 'cost'
              AND (c.is_actual_known = TRUE OR c.state = 'provisioned')
        """
