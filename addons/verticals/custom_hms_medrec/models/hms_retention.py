# -*- coding: utf-8 -*-
"""Retensi rekam medis — PMK 24/2022 Ps. 39.

=============================================================================
KEPUTUSAN: SISTEM INI TIDAK PERNAH MENGHAPUS APA PUN
=============================================================================

Ps. 39 ayat (1) menetapkan penyimpanan **paling singkat** 25 tahun sejak
kunjungan terakhir; ayat (2) membolehkan pengecualian bila rekamnya masih
dimanfaatkan; ayat (3) menyerahkan tata cara pemusnahan ke peraturan lain —
dan juknis pemusnahan RME pasca-PMK 24/2022 belum ditemukan.

Karena itu model ini berhenti tepat sebelum garis yang tidak jelas: ia
**mengusulkan**, tidak pernah menghapus. Tidak ada satu pun baris kode di sini
yang memanggil ``unlink`` pada data pasien. Sebuah tombol "musnahkan" yang
ditulis sekarang akan mengarang tata cara yang belum terbit, dan kesalahannya
tidak bisa diperbaiki.

Yang dihasilkan modul ini adalah **daftar tinjauan** dengan keputusan manusia
di atasnya, siap menjadi berita acara ketika juknisnya ada.

=============================================================================
KEPUTUSAN: PENGECUALIAN DIHITUNG, BUKAN DICENTANG
=============================================================================

"Klaim atau perkara aktif" bukan pertanyaan yang boleh dijawab dengan ingatan
petugas. ``_has_active_claim`` menghitungnya dari data, dan
``custom_hms_casemix`` mengganti implementasinya begitu ``hms.claim`` ada.
Di modul ini jawabannya ``False`` — bukan karena tidak ada klaim, melainkan
karena modul ini tidak punya cara mengetahuinya, dan itu ditulis terang-
terangan alih-alih ditebak. ``legal_hold`` tetap manual karena perkara hukum
memang tidak tercatat di SIMRS.

Konsekuensi yang diterima: dipasang tanpa ``custom_hms_casemix``, tinjauan
retensi hanya menjaga pengecualian hukum. Itu lebih baik daripada mengklaim
memeriksa klaim yang tidak bisa dibacanya.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsRetentionRule(models.Model):
    _name = "hms.retention.rule"
    _description = "Aturan Retensi Rekam Medis"
    _order = "sequence, id"

    name = fields.Char("Nama Aturan", required=True)
    sequence = fields.Integer(default=10)
    scope = fields.Selection(
        [("all", "Seluruh rekam medis"), ("outpatient", "Rawat jalan"),
         ("inpatient", "Rawat inap"), ("emergency", "Gawat darurat")],
        string="Cakupan", required=True, default="all",
        help="Menentukan kunjungan mana yang dihitung sebagai 'kunjungan "
             "terakhir' untuk aturan ini.",
    )
    retention_years = fields.Integer(
        "Retensi (tahun)", required=True,
        default=lambda s: s._default_retention_years(),
        help="Diisi dari hms.settings.emr_retention_years saat aturan dibuat. "
             "PMK 24/2022 Ps. 39 ayat (1): paling singkat 25 tahun. Nilai di "
             "bawah 25 ditolak.",
    )
    note = fields.Text("Catatan")
    active = fields.Boolean(default=True)
    review_ids = fields.One2many("hms.retention.review", "rule_id", "Tinjauan")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _scope_uniq = models.Constraint(
        "unique(company_id, scope)",
        "Hanya boleh ada satu aturan retensi per cakupan.",
    )

    @api.model
    def _default_retention_years(self):
        years = self.env["hms.settings"].get_settings().emr_retention_years
        return years if years and years > 0 else 25

    @api.constrains("retention_years")
    def _check_minimum_retention(self):
        """Batas bawahnya norma, bukan preferensi.

        ``hms.settings.emr_retention_years`` boleh dinaikkan rumah sakit, tidak
        boleh diturunkan di bawah 25 — menyimpan lebih lama selalu sah,
        menyimpan lebih singkat melanggar Ps. 39 ayat (1).
        """
        for rec in self:
            if rec.retention_years < 25:
                raise ValidationError(_(
                    "Retensi rekam medis tidak boleh kurang dari 25 tahun "
                    "(PMK 24/2022 Ps. 39 ayat (1)). Nilai yang dimasukkan: %s."
                ) % rec.retention_years)


class HmsRetentionReview(models.Model):
    _name = "hms.retention.review"
    _description = "Tinjauan Retensi Rekam Medis"
    _order = "due_date, id"

    rule_id = fields.Many2one("hms.retention.rule", "Aturan", required=True,
                              ondelete="restrict", index=True)
    patient_id = fields.Many2one("hms.patient", "Pasien", required=True,
                                 ondelete="restrict", index=True)
    last_visit_date = fields.Date("Kunjungan Terakhir", required=True)
    due_date = fields.Date("Jatuh Tempo Retensi", required=True, index=True)
    state = fields.Selection(
        [("pending", "Menunggu Tinjauan"), ("reviewed", "Sudah Ditinjau")],
        default="pending", required=True, index=True,
    )
    disposition = fields.Selection(
        [("retain", "Tetap Disimpan"), ("archive", "Dialihmediakan / Diarsipkan"),
         ("destruction_proposed", "Diusulkan Dimusnahkan")],
        string="Keputusan Tinjauan",
        help="'Diusulkan dimusnahkan' berhenti sebagai usulan. Sistem ini tidak "
             "melakukan pemusnahan: tata caranya (PMK 24/2022 Ps. 39 ayat (3)) "
             "menunggu peraturan turunannya.",
    )
    has_active_claim = fields.Boolean("Ada Klaim Berjalan", compute="_compute_exception",
                                      store=True)
    legal_hold = fields.Boolean(
        "Ditahan karena Perkara Hukum",
        help="Dicentang manual. Perkara hukum tidak tercatat di SIMRS, jadi "
             "sistem tidak bisa menyimpulkannya sendiri.",
    )
    legal_hold_reference = fields.Char("Nomor Perkara / Referensi")
    is_excepted = fields.Boolean("Dikecualikan", compute="_compute_exception", store=True,
                                 help="Dikecualikan dari pemusnahan (Ps. 39 ayat (2)).")
    exception_reason = fields.Char("Alasan Pengecualian", compute="_compute_exception",
                                   store=True)
    reviewed_by_id = fields.Many2one("res.users", "Ditinjau Oleh", readonly=True, copy=False)
    reviewed_at = fields.Datetime("Waktu Tinjauan", readonly=True, copy=False)
    note = fields.Text("Catatan Tinjauan")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _patient_rule_uniq = models.Constraint(
        "unique(patient_id, rule_id)",
        "Satu pasien hanya punya satu tinjauan per aturan retensi.",
    )

    def _has_active_claim(self):
        """Hook. ``custom_hms_casemix`` menggantinya dengan pemeriksaan sungguhan."""
        self.ensure_one()
        return False

    @api.depends("patient_id", "legal_hold")
    def _compute_exception(self):
        for rec in self:
            active_claim = rec._has_active_claim() if rec.patient_id else False
            rec.has_active_claim = active_claim
            rec.is_excepted = bool(active_claim or rec.legal_hold)
            reasons = []
            if active_claim:
                reasons.append(_("klaim masih berjalan"))
            if rec.legal_hold:
                reasons.append(_("perkara hukum"))
            rec.exception_reason = ", ".join(reasons) or False

    def unlink(self):
        if any(rec.state == "reviewed" for rec in self):
            raise UserError(_(
                "Tinjauan retensi yang sudah diputuskan tidak dapat dihapus."
            ))
        return super().unlink()

    def action_review(self):
        for rec in self:
            if rec.state == "reviewed":
                raise UserError(_("Tinjauan ini sudah diputuskan."))
            if not rec.disposition:
                raise UserError(_("Keputusan tinjauan wajib dipilih."))
            if rec.disposition == "destruction_proposed":
                # Pengecualian dihitung ulang tepat sebelum keputusan, bukan
                # dipercaya dari nilai tersimpan: klaim bisa dibuka kembali
                # setelah daftar tinjauan dicetak.
                rec._compute_exception()
                if rec.is_excepted:
                    raise UserError(_(
                        "Rekam medis %(p)s tidak dapat diusulkan dimusnahkan: "
                        "%(r)s (PMK 24/2022 Ps. 39 ayat (2))."
                    ) % {"p": rec.patient_id.display_name, "r": rec.exception_reason})
            rec.write({
                "state": "reviewed",
                "reviewed_by_id": self.env.uid,
                "reviewed_at": fields.Datetime.now(),
            })
        return True

    @api.model
    def generate_reviews(self, rule=None):
        """Susun daftar tinjauan untuk rekam yang mendekati batas retensi.

        Idempoten: pasien yang sudah punya tinjauan pada aturan yang sama
        dilewati, sehingga cron harian tidak melahirkan duplikat.
        """
        Rule = self.env["hms.retention.rule"]
        rules = rule or Rule.search([])
        settings = self.env["hms.settings"].get_settings()
        lead_days = settings.retention_review_lead_days or 180
        today = fields.Date.context_today(self)
        created = self.browse()
        for one in rules:
            horizon = today + relativedelta(days=lead_days)
            cutoff = horizon - relativedelta(years=one.retention_years)
            patients = self.env["hms.patient"].sudo().search([
                ("last_visit_date", "!=", False),
                ("last_visit_date", "<=", cutoff),
            ])
            existing = set(self.sudo().search([
                ("rule_id", "=", one.id), ("patient_id", "in", patients.ids),
            ]).mapped("patient_id").ids)
            vals_list = [{
                "rule_id": one.id,
                "patient_id": p.id,
                "last_visit_date": p.last_visit_date,
                "due_date": p.last_visit_date + relativedelta(years=one.retention_years),
            } for p in patients if p.id not in existing]
            if vals_list:
                created |= self.create(vals_list)
        return created

    @api.model
    def _cron_generate_reviews(self):
        return len(self.generate_reviews())
