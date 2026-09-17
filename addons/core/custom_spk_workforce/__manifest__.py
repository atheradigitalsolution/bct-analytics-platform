# -*- coding: utf-8 -*-
{
    "name": "Custom SPK Workforce",
    "summary": "Shift attendance for pay, work logs for cost, and the monthly "
    "allocation that stops permanent labour disappearing from COGS",
    "description": """
Custom SPK Workforce
====================

Two layers, deliberately not one
--------------------------------

The commonest way this requirement fails is to build a single record and hope it
answers both questions. It cannot, because they are different questions:

* **Attendance** answers *was this person here* -- it drives pay, and its total for
  a month is the number of shifts worked.
* **Work log** answers *which job did their time land on* -- it drives cost, and its
  total is at most the shifts attended, split across however many SPK they touched.

So attendance is the parent and work logs are its children. A worker who spent a
shift on two jobs has one attendance and two logs summing to 1.0.

Daily and permanent workers diverge
-----------------------------------

Only daily workers are paid per shift, so only their logs carry an actual cost.
Permanent workers still have to reach COGS, or margin per job reads better than it
is -- so their shifts are recorded with no money on them and charged later by
`custom.spk.labor.allocation`, which divides the period's permanent direct payroll
by the shifts those people actually worked and books the result per SPK.

That is the shift-count basis, not a flat spread over direct cost. The effort of
recording it is identical -- the supervisor ticks the same box either way -- and
margin per job then reflects who actually worked on it.

The classification is NOT redefined here. ``x_custom_employment_type`` already
exists on ``hr.employee`` in ``custom_hr_payroll_id``, and payroll computes PPh 21
from it. A second field would be two things that can disagree, and the day they
disagree is the day job costing quietly goes wrong. Hence the dependency, and hence
a core module depending on ee_gap -- which ``custom_hht_bridge`` already does.

Idle time is not somebody's job
-------------------------------

A daily worker present with nothing to build is still paid. Forcing that shift onto
an SPK pollutes the cost of a job that did not incur it, so the company carries
three analytic accounts for it (idle, internal work, rework) and the supervisor
picks one. The share of shifts landing on idle is a number worth watching: it is
money out with no job attached.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Operations",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": [
        "custom_spk",
        "custom_hr_payroll_id",
        "hr_attendance",
        "analytic",
    ],
    "capability_tags": ["attendance", "shift", "job-costing", "payroll", "audit-trail"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/hr_employee_views.xml",
        "views/custom_spk_attendance_views.xml",
        "views/custom_spk_labor_allocation_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
