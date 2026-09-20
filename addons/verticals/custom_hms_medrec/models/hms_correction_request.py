# -*- coding: utf-8 -*-
"""Koreksi rekam medis elektronik di luar masa tenggang — PMK 24/2022 Ps. 30.

=============================================================================
KEPUTUSAN: MODEL INI MENOLAK PERMINTAAN YANG MASIH BISA DIKERJAKAN SENDIRI
=============================================================================

PMK 24/2022 Ps. 30 ayat (6)-(7) membagi koreksi menjadi dua: selama masa
tenggang, nakes pemberi layanan mengoreksi catatannya sendiri; lewat masa itu,
koreksi memerlukan persetujuan PMIK/pimpinan.

Godaan desainnya adalah membuat satu alur persetujuan untuk keduanya "supaya
seragam". Itu keliru, dan keliru ke arah yang berbahaya: kalau semua koreksi
harus lewat persetujuan, koreksi kecil yang mendesak (salah ketik dosis, salah
sisi tubuh) tertahan di antrian administrasi. Jadi ``action_submit`` **menolak**
permintaan yang entrinya masih di dalam ``hms.settings.emr_correction_grace_hours``
dan menyuruh penulisnya mengerjakan sendiri.

=============================================================================
KEPUTUSAN: PERMINTAAN DIBUAT DULU, PENOLAKAN MENYUSUL — DUA PANGGILAN
=============================================================================

``create`` di model ini tidak pernah melempar ``UserError``. Di Odoo, membuat
record lalu melempar ``UserError`` di panggilan yang sama berarti record itu
**tidak pernah tersimpan** (transaksinya di-rollback), sehingga pola "catat
permintaan lalu tolak aksinya" menghasilkan antrian persetujuan yang selamanya
kosong. Kegagalan itu sudah pernah terjadi di repo ini (lihat
``custom_hms_billing.apply_discount``). Karena itu pemeriksaan yang bisa gagal
seluruhnya ditaruh di ``action_submit``/``action_approve``, bukan di ``create``.

=============================================================================
KEPUTUSAN: KOREKSI KLINIS TETAP LEWAT ADENDUM, MODEL INI HANYA MENCATAT IZINNYA
=============================================================================

Model ini **tidak menulis ke catatan klinis**. Ia mencatat siapa mengizinkan
apa, dan alasannya. Perubahan isinya tetap dikerjakan lewat mekanisme
append-only milik ``hms.clinical.note`` (``action_revise``), sehingga versi
lama tidak pernah hilang. Sebuah modul rekam medis yang bisa menimpa catatan
yang sudah ditandatangani bukan rekam medis.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsCorrectionRequest(models.Model):
    _name = "hms.correction.request"
    _description = "Permintaan Koreksi Rekam Medis Elektronik"
    _order = "requested_at desc, id desc"

    name = fields.Char("Nomor Permintaan", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)

    target_model = fields.Char(
        "Model Sasaran", required=True,
        help="Nama teknis model yang akan dikoreksi, mis. hms.clinical.note.",
    )
    target_res_id = fields.Integer("ID Record Sasaran", required=True)
    target_label = fields.Char(
        "Uraian Record Sasaran", required=True,
        help="Uraian yang bisa dibaca manusia, mis. 'CPPT 12 Sep 2026 07:30 "
             "oleh dr. Andi'. Disimpan sebagai teks supaya permintaan tetap "
             "bisa diaudit walau recordnya kemudian direvisi.",
    )
    field_label = fields.Char("Bagian yang Dikoreksi", required=True)
    entry_created_at = fields.Datetime(
        "Waktu Entri Dibuat", required=True,
        help="Waktu catatan aslinya ditulis. Dari sinilah masa tenggang "
             "koreksi dihitung, bukan dari waktu permintaan ini dibuat.",
    )
    old_value = fields.Text("Isi Sekarang", required=True)
    new_value = fields.Text("Usulan Perbaikan", required=True)
    reason = fields.Text("Alasan Koreksi", required=True)

    requested_by_id = fields.Many2one("res.users", "Pemohon", required=True, readonly=True,
                                      default=lambda s: s.env.user)
    requested_at = fields.Datetime("Waktu Permintaan", required=True,
                                   default=fields.Datetime.now, index=True)
    grace_hours_applied = fields.Integer(
        "Masa Tenggang Terpakai (jam)", readonly=True,
        help="Nilai hms.settings.emr_correction_grace_hours saat permintaan "
             "dibuat, disimpan supaya keputusan lama tetap bisa dijelaskan "
             "setelah kebijakan berubah.",
    )
    grace_deadline = fields.Datetime(
        "Batas Koreksi Mandiri", compute="_compute_grace_deadline", store=True,
        help="Waktu entri dibuat + masa tenggang. Sebelum batas ini penulis "
             "mengoreksi sendiri; sesudahnya butuh persetujuan PMIK/pimpinan.",
    )
    within_grace = fields.Boolean("Masih Dalam Masa Tenggang",
                                  compute="_compute_grace_deadline", store=True)

    state = fields.Selection(
        [("draft", "Draf"), ("submitted", "Diajukan"), ("approved", "Disetujui"),
         ("rejected", "Ditolak"), ("applied", "Sudah Diterapkan"),
         ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    approved_by_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True, copy=False)
    approved_at = fields.Datetime("Waktu Persetujuan", readonly=True, copy=False)
    decision_note = fields.Text("Catatan Keputusan")
    applied_at = fields.Datetime("Waktu Penerapan", readonly=True, copy=False)
    applied_by_id = fields.Many2one("res.users", "Diterapkan Oleh", readonly=True, copy=False)
    addendum_reference = fields.Char(
        "Referensi Adendum",
        help="Nomor/uraian entri baru yang memuat perbaikannya. Wajib diisi "
             "sebelum permintaan ditandai sudah diterapkan: koreksi yang tidak "
             "menunjuk adendum tidak bisa ditelusuri.",
    )
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor permintaan koreksi harus unik.")

    @api.depends("entry_created_at", "grace_hours_applied")
    def _compute_grace_deadline(self):
        now = fields.Datetime.now()
        for rec in self:
            hours = rec.grace_hours_applied or 0
            if rec.entry_created_at and hours:
                rec.grace_deadline = fields.Datetime.add(rec.entry_created_at, hours=hours)
            else:
                rec.grace_deadline = False
            rec.within_grace = bool(rec.grace_deadline and rec.grace_deadline > now)

    @api.constrains("old_value", "new_value")
    def _check_values_differ(self):
        for rec in self:
            if (rec.old_value or "").strip() == (rec.new_value or "").strip():
                raise ValidationError(_(
                    "Usulan perbaikan sama persis dengan isi sekarang — tidak "
                    "ada yang perlu dikoreksi."
                ))

    @api.model
    def _grace_hours(self):
        hours = self.env["hms.settings"].get_settings().emr_correction_grace_hours
        return hours if hours and hours > 0 else 48

    @api.model_create_multi
    def create(self, vals_list):
        hours = self._grace_hours()
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hms.correction.request") or "/"
            vals.setdefault("grace_hours_applied", hours)
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Permintaan %s sudah diajukan.") % rec.name)
            if rec.within_grace:
                raise UserError(_(
                    "Entri ini masih di dalam masa tenggang koreksi (sampai "
                    "%(d)s). Penulisnya masih boleh mengoreksi sendiri lewat "
                    "adendum, tanpa persetujuan PMIK (PMK 24/2022 Ps. 30 ayat "
                    "(6)). Ajukan permintaan ini hanya setelah masa tenggang "
                    "lewat."
                ) % {"d": rec.grace_deadline})
            rec.write({"state": "submitted"})
        return True

    def _check_approver(self):
        """Wewenang persetujuan: kepala rekam medis atau pimpinan.

        Petugas rekam medis biasa (``group_hms_medrec``) menyiapkan dan
        menelaah permintaan, tetapi tidak menyetujuinya. Pemohon pun tidak
        boleh menyetujui permintaannya sendiri — pemeriksaan itu ada di
        ``action_approve``, bukan di sini, karena bergantung pada record.
        """
        user = self.env.user
        if not (user.has_group("custom_hms_medrec.group_hms_medrec_manager")
                or user.has_group("custom_hms_base.group_hms_manager")):
            raise UserError(_(
                "Koreksi rekam medis di luar masa tenggang hanya dapat "
                "disetujui Kepala Rekam Medis (PMIK) atau pimpinan rumah sakit "
                "(PMK 24/2022 Ps. 30 ayat (7))."
            ))

    def action_approve(self):
        self._check_approver()
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Hanya permintaan Diajukan yang dapat disetujui."))
            if rec.requested_by_id == self.env.user:
                raise UserError(_(
                    "Pemohon tidak dapat menyetujui permintaan koreksinya "
                    "sendiri. Persetujuan yang diberikan sendiri bukan "
                    "persetujuan."
                ))
            rec.write({
                "state": "approved",
                "approved_by_id": self.env.uid,
                "approved_at": fields.Datetime.now(),
            })
        return True

    def action_reject(self):
        self._check_approver()
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("Hanya permintaan Diajukan yang dapat ditolak."))
            if not rec.decision_note:
                raise UserError(_("Alasan penolakan wajib diisi."))
            rec.write({"state": "rejected"})
        return True

    def action_mark_applied(self):
        for rec in self:
            if rec.state != "approved":
                raise UserError(_(
                    "Koreksi hanya boleh ditandai diterapkan setelah disetujui."
                ))
            if not rec.addendum_reference:
                raise UserError(_(
                    "Referensi adendum wajib diisi. Koreksi rekam medis tidak "
                    "pernah menimpa entri lama; ia menambah entri baru, dan "
                    "entri baru itu harus bisa ditunjuk."
                ))
            rec.write({
                "state": "applied",
                "applied_at": fields.Datetime.now(),
                "applied_by_id": self.env.uid,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "applied":
                raise UserError(_(
                    "Koreksi yang sudah diterapkan tidak dapat dibatalkan."
                ))
            rec.write({"state": "cancelled"})
        return True

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_(
                "Permintaan koreksi yang sudah diajukan tidak dapat dihapus."
            ))
        return super().unlink()
