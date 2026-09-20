# -*- coding: utf-8 -*-
"""Pelepasan informasi rekam medis (ROI) — PMK 24/2022 Ps. 34 & 35.

=============================================================================
KEPUTUSAN: DASAR HUKUM ADALAH KOLOM WAJIB YANG BISA MENOLAK
=============================================================================

``legal_basis`` tidak disimpan sebagai keterangan. Ia memilih aturan yang
berlaku, dan aturan itu benar-benar menolak:

* **Ps. 34 — dengan persetujuan pasien.** Permintaan tanpa record
  ``hms.consent`` yang berstatus ``signed`` ditolak saat diajukan. Ini yang
  paling sering dilanggar dalam praktik: petugas asuransi menelepon, berkas
  dikirim, dan persetujuannya "menyusul" — lalu tidak pernah ada. Ps. 34(7)
  menuntut persetujuan untuk keperluan asuransi diberikan tertulis atau
  elektronik; kalau begitu recordnya harus ada sebelum dokumennya keluar,
  bukan sesudah.
* **Ps. 35 — tanpa persetujuan pasien.** Boleh untuk penegak hukum, audit
  medis, KLB, etik/disiplin, pendidikan dan penelitian. Tetapi Ps. 35(2)
  melarang membuka identitas pasien — dan larangan itu masuk akal hanya untuk
  sebagian pemohon: penyidik yang meminta rekam medis korban justru
  *membutuhkan* identitasnya. Jadi anonimisasi diwajibkan khusus untuk
  pendidikan/penelitian dan audit, tidak untuk semuanya.

=============================================================================
KEPUTUSAN: JEJAK PELEPASAN DITULIS KE ``hms.access.log``, BUKAN HANYA KE SINI
=============================================================================

Pertanyaan yang ditanyakan pasien (dan auditor) bukan "permintaan apa yang
pernah masuk ke unit rekam medis", melainkan **"siapa saja yang pernah
melihat rekam medis saya"**. Jawaban itu hanya utuh kalau pelepasan informasi
tercatat di tabel yang sama dengan pembacaan layar. Karena itu
``action_deliver`` menulis satu baris ``hms.access.log`` ber-``action``
``disclose`` — nilai yang ditambahkan modul ini secara aditif.

Barisnya ditulis dengan ``sudo()`` dengan alasan yang sama seperti seluruh
jejak audit di repo ini: ``hms.access.log`` tidak boleh bisa ditulis oleh
pengguna biasa, justru supaya jejaknya tidak bisa dikarang. Ini bukan
melewati hak akses pengguna — keputusan melepas dokumen tetap dijaga
``_check_approver`` dan ``ir.model.access`` di atas.

Model ini sengaja **tidak** mewarisi ``hms.audited``: mixin itu akan menulis
baris ``read``/``write`` setiap kali layar permintaan dibuka, sehingga satu
pelepasan menghasilkan belasan baris dan baris ``disclose`` yang sebenarnya
penting tenggelam di antaranya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

REQUESTER_TYPES = [
    ("patient", "Pasien sendiri"),
    ("proxy", "Keluarga / penerima kuasa"),
    ("insurance", "Asuransi / penjamin"),
    ("law_enforcement", "Penegak hukum"),
    ("court", "Pengadilan / visum et repertum"),
    ("audit", "Audit medis / etik / disiplin"),
    ("research", "Pendidikan & penelitian"),
    ("health_authority", "Dinas kesehatan / KLB"),
    ("other", "Lainnya"),
]

# Pemohon yang, bila memakai dasar Ps. 35, wajib menerima dokumen tanpa
# identitas pasien (Ps. 35 ayat (2)). Penegak hukum dan pengadilan tidak ada
# di daftar ini karena permintaan mereka justru tertuju pada orang tertentu.
MUST_ANONYMIZE = ("research", "audit")


class HmsRoiDocument(models.Model):
    _name = "hms.roi.document"
    _description = "Dokumen yang Dilepas"
    _order = "sequence, id"

    request_id = fields.Many2one("hms.roi.request", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    doc_type = fields.Selection(
        [("summary", "Resume medis / ringkasan pulang"),
         ("clinical_note", "Catatan klinis (CPPT)"),
         ("lab_result", "Hasil laboratorium"),
         ("rad_report", "Hasil radiologi"),
         ("procedure_report", "Laporan tindakan / operasi"),
         ("death_certificate", "Sertifikat kematian"),
         ("medical_letter", "Surat keterangan medis"),
         ("full_record", "Salinan berkas rekam medis lengkap"),
         ("other", "Lainnya")],
        string="Jenis Dokumen", required=True, default="summary",
    )
    description = fields.Char("Keterangan")
    page_count = fields.Integer("Jumlah Lembar")

    @api.depends("doc_type", "description")
    def _compute_display_name(self):
        labels = dict(self._fields["doc_type"].selection)
        for rec in self:
            rec.display_name = rec.description or labels.get(rec.doc_type, "")


class HmsRoiRequest(models.Model):
    _name = "hms.roi.request"
    _description = "Permintaan Pelepasan Informasi Rekam Medis"
    _order = "requested_at desc, id desc"

    name = fields.Char("Nomor Permintaan", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True, index=True,
                                 ondelete="restrict")
    encounter_ids = fields.Many2many(
        "hms.encounter", string="Kunjungan yang Diminta",
        help="Kosongkan bila permintaan menyangkut seluruh riwayat pasien.",
    )

    requester_type = fields.Selection(REQUESTER_TYPES, "Jenis Pemohon",
                                      required=True, default="patient", index=True)
    requester_name = fields.Char("Nama Pemohon", required=True)
    requester_identity_no = fields.Char("No. Identitas Pemohon")
    requester_organization = fields.Char("Instansi / Perusahaan")
    requester_contact = fields.Char("Kontak Pemohon")
    purpose = fields.Text("Tujuan Penggunaan", required=True)

    legal_basis = fields.Selection(
        [("art34", "Ps. 34 — dengan persetujuan pasien"),
         ("art35", "Ps. 35 — tanpa persetujuan pasien")],
        string="Dasar Hukum", required=True, default="art34", index=True,
        help="PMK 24/2022. Ps. 34 ayat (1): pemeliharaan kesehatan, permintaan "
             "pasien, keperluan administrasi/asuransi/jaminan — semuanya "
             "memerlukan persetujuan pasien. Ps. 35 ayat (1): penegak hukum, "
             "etik/disiplin, audit medis, KLB, pendidikan/penelitian, "
             "keselamatan orang lain — tanpa persetujuan, tetapi Ps. 35 ayat "
             "(2) melarang membuka identitas pasien.",
    )
    consent_id = fields.Many2one(
        "hms.consent", "Persetujuan Pasien",
        domain="[('patient_id', '=', patient_id)]",
        help="Wajib untuk dasar Ps. 34 dan harus berstatus Ditandatangani.",
    )
    anonymized = fields.Boolean(
        "Identitas Pasien Disamarkan",
        help="Wajib untuk permintaan pendidikan/penelitian dan audit dengan "
             "dasar Ps. 35 (PMK 24/2022 Ps. 35 ayat (2)).",
    )

    requested_at = fields.Datetime("Waktu Permintaan", required=True,
                                   default=fields.Datetime.now, index=True)
    due_at = fields.Datetime("Target Selesai", readonly=True)
    state = fields.Selection(
        [("draft", "Draf"), ("submitted", "Diajukan ke Pimpinan"),
         ("approved", "Disetujui"), ("rejected", "Ditolak"),
         ("delivered", "Diserahkan"), ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    approved_by_id = fields.Many2one("res.users", "Disetujui Oleh", readonly=True, copy=False)
    approved_at = fields.Datetime("Waktu Persetujuan", readonly=True, copy=False)
    decision_note = fields.Text("Catatan Keputusan Pimpinan")

    document_ids = fields.One2many("hms.roi.document", "request_id", "Dokumen yang Dilepas")
    delivery_channel = fields.Selection(
        [("in_person", "Diambil langsung"), ("post", "Pos / kurir"),
         ("electronic", "Elektronik (surel terenkripsi)"), ("courier_internal", "Kurir internal")],
        string="Cara Penyerahan", default="in_person",
    )
    delivered_at = fields.Datetime("Waktu Penyerahan", readonly=True, copy=False)
    delivered_by_id = fields.Many2one("res.users", "Diserahkan Oleh", readonly=True, copy=False)
    receipt_name = fields.Char("Nama Penerima (tanda terima)")
    receipt_identity_no = fields.Char("No. Identitas Penerima")
    receipt_note = fields.Text("Catatan Tanda Terima")

    access_log_id = fields.Many2one(
        "hms.access.log", "Baris Jejak Akses", readonly=True, copy=False,
        help="Baris hms.access.log ber-action 'disclose' yang dibuat saat "
             "dokumen diserahkan. Kosong berarti belum pernah diserahkan.",
    )
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor permintaan pelepasan informasi harus unik.")

    # --- constraints ------------------------------------------------------
    @api.constrains("legal_basis", "consent_id", "patient_id")
    def _check_consent_belongs_to_patient(self):
        for rec in self:
            if rec.consent_id and rec.consent_id.patient_id != rec.patient_id:
                raise ValidationError(_(
                    "Persetujuan yang dipilih milik pasien lain."
                ))

    @api.constrains("legal_basis", "anonymized", "requester_type")
    def _check_anonymization_required(self):
        for rec in self:
            if (rec.legal_basis == "art35" and rec.requester_type in MUST_ANONYMIZE
                    and not rec.anonymized):
                raise ValidationError(_(
                    "Permintaan %(t)s dengan dasar Ps. 35 wajib diserahkan tanpa "
                    "membuka identitas pasien (PMK 24/2022 Ps. 35 ayat (2)). "
                    "Aktifkan 'Identitas Pasien Disamarkan'."
                ) % {"t": dict(REQUESTER_TYPES).get(rec.requester_type)})

    # --- CRUD -------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        due_days = self.env["hms.settings"].get_settings().roi_response_due_days or 7
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.roi.request") or "/"
            if not vals.get("due_at"):
                requested = fields.Datetime.to_datetime(
                    vals.get("requested_at") or fields.Datetime.now()
                )
                vals["due_at"] = fields.Datetime.add(requested, days=due_days)
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_(
                "Permintaan yang sudah diajukan tidak dapat dihapus. Batalkan "
                "permintaannya agar jejaknya tetap ada."
            ))
        return super().unlink()

    # --- alur -------------------------------------------------------------
    def action_submit(self):
        """Draf -> Diajukan. Di sinilah dasar hukum benar-benar diperiksa."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Permintaan %s sudah diajukan.") % rec.name)
            if rec.legal_basis == "art34":
                if not rec.consent_id:
                    raise UserError(_(
                        "Dasar Ps. 34 menuntut persetujuan pasien. Rekam "
                        "persetujuannya lebih dulu (hms.consent), atau pakai "
                        "dasar Ps. 35 bila permintaan ini memang termasuk "
                        "pengecualian PMK 24/2022 Ps. 35 ayat (1)."
                    ))
                if rec.consent_id.state != "signed":
                    raise UserError(_(
                        "Persetujuan %(c)s berstatus %(s)s, bukan ditandatangani. "
                        "Dokumen tidak boleh dilepas atas persetujuan yang belum "
                        "sah."
                    ) % {"c": rec.consent_id.display_name,
                         "s": dict(rec.consent_id._fields["state"].selection).get(
                             rec.consent_id.state)})
            rec.write({"state": "submitted"})
        return True

    def _check_approver(self):
        """Persetujuan pelepasan adalah wewenang pimpinan, bukan petugas RM.

        PMK 24/2022 Ps. 34 ayat (2): permintaan disampaikan kepada pimpinan
        fasilitas pelayanan kesehatan. Petugas rekam medis yang menyiapkan
        berkasnya karena itu tidak boleh sekaligus menyetujuinya — pemisahan
        ini satu-satunya yang membuat persetujuan berarti sesuatu.
        """
        if not self.env.user.has_group("custom_hms_base.group_hms_manager"):
            raise UserError(_(
                "Hanya pimpinan rumah sakit (grup Manajemen Rumah Sakit) yang "
                "dapat menyetujui atau menolak pelepasan informasi rekam medis "
                "(PMK 24/2022 Ps. 34 ayat (2))."
            ))

    def action_approve(self):
        self._check_approver()
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_(
                    "Hanya permintaan berstatus Diajukan yang dapat disetujui."
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
                raise UserError(_(
                    "Hanya permintaan berstatus Diajukan yang dapat ditolak."
                ))
            if not rec.decision_note:
                raise UserError(_(
                    "Alasan penolakan wajib diisi: pemohon berhak tahu dasar "
                    "penolakannya."
                ))
            rec.write({"state": "rejected"})
        return True

    def action_deliver(self):
        """Disetujui -> Diserahkan. Satu-satunya jalan dokumen keluar."""
        for rec in self:
            if rec.state != "approved":
                raise UserError(_(
                    "Dokumen hanya boleh diserahkan setelah pimpinan menyetujui "
                    "permintaan %s."
                ) % rec.name)
            if not rec.document_ids:
                raise UserError(_(
                    "Belum ada dokumen yang tercatat akan dilepas. Tanda terima "
                    "tanpa daftar dokumen tidak membuktikan apa pun."
                ))
            if not rec.receipt_name:
                raise UserError(_("Nama penerima pada tanda terima wajib diisi."))
            log = rec._log_disclosure()
            rec.write({
                "state": "delivered",
                "delivered_at": fields.Datetime.now(),
                "delivered_by_id": self.env.uid,
                "access_log_id": log.id,
            })
            rec.env["hms.event"].emit("roi.delivered", {
                "request": rec.name,
                "patient_id": rec.patient_id.id,
                "legal_basis": rec.legal_basis,
                "anonymized": rec.anonymized,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "delivered":
                raise UserError(_(
                    "Permintaan yang dokumennya sudah diserahkan tidak dapat "
                    "dibatalkan — yang sudah keluar tidak bisa ditarik kembali "
                    "oleh perubahan status."
                ))
            rec.write({"state": "cancelled"})
        return True

    def _log_disclosure(self):
        """Tulis satu baris jejak akses ber-action ``disclose``.

        ``sudo()`` dipakai karena ``hms.access.log`` memang tidak boleh bisa
        ditulis pengguna biasa — itulah yang membuat jejaknya tidak bisa
        dikarang. Wewenang melepas dokumen sudah dijaga di ``action_deliver``.
        """
        self.ensure_one()
        Log = self.env["hms.access.log"].sudo()
        entry = {
            "user_id": self.env.uid,
            "patient_id": self.patient_id.id,
            "model_name": self._name,
            "res_id": self.id,
            "action": "disclose",
            "access_date": fields.Date.context_today(self),
            "was_in_care_team": False,
        }
        if "encounter_id" in Log._fields and self.encounter_ids:
            entry["encounter_id"] = self.encounter_ids[0].id
        return Log.create(entry)
