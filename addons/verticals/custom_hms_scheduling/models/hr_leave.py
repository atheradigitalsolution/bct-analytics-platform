# -*- coding: utf-8 -*-
"""Approved HR leave becomes a schedule exception automatically."""
from odoo import _, api, fields, models


class HrLeave(models.Model):
    _inherit = "hr.leave"

    hms_exception_id = fields.Many2one("hms.schedule.exception", "Pengecualian Jadwal",
                                       readonly=True, copy=False)

    def action_validate(self):
        """Approving leave for a practitioner must reach the clinic schedule.

        Without this the HR system and the appointment book disagree, and the
        first person to find out is a patient at the counter.
        """
        res = super().action_validate()
        Practitioner = self.env["hms.practitioner"]
        Exception_ = self.env["hms.schedule.exception"]
        for leave in self:
            practitioner = Practitioner.search(
                [("employee_id", "=", leave.employee_id.id)], limit=1
            )
            if not practitioner or leave.hms_exception_id:
                continue
            exception = Exception_.create({
                "practitioner_id": practitioner.id,
                "type": "sick" if "sakit" in (leave.holiday_status_id.name or "").lower() else "leave",
                "date_from": leave.request_date_from,
                "date_to": leave.request_date_to or leave.request_date_from,
                "leave_id": leave.id,
                "state": "approved",
                "note": leave.private_name or leave.holiday_status_id.name,
            })
            exception.action_approve()
            leave.write({"hms_exception_id": exception.id})
        return res
