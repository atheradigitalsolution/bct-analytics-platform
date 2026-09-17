# -*- coding: utf-8 -*-
"""Tautan tiket pemeliharaan ke kontrak jam, plus jam yang diisi tangan.

`helpdesk.ticket` (custom_helpdesk) tidak punya kaitan ke project maupun ke
`account.analytic.line`, jadi tidak ada timesheet yang bisa dijumlahkan darinya.
Field jam di sini diisi manusia. Itu lebih lemah daripada timesheet dan dinyatakan
begitu, bukan disamarkan sebagai angka terhitung.
"""

from odoo import fields, models


class HelpdeskTicket(models.Model):
    _inherit = "helpdesk.ticket"

    athera_contract_id = fields.Many2one(
        "athera.service.contract",
        string="Kontrak layanan ATHERA",
        ondelete="set null",
        index=True,
        help="Kontrak yang menanggung jam tiket ini. Kosong berarti tidak dibebankan.",
    )
    athera_tenant_id = fields.Many2one(
        related="athera_contract_id.tenant_id", store=True, readonly=True,
        string="Klien ATHERA",
    )
    athera_hours_spent = fields.Float(
        string="Jam terpakai",
        digits=(16, 2),
        default=0.0,
        help="Diisi tangan — helpdesk.ticket belum punya timesheet.",
    )

    _athera_hours_spent_non_negative = models.Constraint(
        "CHECK (athera_hours_spent >= 0)",
        "Jam terpakai tidak boleh negatif.",
    )
