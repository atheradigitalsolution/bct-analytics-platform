# -*- coding: utf-8 -*-
"""Pelimpahan wewenang tertulis dokter -> perawat.

PMK 26/2019 Ps. 28 menuntut pelimpahan wewenang **tertulis**, dalam dua bentuk:
*delegatif* (tanggung jawab berpindah ke perawat, mis. memasang infus) dan
*mandat* (di bawah pengawasan pemberi, mis. menjahit luka). Yang membedakan
sebuah pelimpahan dari sebuah catatan bebas adalah bahwa ia bisa **ditanyai**:
"apakah perawat X berwenang melakukan tindakan Y pada tanggal Z?" — itulah
yang disediakan ``check_authorization`` / ``assert_authorized``.

Catatan sumber: UU 38/2014 yang menjadi dasar PMK 26/2019 sudah dicabut oleh
UU 17/2023 dan PP 28/2024, dan **nomor pasal penggantinya belum diverifikasi**.
Karena itu tidak ada nomor pasal PP 28/2024 yang dituliskan sebagai fakta di
mana pun pada model ini; rujukan yang dipakai hanya PMK 26/2019.

Keputusan: masa berlaku dijaga oleh pemeriksaan, bukan oleh state saja.
``state == 'active'`` yang tidak pernah ditinjau ulang akan tetap "aktif"
bertahun-tahun setelah tanggalnya lewat; karena itu ``check_authorization``
selalu menguji tanggal, dan cron hanya merapikan tampilannya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsDelegation(models.Model):
    _name = "hms.delegation"
    _description = "Pelimpahan Wewenang Dokter ke Perawat"
    _order = "valid_from desc, id desc"

    name = fields.Char("Nomor", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    doctor_id = fields.Many2one(
        "hms.practitioner", "Dokter Pemberi", required=True, index=True,
        domain="[('type', '=', 'doctor')]",
    )
    nurse_id = fields.Many2one(
        "hms.practitioner", "Perawat Penerima", required=True, index=True,
        domain="[('type', 'in', ['nurse', 'midwife'])]",
    )
    kind = fields.Selection(
        [("delegative", "Delegatif — tanggung jawab berpindah"),
         ("mandate", "Mandat — di bawah pengawasan pemberi")],
        string="Jenis Pelimpahan", default="delegative", required=True,
        help="PMK 26/2019 tentang Keperawatan membedakan pelimpahan delegatif "
             "dan mandat; keduanya wajib tertulis.",
    )
    supervision_required = fields.Boolean(
        "Wajib Diawasi Langsung", compute="_compute_supervision", store=True, readonly=False,
        help="Otomatis aktif untuk pelimpahan mandat; dapat dinaikkan untuk "
             "pelimpahan delegatif bila kebijakan unit menghendaki.",
    )
    unit_id = fields.Many2one("hms.unit", "Unit Berlaku",
                              help="Kosongkan bila berlaku di seluruh unit.")
    procedure_ids = fields.Many2many(
        "hms.icd9", "hms_delegation_icd9_rel", "delegation_id", "icd9_id",
        string="Lingkup Tindakan (ICD-9-CM)",
    )
    scope_note = fields.Text(
        "Lingkup Tindakan (uraian)",
        help="Untuk tindakan keperawatan yang tidak punya kode ICD-9-CM.",
    )

    valid_from = fields.Date("Berlaku Dari", required=True,
                             default=fields.Date.context_today, index=True)
    valid_until = fields.Date("Berlaku Sampai", required=True, index=True)
    state = fields.Selection(
        [("draft", "Draf"), ("active", "Berlaku"), ("expired", "Kedaluwarsa"),
         ("revoked", "Dicabut")],
        default="draft", required=True, index=True,
    )
    signed_at = fields.Datetime("Waktu Penandatanganan", readonly=True, copy=False)
    signed_by_id = fields.Many2one("res.users", "Ditandatangani Oleh", readonly=True,
                                   copy=False)
    revoked_at = fields.Datetime("Waktu Pencabutan", readonly=True, copy=False)
    revoke_reason = fields.Char("Alasan Pencabutan")
    note = fields.Text("Catatan")

    is_currently_valid = fields.Boolean("Berlaku Hari Ini", compute="_compute_currently_valid")

    _name_uniq = models.Constraint("unique(name)", "Nomor pelimpahan wewenang harus unik.")
    _dates_chk = models.Constraint(
        "CHECK (valid_until >= valid_from)",
        "Masa berlaku pelimpahan wewenang tidak boleh berakhir sebelum dimulai.",
    )

    # --- computes ---------------------------------------------------------
    @api.depends("kind")
    def _compute_supervision(self):
        for rec in self:
            rec.supervision_required = rec.kind == "mandate"

    def _compute_currently_valid(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_currently_valid = rec._covers_date(today)

    # --- helpers ----------------------------------------------------------
    def _covers_date(self, on_date):
        self.ensure_one()
        if self.state != "active":
            return False
        if not (self.valid_from and self.valid_until):
            return False
        return self.valid_from <= on_date <= self.valid_until

    # --- constraints ------------------------------------------------------
    @api.constrains("doctor_id", "nurse_id")
    def _check_two_different_people(self):
        for rec in self:
            if rec.doctor_id and rec.doctor_id == rec.nurse_id:
                raise ValidationError(_(
                    "Pemberi dan penerima pelimpahan wewenang harus dua orang berbeda."
                ))

    @api.constrains("procedure_ids", "scope_note", "state")
    def _check_scope_is_written(self):
        """Pelimpahan tanpa lingkup adalah izin terbuka, bukan pelimpahan."""
        for rec in self:
            if rec.state == "active" and not rec.procedure_ids and not rec.scope_note:
                raise ValidationError(_(
                    "Pelimpahan wewenang yang berlaku harus menyebutkan lingkup "
                    "tindakannya, baik sebagai kode ICD-9-CM maupun uraian tertulis."
                ))

    # --- create -----------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.delegation") or "/"
        return super().create(vals_list)

    # --- workflow ---------------------------------------------------------
    def action_activate(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Pelimpahan %s sudah tidak berstatus draf.") % rec.name)
            rec.write({
                "state": "active",
                "signed_at": fields.Datetime.now(),
                "signed_by_id": self.env.uid,
            })
        return True

    def action_revoke(self):
        for rec in self:
            if rec.state not in ("active", "draft"):
                raise UserError(_("Pelimpahan %s sudah berakhir.") % rec.name)
            if not rec.revoke_reason:
                raise UserError(_("Alasan pencabutan wajib diisi."))
            rec.write({"state": "revoked", "revoked_at": fields.Datetime.now()})
        return True

    @api.model
    def _cron_expire(self):
        stale = self.search([
            ("state", "=", "active"),
            ("valid_until", "<", fields.Date.context_today(self)),
        ])
        stale.write({"state": "expired"})
        return len(stale)

    # --- pertanyaan yang harus bisa dijawab -------------------------------
    @api.model
    def check_authorization(self, nurse, procedure=None, on_date=None):
        """Kembalikan pelimpahan yang menutupi tindakan ini, atau recordset kosong.

        ``nurse`` boleh berupa record ``hms.practitioner`` atau id-nya;
        ``procedure`` boleh record ``hms.icd9``, id-nya, atau None untuk
        pertanyaan "apakah perawat ini punya pelimpahan aktif sama sekali".

        Tanggal diuji di sini, tidak dipercayakan pada ``state`` saja: sebuah
        baris yang lupa disapu cron akan tetap bertuliskan "Berlaku" setelah
        tanggalnya lewat, dan justru pada kasus itulah jawabannya harus tidak.
        """
        nurse_id = nurse.id if hasattr(nurse, "id") else nurse
        on_date = fields.Date.to_date(on_date) or fields.Date.context_today(self)
        domain = [
            ("nurse_id", "=", nurse_id),
            ("state", "=", "active"),
            ("valid_from", "<=", on_date),
            ("valid_until", ">=", on_date),
        ]
        candidates = self.search(domain)
        if procedure is None:
            return candidates
        procedure_id = procedure.id if hasattr(procedure, "id") else procedure
        return candidates.filtered(
            lambda d: procedure_id in d.procedure_ids.ids
        )

    @api.model
    def assert_authorized(self, nurse, procedure=None, on_date=None):
        """Sama seperti ``check_authorization``, tetapi menolak bila tidak ada.

        Dipakai pemanggil yang memang harus berhenti. Tidak ada record yang
        dibuat di jalur ini: membuat baris lalu melempar ``UserError`` berarti
        barisnya ikut hilang bersama transaksi yang dibatalkan.
        """
        found = self.check_authorization(nurse, procedure=procedure, on_date=on_date)
        if found:
            return found
        nurse_rec = nurse if hasattr(nurse, "name") else self.env["hms.practitioner"].browse(nurse)
        raise UserError(_(
            "Tidak ada pelimpahan wewenang tertulis yang berlaku untuk %(nurse)s "
            "pada %(date)s untuk tindakan ini. PMK 26/2019 mensyaratkan pelimpahan "
            "wewenang dalam bentuk tertulis sebelum tindakan dilakukan."
        ) % {
            "nurse": nurse_rec.display_name,
            "date": fields.Date.to_date(on_date) or fields.Date.context_today(self),
        })
