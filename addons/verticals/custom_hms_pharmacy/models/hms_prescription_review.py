# -*- coding: utf-8 -*-
"""Telaah resep tiga aspek (PKPO 5.1) dan intervensi apoteker.

=============================================================================
GERBANG LAMA TIDAK DISENTUH
=============================================================================

``hms.prescription`` sudah punya gerbang verifikasi apoteker:
``action_verify()`` yang mengisi ``verified_by_id`` / ``verified_at`` dan
memindahkan resep dari ``submitted`` ke ``verified``. Semua yang ditambahkan
berkas ini bersifat **aditif**:

* nama dan makna ``verified_by_id`` / ``verified_at`` tidak berubah;
* ``action_verify()`` tidak diberi prasyarat baru — resep tetap bisa
  diverifikasi tanpa rincian tiga aspek terisi.

Alasannya bukan kemalasan. Menjadikan telaah tiga aspek sebagai syarat
verifikasi akan mengubah arti sebuah kolom yang sudah dipakai: baris yang
sudah terverifikasi di basis data akan mendadak berarti "sudah ditelaah tiga
aspek", padahal aspek-aspeknya tidak pernah diisi. Yang benar adalah dua
ukuran berdampingan — "sudah diverifikasi" dan "sudah ditelaah lengkap" —
supaya kepatuhan PKPO 5.1 bisa diukur apa adanya, termasuk saat angkanya
memalukan.

=============================================================================
SATU GERBANG BARU, DAN HANYA SATU
=============================================================================

``action_dispense()`` ditolak selama masih ada intervensi apoteker terbuka
yang tindakannya **menahan obat** (``action_taken == 'hold'``). Ini bukan
perubahan makna: resep tanpa intervensi berperilaku persis seperti sebelumnya.
Yang dicegah adalah kejadian yang membuat pencatatan intervensi tidak ada
gunanya — apoteker menahan obat karena curiga dosisnya salah, lalu obat itu
tetap keluar loket karena penahanan hanya berupa catatan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

ASPECT_RESULTS = [
    ("ok", "Sesuai"),
    ("issue", "Ada Masalah"),
    ("na", "Tidak Dapat Dinilai"),
]

ISSUE_TYPES = [
    ("interaction", "Interaksi Obat"),
    ("allergy", "Riwayat Alergi"),
    ("duplication", "Duplikasi Terapi"),
    ("dose", "Dosis / Kekuatan"),
    ("frequency", "Frekuensi"),
    ("route", "Rute Pemberian"),
    ("formulary", "Di Luar Formularium / Fornas"),
    ("restriction", "Restriksi Penjamin"),
    ("contraindication", "Kontraindikasi"),
    ("incomplete", "Resep Tidak Lengkap"),
    ("other", "Lain-lain"),
]

ACTIONS_TAKEN = [
    ("contact_prescriber", "Hubungi Penulis Resep"),
    ("dose_adjust", "Usul Penyesuaian Dosis"),
    ("substitute", "Usul Substitusi"),
    ("hold", "Tahan Obat Sampai Ada Jawaban"),
    ("stop", "Usul Hentikan Obat"),
    ("education", "Edukasi / PIO"),
    ("other", "Lain-lain"),
]


class HmsPrescription(models.Model):
    _inherit = "hms.prescription"

    # --- telaah tiga aspek (PKPO 5.1) -------------------------------------
    review_admin_result = fields.Selection(
        ASPECT_RESULTS, string="Telaah Administratif",
        help="Identitas pasien, ruang/unit, pembiayaan, tanggal, dan identitas "
             "dokter penulis resep.",
    )
    review_admin_note = fields.Text("Catatan Administratif")
    review_pharmaceutic_result = fields.Selection(
        ASPECT_RESULTS, string="Telaah Farmasetik",
        help="Nama obat, bentuk dan kekuatan sediaan, jumlah, instruksi "
             "penggunaan, serta stabilitas dan kompatibilitas.",
    )
    review_pharmaceutic_note = fields.Text("Catatan Farmasetik")
    review_clinical_result = fields.Selection(
        ASPECT_RESULTS, string="Telaah Klinis",
        help="Ketepatan obat, dosis, frekuensi dan rute; duplikasi; alergi; "
             "interaksi; kesesuaian PPK/Fornas; berat badan; kontraindikasi.",
    )
    review_clinical_note = fields.Text("Catatan Klinis")

    review_state = fields.Selection(
        [("pending", "Belum Ditelaah"), ("partial", "Telaah Sebagian"),
         ("issue", "Telaah Lengkap — Ada Temuan"),
         ("complete", "Telaah Lengkap — Tanpa Temuan")],
        string="Status Telaah", compute="_compute_review_state", store=True, index=True,
    )
    reviewed_by_id = fields.Many2one("hms.practitioner", "Ditelaah Oleh", readonly=True,
                                     copy=False)
    reviewed_at = fields.Datetime("Waktu Telaah", readonly=True, copy=False)

    intervention_ids = fields.One2many("hms.prescription.intervention", "prescription_id",
                                       "Intervensi Apoteker")
    open_intervention_count = fields.Integer("Intervensi Terbuka",
                                             compute="_compute_interventions", store=True)
    has_blocking_intervention = fields.Boolean(
        "Ada Penahanan Obat", compute="_compute_interventions", store=True,
        help="Ada intervensi terbuka yang menahan obat sampai penulis resep menjawab.",
    )

    @api.depends("review_admin_result", "review_pharmaceutic_result", "review_clinical_result")
    def _compute_review_state(self):
        for rx in self:
            results = [
                rx.review_admin_result,
                rx.review_pharmaceutic_result,
                rx.review_clinical_result,
            ]
            filled = [r for r in results if r]
            if not filled:
                rx.review_state = "pending"
            elif len(filled) < 3:
                rx.review_state = "partial"
            elif "issue" in filled:
                rx.review_state = "issue"
            else:
                rx.review_state = "complete"

    @api.depends("intervention_ids.state", "intervention_ids.action_taken")
    def _compute_interventions(self):
        for rx in self:
            open_ones = rx.intervention_ids.filtered(lambda i: i.state == "open")
            rx.open_intervention_count = len(open_ones)
            rx.has_blocking_intervention = any(
                i.action_taken == "hold" for i in open_ones
            )

    def action_record_review(self):
        """Catat telaah tiga aspek. TIDAK memindahkan state resep.

        Sengaja terpisah dari ``action_verify()``: verifikasi adalah keputusan
        apoteker untuk meneruskan resep, telaah adalah pemeriksaan yang
        mendahuluinya. Menggabungkannya akan membuat angka kepatuhan PKPO
        selalu 100% karena setiap resep yang lolos otomatis "tertelaah".
        """
        for rx in self:
            missing = [
                label for value, label in (
                    (rx.review_admin_result, _("administratif")),
                    (rx.review_pharmaceutic_result, _("farmasetik")),
                    (rx.review_clinical_result, _("klinis")),
                ) if not value
            ]
            if missing:
                raise UserError(_(
                    "Telaah resep %(name)s belum lengkap. Aspek yang belum "
                    "dinilai: %(aspects)s."
                ) % {"name": rx.name, "aspects": ", ".join(missing)})
            rx.write({
                "reviewed_by_id": rx._current_pharmacist().id,
                "reviewed_at": fields.Datetime.now(),
            })
        return True

    def action_dispense(self):
        """Gerbang tambahan: obat yang sedang ditahan tidak boleh keluar loket.

        Aditif. Resep tanpa intervensi terbuka melewati pemeriksaan ini tanpa
        perubahan perilaku apa pun, sehingga seluruh alur dispensing yang
        sudah ada tetap berarti persis seperti sebelumnya.
        """
        for rx in self:
            if rx.has_blocking_intervention:
                raise UserError(_(
                    "Resep %s sedang ditahan karena ada intervensi apoteker yang "
                    "belum dijawab penulis resep. Selesaikan intervensinya lebih "
                    "dulu, atau tarik penahanannya dengan alasan tercatat."
                ) % rx.name)
        return super().action_dispense()


class HmsPrescriptionIntervention(models.Model):
    _name = "hms.prescription.intervention"
    _description = "Intervensi Apoteker atas Resep"
    _order = "raised_at desc, id desc"

    prescription_id = fields.Many2one("hms.prescription", "Resep", required=True,
                                      ondelete="cascade", index=True)
    line_id = fields.Many2one(
        "hms.prescription.line", "Baris Resep",
        domain="[('prescription_id', '=', prescription_id)]",
        help="Kosongkan bila temuan menyangkut resep secara keseluruhan.",
    )
    issue_type = fields.Selection(ISSUE_TYPES, string="Jenis Temuan", required=True,
                                  default="other", index=True)
    finding = fields.Text("Uraian Temuan", required=True)
    action_taken = fields.Selection(ACTIONS_TAKEN, string="Tindakan Apoteker",
                                    required=True, default="contact_prescriber")
    pharmacist_id = fields.Many2one("hms.practitioner", "Apoteker")
    raised_at = fields.Datetime("Waktu Intervensi", required=True,
                                default=fields.Datetime.now, index=True)

    prescriber_response = fields.Text("Jawaban Penulis Resep")
    outcome = fields.Selection(
        [("accepted", "Diterima — Resep Diubah"),
         ("accepted_no_change", "Diterima — Tanpa Perubahan"),
         ("rejected", "Ditolak Penulis Resep"),
         ("no_response", "Tidak Ada Jawaban")],
        string="Hasil Intervensi",
    )
    state = fields.Selection(
        [("open", "Terbuka"), ("resolved", "Selesai"), ("withdrawn", "Ditarik")],
        default="open", required=True, index=True,
    )
    resolved_at = fields.Datetime("Waktu Penyelesaian", readonly=True, copy=False)
    resolved_by_id = fields.Many2one("res.users", "Diselesaikan Oleh", readonly=True,
                                     copy=False)
    withdraw_reason = fields.Char("Alasan Penarikan")

    def action_resolve(self):
        for rec in self:
            if rec.state != "open":
                raise UserError(_("Intervensi ini sudah tidak terbuka."))
            if not rec.outcome:
                raise UserError(_(
                    "Hasil intervensi wajib dipilih: intervensi tanpa hasil tidak "
                    "dapat dihitung sebagai pelayanan farmasi klinik."
                ))
            rec.write({
                "state": "resolved",
                "resolved_at": fields.Datetime.now(),
                "resolved_by_id": self.env.uid,
            })
        return True

    def action_withdraw(self):
        """Menarik penahanan obat harus beralasan, bukan sekadar menutup baris."""
        for rec in self:
            if rec.state != "open":
                raise UserError(_("Intervensi ini sudah tidak terbuka."))
            if not rec.withdraw_reason:
                raise UserError(_("Alasan penarikan intervensi wajib diisi."))
            rec.write({"state": "withdrawn"})
        return True
