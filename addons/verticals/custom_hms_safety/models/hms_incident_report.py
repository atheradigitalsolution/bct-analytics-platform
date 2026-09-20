# -*- coding: utf-8 -*-
"""Insiden Keselamatan Pasien (IKP) — PMK 11/2017.

=============================================================================
KEPUTUSAN: ANONIMITAS PELAPOR, DAN BATASNYA
=============================================================================

PMK 11/2017 Ps. 19 menyebut pelaporan eksternal ke KNKP bersifat rahasia dan
anonim, dan seluruh bangunan "budaya tanpa menyalahkan" bergantung pada
pelapor yang tidak takut namanya dipakai untuk menghukumnya. Jadi opsi
anonim memang disediakan (`is_anonymous`). Yang TIDAK disediakan adalah
janji bahwa identitas itu mustahil ditemukan, karena janji itu tidak bisa
ditepati di atas Odoo:

1. Setiap baris tabel Odoo membawa ``create_uid``. Kolom itu ditulis oleh
   ORM, tidak bisa dimatikan per-model, dan terbaca oleh siapa pun yang boleh
   membaca barisnya. Menyembunyikannya butuh ``sudo()`` saat create — yang
   berarti setiap laporan dibuat atas nama pengguna sistem, dan bersamanya
   hilang pula kemampuan menegakkan record rule "pelapor boleh membaca
   laporannya sendiri". Kita justru MEMAKAI ``create_uid`` untuk rule itu.
2. Bahkan bila ``create_uid`` bisa dikaburkan, jejak lain tetap ada di luar
   model: log HTTP, jejak transaksi Postgres, dan cadangan basis data.

Karena itu yang ditawarkan model ini didefinisikan dengan jujur:

    Anonim = identitas pelapor **tidak dicatat sebagai data laporan** dan
    tidak pernah tampil pada layar, cetakan, rekapitulasi, maupun pembahasan
    insiden. Identitas itu TIDAK hilang dari jejak teknis basis data.

Konsekuensi teknis: bila ``is_anonymous`` aktif, ``reporter_id`` wajib kosong
(``_check_anonymous_has_no_reporter``). Laporan anonim karena itu benar-benar
tidak punya pelapor di tingkat data — bukan punya pelapor yang disembunyikan
oleh UI, yang akan bocor pada ekspor pertama.

=============================================================================
KEPUTUSAN: MODEL INI SENGAJA **TIDAK** MEWARISI ``hms.audited``
=============================================================================

``hms.audited`` ada untuk satu tujuan: membuktikan siapa membuka rekam medis
pasien (UU PDP). Ia menulis ke ``hms.access.log`` satu baris berisi
``user_id`` + ``model_name`` + ``res_id`` untuk setiap create/read/write.

Bila laporan insiden ikut diaudit, maka setiap laporan — termasuk yang
anonim — melahirkan baris log bernama pengguna dengan ``res_id`` laporan itu.
Pembaca ``hms.access.log`` (administrator/DPO, bukan tim KP) dengan demikian
bisa memetakan laporan anonim kembali ke pelapornya hanya dengan satu join.
Mengaudit insiden justru **membatalkan** kerahasiaan yang diminta PMK 11/2017.

Yang hilang dengan keputusan ini diakui: akses ke data pasien lewat laporan
insiden tidak tercatat di jejak akses rekam medis. Penggantinya bukan audit,
melainkan pembatasan akses — model ini hanya terbaca tim KP dan pelapornya
sendiri, lingkaran yang jauh lebih sempit daripada pembaca rekam medis.
Laporan insiden juga tidak pernah menjadi bagian berkas rekam medis pasien.

Karena alasan yang sama model ini tidak mewarisi ``mail.thread``: chatter
menyimpan penulis tiap pesan, yaitu jejak identitas kedua yang tidak perlu.
Akuntabilitas sisi tim KP tetap ada lewat kolom eksplisit
(``investigator_id``, ``graded_by_id``, ``closed_by_id``) beserta waktunya.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

INCIDENT_TYPES = [
    ("kpc", "KPC — Kondisi Potensial Cedera"),
    ("knc", "KNC — Kejadian Nyaris Cedera"),
    ("ktc", "KTC — Kejadian Tidak Cedera"),
    ("ktd", "KTD — Kejadian Tidak Diharapkan"),
    ("sentinel", "Kejadian Sentinel"),
]

# Bands grading risiko IKP (matriks dampak x probabilitas KKP-RS). Metode
# investigasi menempel pada band-nya, bukan pada jenis insidennya: sebuah KNC
# bergrading merah tetap wajib RCA.
GRADES = [
    ("blue", "Biru — Risiko Rendah"),
    ("green", "Hijau — Risiko Sedang"),
    ("yellow", "Kuning — Risiko Tinggi"),
    ("red", "Merah — Risiko Ekstrem"),
]
RCA_GRADES = ("yellow", "red")


class HmsIncidentReport(models.Model):
    _name = "hms.incident.report"
    _description = "Laporan Insiden Keselamatan Pasien"
    _order = "occurred_at desc, id desc"

    name = fields.Char("Nomor Laporan", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)

    # --- pelapor ----------------------------------------------------------
    is_anonymous = fields.Boolean(
        "Lapor Anonim",
        help="Identitas pelapor tidak dicatat sebagai data laporan dan tidak "
             "pernah ditampilkan atau dicetak. Perhatikan: jejak teknis basis "
             "data (kolom pembuat record, log server, cadangan) tetap ada — "
             "sistem ini tidak menjanjikan anonimitas mutlak.",
    )
    reporter_id = fields.Many2one(
        "hms.practitioner", "Pelapor",
        help="Wajib kosong bila laporan dikirim anonim.",
    )
    reporter_display = fields.Char("Pelapor (tampil)", compute="_compute_reporter_display")
    reporter_unit_id = fields.Many2one("hms.unit", "Unit Pelapor")

    # --- kejadian ---------------------------------------------------------
    unit_id = fields.Many2one("hms.unit", "Unit Tempat Kejadian", required=True, index=True)
    location_detail = fields.Char("Rincian Lokasi", help="Mis. kamar 3B, koridor lift barat.")
    occurred_at = fields.Datetime("Waktu Kejadian", required=True,
                                  default=fields.Datetime.now, index=True)
    reported_at = fields.Datetime("Waktu Lapor", readonly=True, copy=False, index=True)
    due_at = fields.Datetime(
        "Batas Lapor", readonly=True, copy=False, index=True,
        help="Waktu kejadian + hms.settings.incident_report_due_hours. Dibekukan "
             "saat laporan dibuat: tenggat sebuah insiden adalah kebijakan yang "
             "berlaku ketika insiden itu terjadi, bukan kebijakan hari ini.",
    )
    due_hours_applied = fields.Integer(
        "Tenggat Terpakai (jam)", readonly=True, copy=False,
        help="Nilai parameter yang dipakai saat laporan ini dibuat, disimpan "
             "supaya tenggat lama tetap bisa dijelaskan setelah kebijakan berubah.",
    )
    is_late = fields.Boolean("Terlambat Lapor", compute="_compute_is_late", store=True)
    late_hours = fields.Float("Keterlambatan (jam)", compute="_compute_is_late", store=True)

    incident_type = fields.Selection(INCIDENT_TYPES, string="Jenis Insiden",
                                     required=True, default="knc", index=True)
    category = fields.Selection(
        [("fall", "Pasien Jatuh"), ("medication", "Obat / Kesalahan Pengobatan"),
         ("identification", "Identifikasi Pasien"), ("procedure", "Tindakan / Pembedahan"),
         ("infection", "Infeksi Terkait Pelayanan"), ("specimen", "Sampel / Hasil Penunjang"),
         ("equipment", "Alat / Fasilitas"), ("transfusion", "Transfusi Darah"),
         ("communication", "Komunikasi / Serah Terima"), ("other", "Lain-lain")],
        string="Kategori", default="other", required=True, index=True,
        help="Kategori dipakai rekapitulasi mutu, mis. indikator pencegahan "
             "pasien jatuh pada INM.",
    )
    chronology = fields.Text("Kronologi Kejadian")
    immediate_action = fields.Text("Tindakan Segera Setelah Kejadian")
    patient_id = fields.Many2one(
        "hms.patient", "Pasien Terkait", index=True,
        help="Boleh kosong. KPC dan insiden yang menimpa pengunjung atau staf "
             "tetap wajib dilaporkan meski tidak ada pasien yang terlibat.",
    )
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan Terkait")
    patient_harmed = fields.Boolean("Pasien Mengalami Cedera")
    witness_names = fields.Char("Saksi")

    # --- alur tim keselamatan pasien --------------------------------------
    state = fields.Selection(
        [("draft", "Draf"), ("reported", "Dilaporkan"), ("investigating", "Investigasi"),
         ("graded", "Tergrading"), ("closed", "Ditutup")],
        default="draft", required=True, index=True,
    )
    investigator_id = fields.Many2one("res.users", "Investigator", readonly=True, copy=False)
    investigation_started_at = fields.Datetime("Mulai Investigasi", readonly=True, copy=False)
    grade = fields.Selection(GRADES, string="Grading Risiko", index=True)
    investigation_method = fields.Selection(
        [("simple", "Investigasi Sederhana"), ("rca", "Root Cause Analysis")],
        string="Metode Investigasi", compute="_compute_investigation_method", store=True,
        help="Grading kuning dan merah mewajibkan RCA; biru dan hijau cukup "
             "investigasi sederhana oleh atasan langsung.",
    )
    root_cause = fields.Text("Akar Masalah")
    recommendation = fields.Text("Rekomendasi Perbaikan")
    graded_at = fields.Datetime("Waktu Grading", readonly=True, copy=False)
    graded_by_id = fields.Many2one("res.users", "Digrading Oleh", readonly=True, copy=False)
    closure_note = fields.Text("Catatan Penutupan")
    closed_at = fields.Datetime("Waktu Ditutup", readonly=True, copy=False)
    closed_by_id = fields.Many2one("res.users", "Ditutup Oleh", readonly=True, copy=False)

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor laporan insiden harus unik.")
    _open_incident_idx = models.Index(
        "(state, due_at) WHERE state IN ('draft', 'reported', 'investigating')"
    )

    # --- computes ---------------------------------------------------------
    @api.depends("is_anonymous", "reporter_id")
    def _compute_reporter_display(self):
        for rec in self:
            if rec.is_anonymous:
                rec.reporter_display = _("Anonim (identitas tidak dicatat)")
            else:
                rec.reporter_display = rec.reporter_id.display_name or _("Belum diisi")

    @api.depends("reported_at", "due_at")
    def _compute_is_late(self):
        for rec in self:
            if rec.reported_at and rec.due_at and rec.reported_at > rec.due_at:
                rec.is_late = True
                rec.late_hours = (rec.reported_at - rec.due_at).total_seconds() / 3600.0
            else:
                rec.is_late = False
                rec.late_hours = 0.0

    @api.depends("grade")
    def _compute_investigation_method(self):
        for rec in self:
            if not rec.grade:
                rec.investigation_method = False
            else:
                rec.investigation_method = "rca" if rec.grade in RCA_GRADES else "simple"

    # --- constraints ------------------------------------------------------
    @api.constrains("is_anonymous", "reporter_id")
    def _check_anonymous_has_no_reporter(self):
        """Anonim berarti tidak dicatat, bukan dicatat lalu disembunyikan.

        Menyimpan pelapor pada laporan "anonim" hanya memindahkan kebocoran ke
        ekspor pertama yang dibuat seseorang.
        """
        for rec in self:
            if rec.is_anonymous and rec.reporter_id:
                raise ValidationError(_(
                    "Laporan anonim tidak boleh menyimpan pelapor. Kosongkan kolom "
                    "Pelapor, atau matikan opsi Lapor Anonim."
                ))

    @api.constrains("occurred_at", "reported_at")
    def _check_occurred_before_reported(self):
        for rec in self:
            if rec.reported_at and rec.occurred_at and rec.occurred_at > rec.reported_at:
                raise ValidationError(_(
                    "Waktu kejadian tidak boleh setelah waktu lapor."
                ))

    @api.constrains("encounter_id", "patient_id")
    def _check_encounter_matches_patient(self):
        for rec in self:
            if rec.encounter_id and rec.patient_id and rec.encounter_id.patient_id != rec.patient_id:
                raise ValidationError(_(
                    "Kunjungan yang dipilih milik pasien lain."
                ))

    # --- create / write ---------------------------------------------------
    def _incident_due_hours(self):
        """Tenggat pelaporan internal, dari kebijakan RS.

        Dibaca lewat ``get_settings()`` yang sudah ber-``sudo()`` di dalamnya:
        seorang perawat berhak melapor tanpa harus berhak membaca tabel
        pengaturan rumah sakit.
        """
        hours = self.env["hms.settings"].get_settings().incident_report_due_hours
        # Nol/negatif berarti parameter belum diisi; jatuh ke norma PMK 11/2017
        # (2x24 jam) daripada menerbitkan tenggat yang sudah lewat saat dibuat.
        return hours if hours and hours > 0 else 48

    @api.model_create_multi
    def create(self, vals_list):
        hours = self._incident_due_hours()
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.incident.report") or "/"
            vals.setdefault("due_hours_applied", hours)
            if not vals.get("due_at"):
                occurred = fields.Datetime.to_datetime(
                    vals.get("occurred_at") or fields.Datetime.now()
                )
                vals["due_at"] = occurred + timedelta(hours=vals["due_hours_applied"])
        return super().create(vals_list)

    def write(self, vals):
        """Tenggat ikut bergeser hanya selama laporan masih draf.

        Setelah dikirim, ``due_at`` adalah bukti kepatuhan 2x24 jam dan tidak
        boleh berubah karena ada yang mengoreksi jam kejadian di kemudian hari.
        """
        res = super().write(vals)
        if "occurred_at" in vals:
            for rec in self:
                if rec.state == "draft" and rec.occurred_at:
                    hours = rec.due_hours_applied or rec._incident_due_hours()
                    super(HmsIncidentReport, rec).write({
                        "due_at": rec.occurred_at + timedelta(hours=hours),
                    })
        return res

    # --- state machine ----------------------------------------------------
    def action_report(self):
        """Draf -> Dilaporkan. Titik ini yang dihitung terhadap tenggat."""
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Laporan %s sudah dikirim.") % rec.name)
            if not rec.chronology:
                raise UserError(_(
                    "Kronologi wajib diisi: tim KP tidak dapat menginvestigasi "
                    "insiden yang hanya berisi jenis dan lokasi."
                ))
            rec.write({"state": "reported", "reported_at": fields.Datetime.now()})
        return True

    def action_start_investigation(self):
        for rec in self:
            if rec.state != "reported":
                raise UserError(_(
                    "Hanya laporan berstatus Dilaporkan yang dapat diinvestigasi."
                ))
            rec.write({
                "state": "investigating",
                "investigator_id": self.env.uid,
                "investigation_started_at": fields.Datetime.now(),
            })
        return True

    def action_grade(self):
        """Investigasi -> Tergrading. Grading tanpa analisis bukan grading."""
        for rec in self:
            if rec.state != "investigating":
                raise UserError(_("Grading dilakukan setelah investigasi dimulai."))
            if not rec.grade:
                raise UserError(_("Grading risiko wajib dipilih."))
            if not rec.root_cause:
                raise UserError(_(
                    "Akar masalah wajib diisi sebelum grading ditetapkan."
                ))
            if not rec.recommendation:
                raise UserError(_(
                    "Rekomendasi perbaikan wajib diisi: insiden tanpa rekomendasi "
                    "tidak mengubah apa pun."
                ))
            rec.write({
                "state": "graded",
                "graded_at": fields.Datetime.now(),
                "graded_by_id": self.env.uid,
            })
        return True

    def action_close(self):
        for rec in self:
            if rec.state != "graded":
                raise UserError(_(
                    "Laporan hanya dapat ditutup setelah grading dan rekomendasi "
                    "ditetapkan."
                ))
            rec.write({
                "state": "closed",
                "closed_at": fields.Datetime.now(),
                "closed_by_id": self.env.uid,
            })
        return True
