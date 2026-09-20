# -*- coding: utf-8 -*-
"""Visit statistics as a SQL view."""
from odoo import api, fields, models, tools


class HmsReportVisit(models.Model):
    _name = "hms.report.visit"
    _description = "Laporan Kunjungan"
    _auto = False
    _order = "arrival_date desc"

    encounter_id = fields.Many2one("hms.encounter", readonly=True)
    patient_id = fields.Many2one("hms.patient", readonly=True)
    arrival_date = fields.Date("Tanggal", readonly=True)
    unit_id = fields.Many2one("hms.unit", "Unit", readonly=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter", readonly=True)
    payer_id = fields.Many2one("hms.payer", "Penjamin", readonly=True)
    encounter_type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("emergency", "Gawat Darurat"),
         ("inpatient", "Rawat Inap"), ("mcu", "MCU"), ("daycare", "One Day Care"),
         ("telemedicine", "Telemedisin")],
        string="Jenis", readonly=True,
    )
    visit_type = fields.Selection(
        [("new", "Baru"), ("followup", "Kontrol Ulang"), ("control", "Kontrol Rutin")],
        string="Kunjungan", readonly=True,
    )
    gender = fields.Selection(
        [("male", "Laki-laki"), ("female", "Perempuan")], readonly=True,
    )
    age_group = fields.Char("Kelompok Umur", readonly=True)
    state = fields.Char(readonly=True)
    visit_count = fields.Integer("Jumlah", readonly=True)

    @property
    def _table_query(self):
        return """
            SELECT
                e.id                                       AS id,
                e.id                                       AS encounter_id,
                e.patient_id                               AS patient_id,
                (e.arrival_at AT TIME ZONE 'UTC')::date    AS arrival_date,
                e.unit_id                                  AS unit_id,
                e.practitioner_id                          AS practitioner_id,
                e.payer_id                                 AS payer_id,
                e.type                                     AS encounter_type,
                e.visit_type                               AS visit_type,
                p.gender                                   AS gender,
                CASE
                    WHEN p.age_years < 1  THEN '0 - <1 th'
                    WHEN p.age_years < 5  THEN '1 - 4 th'
                    WHEN p.age_years < 15 THEN '5 - 14 th'
                    WHEN p.age_years < 25 THEN '15 - 24 th'
                    WHEN p.age_years < 45 THEN '25 - 44 th'
                    WHEN p.age_years < 65 THEN '45 - 64 th'
                    ELSE '65 th ke atas'
                END                                        AS age_group,
                e.state                                    AS state,
                1                                          AS visit_count
            FROM hms_encounter e
            JOIN hms_patient p ON p.id = e.patient_id
            WHERE e.state != 'cancelled'
        """
