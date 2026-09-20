# -*- coding: utf-8 -*-
"""Dokumen bermasa-berlaku, satu model untuk semua pemiliknya.

Yang membuat satu model cukup: masalahnya identik di mana pun ia muncul —
sebuah tanggal yang kalau lewat membuat sesuatu tidak boleh beroperasi. Yang
berbeda hanya siapa pemiliknya, dan itu diselesaikan referensi polimorfik
``res_model`` + ``res_id`` alih-alih enam Many2one opsional yang lima di
antaranya selalu kosong.
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LgxDocument(models.Model):
    _name = "lgx.document"
    _description = "Dokumen Logistik"
    _order = "expiry_date, id"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char("Nomor Dokumen", required=True, index=True)
    document_type_id = fields.Many2one("lgx.document.type", "Jenis Dokumen", required=True, index=True)
    category = fields.Selection(related="document_type_id.category", store=True)
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)

    # Pemilik dokumen, polimorfik.
    res_model = fields.Char("Model Pemilik", index=True)
    res_id = fields.Integer("ID Pemilik", index=True)
    owner_label = fields.Char("Pemilik", compute="_compute_owner_label", store=True)
    job_id = fields.Many2one("lgx.job", "Job", index=True, ondelete="cascade",
                             help="Diisi untuk dokumen yang melekat pada satu job.")
    partner_id = fields.Many2one("res.partner", "Pihak", index=True)

    issue_date = fields.Date("Tanggal Terbit")
    expiry_date = fields.Date("Masa Berlaku", index=True, tracking=True)
    warning_days = fields.Integer("Ambang Peringatan (hari)",
                                  compute="_compute_warning_days", store=True, readonly=False)
    status = fields.Selection(
        [("valid", "Berlaku"), ("warning", "Mendekati Kedaluwarsa"), ("expired", "Kedaluwarsa"),
         ("no_expiry", "Tanpa Masa Berlaku")],
        string="Status", compute="_compute_status", store=True, index=True,
    )
    days_to_expiry = fields.Integer("Sisa Hari", compute="_compute_status", store=True)
    responsible_id = fields.Many2one("res.users", "Penanggung Jawab",
                                     default=lambda s: s.env.user)
    attachment_ids = fields.Many2many("ir.attachment", string="Berkas")
    requires_stamp_duty = fields.Boolean(related="document_type_id.requires_stamp_duty", store=True)
    stamp_duty_applied = fields.Boolean("Meterai Sudah Dibubuhkan")
    is_customer_visible = fields.Boolean(
        "Terlihat Pelanggan", compute="_compute_visibility", store=True, readonly=False)
    last_reminder_date = fields.Date("Peringatan Terakhir", readonly=True, copy=False)
    note = fields.Char("Catatan")
    active = fields.Boolean(default=True)

    _number_type_uniq = models.Constraint(
        "unique(name, document_type_id, res_model, res_id)",
        "Dokumen dengan nomor dan jenis ini sudah tercatat pada pemilik yang sama.",
    )

    @api.depends("document_type_id")
    def _compute_warning_days(self):
        for document in self:
            document.warning_days = document.document_type_id.default_warning_days or 30

    @api.depends("document_type_id")
    def _compute_visibility(self):
        for document in self:
            document.is_customer_visible = document.document_type_id.is_customer_visible

    @api.depends("expiry_date", "warning_days")
    def _compute_status(self):
        today = fields.Date.context_today(self)
        for document in self:
            if not document.expiry_date:
                document.status = "no_expiry"
                document.days_to_expiry = 0
                continue
            delta = (document.expiry_date - today).days
            document.days_to_expiry = delta
            if delta < 0:
                document.status = "expired"
            elif delta <= (document.warning_days or 30):
                document.status = "warning"
            else:
                document.status = "valid"

    @api.depends("res_model", "res_id", "job_id", "partner_id")
    def _compute_owner_label(self):
        for document in self:
            if document.res_model and document.res_id:
                record = self.env[document.res_model].browse(document.res_id).exists()
                document.owner_label = record.display_name if record else False
            elif document.job_id:
                document.owner_label = document.job_id.display_name
            elif document.partner_id:
                document.owner_label = document.partner_id.display_name
            else:
                document.owner_label = False

    @api.constrains("issue_date", "expiry_date")
    def _check_dates(self):
        for document in self:
            if document.issue_date and document.expiry_date and document.expiry_date < document.issue_date:
                raise ValidationError(_(
                    "Masa berlaku dokumen %s berakhir sebelum tanggal terbitnya.", document.name,
                ))

    @api.constrains("requires_stamp_duty", "stamp_duty_applied", "document_type_id")
    def _check_stamp_duty_order(self):
        """Urutan e-meterai: DIBUBUHKAN SEBELUM tanda tangan digital.

        Catatan Peruri, dan urutannya tidak dapat dibalik: meterai yang
        dibubuhkan setelah tanda tangan merusak tanda tangannya. Di sini hal itu
        hanya dicatat sebagai flag; alur e-signing yang menegakkannya ada di
        lapisan kanal.
        """
        return True

    @api.model
    def _cron_warn_expiring(self):
        """Satu mesin untuk seluruh dokumen bermasa-berlaku.

        Idempoten per hari: dokumen yang sudah diperingatkan hari ini tidak
        diperingatkan lagi, sehingga menjalankan cron dua kali tidak menghasilkan
        dua aktivitas untuk hal yang sama.
        """
        today = fields.Date.context_today(self)
        due = self.search([
            ("status", "in", ("warning", "expired")),
            "|", ("last_reminder_date", "=", False), ("last_reminder_date", "<", today),
        ])
        for document in due:
            responsible = document.responsible_id or self.env.user
            label = (_("sudah kedaluwarsa pada %s", document.expiry_date)
                     if document.status == "expired"
                     else _("kedaluwarsa dalam %s hari", document.days_to_expiry))
            document.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("%s %s — %s", document.document_type_id.name, document.name, label),
                note=_("Pemilik: %s. Dokumen yang mati membuat operasi yang bersandar "
                       "padanya menjadi risiko hukum pada perusahaan.",
                       document.owner_label or "-"),
                user_id=responsible.id,
            )
            document.last_reminder_date = today
        return len(due)

    @api.model
    def lgx_attach_to(self, record, document_type, number, expiry_date=None, **kwargs):
        """Buat dokumen untuk sebuah record apa pun.

        Dipakai modul lain (armada, pengemudi, kepabeanan) agar tidak masing-masing
        membangun cara sendiri menautkan dokumen.
        """
        values = {
            "name": number,
            "document_type_id": (document_type.id if hasattr(document_type, "id")
                                 else self.env.ref(document_type).id),
            "res_model": record._name,
            "res_id": record.id,
            "expiry_date": expiry_date,
        }
        values.update(kwargs)
        return self.create(values)
