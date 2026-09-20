# -*- coding: utf-8 -*-
"""RL 4a — inpatient morbidity by principal diagnosis."""
from odoo import fields, models


class HmsReportRl4(models.Model):
    _name = "hms.report.rl4"
    _description = "RL 4a — Morbiditas Rawat Inap"
    _auto = False
    _order = "discharge_date desc"

    encounter_id = fields.Many2one("hms.encounter", readonly=True)
    discharge_date = fields.Date("Tanggal Keluar", readonly=True)
    icd10_id = fields.Many2one("hms.icd10", "Diagnosis Utama", readonly=True)
    icd10_code = fields.Char("Kode ICD-10", readonly=True)
    gender = fields.Selection(
        [("male", "Laki-laki"), ("female", "Perempuan")], readonly=True,
    )
    age_group = fields.Char("Kelompok Umur", readonly=True)
    discharge_disposition = fields.Char("Cara Keluar", readonly=True)
    is_death = fields.Integer("Meninggal", readonly=True)
    case_count = fields.Integer("Jumlah Kasus", readonly=True)
    length_of_stay = fields.Integer("Lama Dirawat", readonly=True)

    @property
    def _table_query(self):
        # Only final principal diagnoses: RL 4a reports what the patient was
        # discharged with, and counting working diagnoses would double-report
        # every case that was revised during the stay.
        return """
            SELECT
                e.id                                          AS id,
                e.id                                          AS encounter_id,
                (e.closed_at AT TIME ZONE 'UTC')::date        AS discharge_date,
                dx.icd10_id                                   AS icd10_id,
                i.code                                        AS icd10_code,
                p.gender                                      AS gender,
                CASE
                    WHEN p.age_years < 1  THEN '0 - <1 th'
                    WHEN p.age_years < 5  THEN '1 - 4 th'
                    WHEN p.age_years < 15 THEN '5 - 14 th'
                    WHEN p.age_years < 25 THEN '15 - 24 th'
                    WHEN p.age_years < 45 THEN '25 - 44 th'
                    WHEN p.age_years < 65 THEN '45 - 64 th'
                    ELSE '65 th ke atas'
                END                                           AS age_group,
                e.discharge_disposition                       AS discharge_disposition,
                CASE WHEN e.discharge_disposition = 'deceased' THEN 1 ELSE 0 END AS is_death,
                1                                             AS case_count,
                COALESCE(a.length_of_stay, 0)                 AS length_of_stay
            FROM hms_encounter e
            JOIN hms_patient p ON p.id = e.patient_id
            LEFT JOIN hms_admission a ON a.encounter_id = e.id
            JOIN hms_diagnosis dx ON dx.encounter_id = e.id
                 AND dx.rank = 'primary' AND dx.stage = 'final'
            JOIN hms_icd10 i ON i.id = dx.icd10_id
            WHERE e.type = 'inpatient' AND e.state = 'discharged'
        """
