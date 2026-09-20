# -*- coding: utf-8 -*-
"""Daily inpatient census."""
from odoo import fields, models


class HmsReportCensus(models.Model):
    _name = "hms.report.census"
    _description = "Sensus Harian Rawat Inap"
    _auto = False
    _order = "census_date desc"

    admission_id = fields.Many2one("hms.admission", readonly=True)
    census_date = fields.Date("Tanggal", readonly=True)
    ward_id = fields.Many2one("hms.ward", "Ruang", readonly=True)
    class_id = fields.Many2one("hms.care.class", "Kelas", readonly=True)
    payer_id = fields.Many2one("hms.payer", "Penjamin", readonly=True)
    dpjp_id = fields.Many2one("hms.practitioner", "DPJP", readonly=True)
    patient_days = fields.Integer("Hari Rawat", readonly=True)
    admissions = fields.Integer("Masuk", readonly=True)
    discharges = fields.Integer("Keluar", readonly=True)

    @property
    def _table_query(self):
        # One row per admission per day it occupied a bed. generate_series
        # expands the stay so "patient days" is counted rather than inferred,
        # which is what BOR and ALOS are actually computed from.
        return """
            SELECT
                (a.id * 100000 + (d::date - (a.admitted_at AT TIME ZONE 'UTC')::date)) AS id,
                a.id                       AS admission_id,
                d::date                    AS census_date,
                a.ward_id                  AS ward_id,
                a.class_id                 AS class_id,
                e.payer_id                 AS payer_id,
                a.dpjp_id                  AS dpjp_id,
                1                          AS patient_days,
                CASE WHEN d::date = (a.admitted_at AT TIME ZONE 'UTC')::date
                     THEN 1 ELSE 0 END     AS admissions,
                CASE WHEN a.discharged_at IS NOT NULL
                      AND d::date = (a.discharged_at AT TIME ZONE 'UTC')::date
                     THEN 1 ELSE 0 END     AS discharges
            FROM hms_admission a
            JOIN hms_encounter e ON e.id = a.encounter_id
            CROSS JOIN LATERAL generate_series(
                (a.admitted_at AT TIME ZONE 'UTC')::date,
                COALESCE((a.discharged_at AT TIME ZONE 'UTC')::date, CURRENT_DATE),
                INTERVAL '1 day'
            ) AS d
            WHERE a.state != 'cancelled'
        """
