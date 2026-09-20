# -*- coding: utf-8 -*-
"""Revenue by unit and tariff category."""
from odoo import fields, models


class HmsReportRevenue(models.Model):
    _name = "hms.report.revenue"
    _description = "Laporan Pendapatan"
    _auto = False
    _order = "service_date desc"

    bill_line_id = fields.Many2one("hms.bill.line", readonly=True)
    bill_id = fields.Many2one("hms.bill", readonly=True)
    service_date = fields.Date("Tanggal Layanan", readonly=True)
    unit_id = fields.Many2one("hms.unit", "Unit Pelaksana", readonly=True)
    practitioner_id = fields.Many2one("hms.practitioner", "Praktisi", readonly=True)
    category_id = fields.Many2one("hms.tariff.category", "Kategori", readonly=True)
    payer_id = fields.Many2one("hms.payer", "Penjamin", readonly=True)
    report_section = fields.Char("Kelompok", readonly=True)
    currency_id = fields.Many2one("res.currency", readonly=True)
    amount_gross = fields.Monetary("Bruto", readonly=True)
    amount_discount = fields.Monetary("Diskon", readonly=True)
    amount_payer = fields.Monetary("Porsi Penjamin", readonly=True)
    amount_patient = fields.Monetary("Porsi Pasien", readonly=True)
    amount_medical = fields.Monetary("Jasa Medis", readonly=True)
    amount_facility = fields.Monetary("Jasa Sarana", readonly=True)
    amount_consumable = fields.Monetary("BHP", readonly=True)
    qty = fields.Float("Jumlah", readonly=True)

    @property
    def _table_query(self):
        return """
            SELECT
                l.id              AS id,
                l.id              AS bill_line_id,
                l.bill_id         AS bill_id,
                l.service_date    AS service_date,
                l.unit_id         AS unit_id,
                l.practitioner_id AS practitioner_id,
                t.category_id     AS category_id,
                b.payer_id        AS payer_id,
                c.report_section  AS report_section,
                l.currency_id     AS currency_id,
                l.qty * l.unit_price AS amount_gross,
                l.discount_amount AS amount_discount,
                l.amount_payer    AS amount_payer,
                l.amount_patient  AS amount_patient,
                l.amount_medical  AS amount_medical,
                l.amount_facility AS amount_facility,
                l.amount_consumable AS amount_consumable,
                l.qty             AS qty
            FROM hms_bill_line l
            JOIN hms_bill b   ON b.id = l.bill_id
            JOIN hms_tariff t ON t.id = l.tariff_id
            JOIN hms_tariff_category c ON c.id = t.category_id
            WHERE l.state = 'confirmed'
        """
