# -*- coding: utf-8 -*-
"""Kontrak jam layanan ATHERA — objek komersial yang selama ini tidak ada.

Model ini menjawab satu pertanyaan yang sebelumnya tidak punya tempat di mana pun:
**berapa jam yang sudah dibeli klien untuk layanan ini, dan berapa yang tersisa.**

Pekerjaannya sendiri tetap hidup di model native (`project.task`, `helpdesk.ticket`);
di sini hanya saldonya.
"""

from odoo import api, fields, models


class AtheraServiceContract(models.Model):
    _name = "athera.service.contract"
    _description = "Kontrak Jam Layanan ATHERA"
    _inherit = ["mail.thread"]
    _order = "date_start desc, id desc"
    _rec_name = "name"

    name = fields.Char(
        required=True,
        copy=False,
        default="Baru",
        # Bukan sequence otomatis. Kontrak layanan lahir dari negosiasi, dan nomornya
        # biasanya sudah tertulis di dokumen yang ditandatangani sebelum ada barisnya
        # di sini. Menomori ulang secara otomatis berarti dua nomor untuk satu kontrak.
        help="Nomor kontrak sebagaimana tertulis di dokumen yang disepakati.",
    )

    tenant_id = fields.Many2one(
        "tenant.registry",
        string="Klien",
        required=True,
        ondelete="restrict",
        tracking=True,
        index=True,
    )
    tenant_slug = fields.Char(related="tenant_id.slug", store=True, readonly=True)

    subscription_id = fields.Many2one(
        "athera.subscription",
        string="Langganan",
        ondelete="set null",
        tracking=True,
        help="Opsional. Jam layanan bisa dijual lepas dari langganan bulanan.",
    )

    service_type = fields.Selection(
        [
            ("development", "Pengembangan modul kustom"),
            ("maintenance", "Pemeliharaan"),
            ("training", "Training"),
        ],
        required=True,
        default="development",
        tracking=True,
    )

    date_start = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    date_end = fields.Date(
        tracking=True,
        help="Kosong berarti tanpa batas waktu; saldo jam yang membatasi, bukan tanggal.",
    )

    hours_purchased = fields.Float(
        string="Jam dibeli", required=True, default=0.0, tracking=True, digits=(16, 2),
    )
    hours_consumed = fields.Float(
        string="Jam terpakai", compute="_compute_hours", store=True, digits=(16, 2),
    )
    hours_remaining = fields.Float(
        string="Sisa jam", compute="_compute_hours", store=True, digits=(16, 2),
    )

    currency_id = fields.Many2one(
        "res.currency",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    rate_hour = fields.Monetary(string="Tarif per jam", currency_field="currency_id")
    amount_total = fields.Monetary(
        string="Nilai kontrak", compute="_compute_amount_total", store=True,
        currency_field="currency_id",
    )

    sla_id = fields.Many2one(
        "helpdesk.sla",
        string="SLA",
        ondelete="set null",
        help="SLA dari custom_helpdesk. Tidak diduplikasi di sini — satu definisi saja.",
    )

    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("running", "Berjalan"),
            ("exhausted", "Jam habis"),
            ("closed", "Ditutup"),
        ],
        default="draft",
        required=True,
        tracking=True,
        # `exhausted` dihitung, bukan ditekan tombol: lihat _compute_hours. Sebuah state
        # yang menggambarkan aritmetika tapi hanya berubah kalau ada yang ingat mengkliknya
        # akan salah persis pada kontrak yang paling sibuk.
    )

    task_ids = fields.One2many("project.task", "athera_contract_id", string="Task")
    ticket_ids = fields.One2many("helpdesk.ticket", "athera_contract_id", string="Tiket")
    task_count = fields.Integer(compute="_compute_counts")
    ticket_count = fields.Integer(compute="_compute_counts")

    note = fields.Text()

    # Odoo 19: `models.Constraint`, BUKAN `_sql_constraints`. Bentuk lama diterima tanpa
    # keluhan dan tidak membuat constraint apa pun — cacat senyap yang hanya terlihat
    # karena ada uji yang benar-benar mencoba menyisipkan angka negatif.
    _hours_purchased_non_negative = models.Constraint(
        "CHECK (hours_purchased >= 0)",
        "Jam yang dibeli tidak boleh negatif.",
    )

    @api.depends("task_ids.effective_hours", "ticket_ids.athera_hours_spent",
                 "hours_purchased", "state")
    def _compute_hours(self):
        """Saldo dari dua sumber yang berbeda sifatnya, dijumlahkan apa adanya.

        `effective_hours` berasal dari timesheet sungguhan di project.task.
        `athera_hours_spent` diisi tangan di tiket, karena helpdesk.ticket tidak punya
        timesheet (lihat manifest). Keduanya dijumlahkan tanpa pembobotan — mencampur
        dua tingkat keandalan diam-diam sudah cukup buruk tanpa ditambah faktor koreksi
        yang tidak ada dasarnya.
        """
        for contract in self:
            from_tasks = sum(contract.task_ids.mapped("effective_hours"))
            from_tickets = sum(contract.ticket_ids.mapped("athera_hours_spent"))
            consumed = from_tasks + from_tickets
            contract.hours_consumed = consumed
            contract.hours_remaining = contract.hours_purchased - consumed

            # State mengikuti aritmetika, tapi hanya di antara `running` dan `exhausted`.
            # `draft` dan `closed` adalah keputusan manusia dan tidak boleh dibatalkan
            # oleh sebuah timesheet yang masuk.
            if contract.state in ("running", "exhausted"):
                contract.state = "exhausted" if contract.hours_remaining <= 0 else "running"

    @api.depends("hours_purchased", "rate_hour")
    def _compute_amount_total(self):
        for contract in self:
            contract.amount_total = contract.hours_purchased * contract.rate_hour

    @api.depends("task_ids", "ticket_ids")
    def _compute_counts(self):
        for contract in self:
            contract.task_count = len(contract.task_ids)
            contract.ticket_count = len(contract.ticket_ids)

    def action_start(self):
        """Draf → berjalan. Saldo langsung dihitung ulang supaya kontrak yang dimulai
        dengan nol jam tidak duduk di `running` sampai timesheet pertama menyentuhnya."""
        self.write({"state": "running"})
        self._compute_hours()
        return True

    def action_close(self):
        return self.write({"state": "closed"})

    def action_reset_to_draft(self):
        return self.write({"state": "draft"})

    def action_view_tasks(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Task",
            "res_model": "project.task",
            "view_mode": "list,form",
            "domain": [("athera_contract_id", "=", self.id)],
            "context": {"default_athera_contract_id": self.id},
        }

    def action_view_tickets(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Tiket",
            "res_model": "helpdesk.ticket",
            "view_mode": "list,form",
            "domain": [("athera_contract_id", "=", self.id)],
            "context": {"default_athera_contract_id": self.id},
        }
