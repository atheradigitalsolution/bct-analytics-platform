# -*- coding: utf-8 -*-
"""Tautan dari pekerjaan native ke kontrak jam.

Tidak ada logika di sini selain tautannya. `effective_hours` sudah disediakan
`hr_timesheet`; yang ditambahkan hanyalah "jam ini dibebankan ke kontrak mana".
"""

from odoo import fields, models


class ProjectTask(models.Model):
    _inherit = "project.task"

    athera_contract_id = fields.Many2one(
        "athera.service.contract",
        string="Kontrak layanan ATHERA",
        ondelete="set null",
        index=True,
        # `set null` dan bukan `restrict`: menghapus kontrak tidak boleh menghapus atau
        # mengunci pekerjaan yang sudah tercatat. Task yatim tetap task yang nyata.
        help="Kontrak yang menanggung jam task ini. Kosong berarti tidak dibebankan.",
    )
    athera_tenant_id = fields.Many2one(
        related="athera_contract_id.tenant_id", store=True, readonly=True,
        string="Klien ATHERA",
    )
