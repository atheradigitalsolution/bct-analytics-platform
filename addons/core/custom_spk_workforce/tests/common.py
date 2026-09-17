# -*- coding: utf-8 -*-
"""Fixtures shaped like the shop floor: one daily welder, one permanent one, one mandor."""

from __future__ import annotations

from odoo.tests.common import TransactionCase


class WorkforceCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Attendance = cls.env["custom.spk.attendance"]
        cls.WorkLog = cls.env["custom.spk.work.log"]
        cls.Allocation = cls.env["custom.spk.labor.allocation"]
        cls.company = cls.env.company

        cls.shift1 = cls.env.ref("custom_spk.shift_1")
        cls.shift3 = cls.env.ref("custom_spk.shift_3")  # night, multiplier 1.3

        plan = cls.env["account.analytic.plan"].sudo().search([], limit=1)
        cls.plan_vals = {"plan_id": plan.id} if plan else {}
        cls.idle_account = cls.env["account.analytic.account"].create(
            {"name": "IDLE-WORKSHOP", **cls.plan_vals})
        cls.internal_account = cls.env["account.analytic.account"].create(
            {"name": "INTERNAL-WORK", **cls.plan_vals})
        cls.company.write({
            "x_spk_idle_analytic_id": cls.idle_account.id,
            "x_spk_internal_analytic_id": cls.internal_account.id,
        })

        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

        cls.daily = cls.env["hr.employee"].create({
            "name": "Tukang Las Harian",
            "x_custom_employment_type": "pegawai_tidak_tetap",
            "x_spk_labor_category": "direct",
            "x_spk_shift_rate": 180000.0,
        })
        cls.permanent_direct = cls.env["hr.employee"].create({
            "name": "Tukang Las Tetap",
            "x_custom_employment_type": "pegawai_tetap",
            "x_spk_labor_category": "direct",
        })
        cls.permanent_indirect = cls.env["hr.employee"].create({
            "name": "Mandor",
            "x_custom_employment_type": "pegawai_tetap",
            "x_spk_labor_category": "indirect",
        })

    @classmethod
    def _spk(cls, event="GIIAS"):
        spk = cls.env["custom.spk"].create({
            "partner_id": cls.partner.id, "event_name": event,
        })
        spk.action_confirm()
        return spk

    def _attendance(self, employee, shift=None, date=None, status="hadir"):
        return self.Attendance.create({
            "employee_id": employee.id,
            "shift_id": (shift or self.shift1).id,
            "date": date or "2026-06-01",
            "attendance_status": status,
        })
