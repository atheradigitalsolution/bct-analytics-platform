# -*- coding: utf-8 -*-
"""Klaim penjamin — satu episode pelayanan, dari koding sampai dibayar.

=============================================================================
KEPUTUSAN: SETIAP TRANSISI ADALAH GERBANG YANG BISA MENOLAK
=============================================================================

Sebuah "state machine" yang tiap tombolnya hanya menulis kolom ``state``
bukan state machine; ia daftar pilihan dengan nama yang keren. Nilainya ada
pada apa yang **ditolak**. Di modul ini:

* ``action_start_coding`` menolak kunjungan yang masih punya temuan KLPCM
  terbuka (``custom_hms_medrec``), dan menolak klaim yang tenggatnya sudah
  lewat. Inilah gerbang yang memberi makna pada seluruh pekerjaan PMIK.
* ``action_code_done`` menolak klaim tanpa diagnosis utama, klaim yang masih
  punya pertanyaan koder belum terjawab, dan readmisi tanpa alasan.
* ``action_verify_internal`` menolak verifikasi oleh koder yang sama ketika
  selisih tarif melewati ``hms.settings.claim_variance_threshold``.
* ``action_submit`` menolak klaim yang melewati ``deadline_at`` —
  Perpres 82/2018 Ps. 77, enam bulan sejak pelayanan selesai — dan sekaligus
  memindahkannya ke ``expired`` supaya tidak dicoba lagi besok.
* ``action_mark_paid`` menolak pembayaran yang tidak sama dengan nilai
  disetujui kecuali selisihnya sudah dibukukan sebagai
  ``hms.claim.adjustment`` yang diotorisasi.

=============================================================================
KEPUTUSAN: `deadline_at` DIBEKUKAN PER KLAIM, BUKAN DIHITUNG ULANG
=============================================================================

``expiry_months_applied`` menyimpan nilai parameter saat klaim dibuat, dan
``deadline_at`` dihitung darinya. Perubahan kebijakan menggeser tenggat klaim
yang **belum diajukan** saja — mekanismenya ada di
``custom_hms_casemix/models/hms_settings.py`` dan alasannya ditulis di sana.

=============================================================================
KEPUTUSAN: GROUPING TIDAK ADA DI SINI
=============================================================================

``grouped_tariff`` adalah kolom yang diisi manusia dari aplikasi E-Klaim,
bukan hasil panggilan otomatis. Modul ini tidak memanggil E-Klaim sama sekali
(lihat ``models/hms_eklaim.py``). ``variance_amount`` karena itu bermakna
hanya setelah seseorang memasukkan hasil grouping — dan selama belum,
``is_high_variance`` bernilai False karena selisihnya memang belum diketahui,
bukan karena kecil.
"""
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

CLAIM_STATES = [
    ("to_code", "Menunggu Koding"),
    ("coding", "Sedang Dikoding"),
    ("internal_review", "Review Internal"),
    ("internal_verified", "Terverifikasi Internal"),
    ("finalized", "Final"),
    ("submitted", "Diajukan"),
    ("bpjs_verifying", "Verifikasi Penjamin"),
    ("approved", "Layak / Disetujui"),
    ("pending", "Pending (Dikembalikan)"),
    ("resubmitted", "Diajukan Ulang"),
    ("dispute", "Dispute"),
    ("rejected", "Tidak Layak"),
    ("paid", "Dibayar"),
    ("expired", "Kedaluwarsa"),
]

# State sebelum berkas keluar dari rumah sakit. Hanya di sinilah tenggat
# masih boleh bergeser saat kebijakan dikoreksi.
PRE_SUBMISSION_STATES = (
    "to_code", "coding", "internal_review", "internal_verified", "finalized",
)


class HmsClaim(models.Model):
    _name = "hms.claim"
    _description = "Klaim Penjamin"
    _order = "deadline_at, id"
    _rec_names_search = ["name", "encounter_id.name", "sep_id.name"]

    name = fields.Char("Nomor Klaim", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    payer_id = fields.Many2one("hms.payer", "Penjamin", required=True, index=True)
    cob_payer_id = fields.Many2one(
        "hms.payer", "Penjamin Kedua (COB)",
        help="Coordination of Benefit: penjamin yang menanggung selisih di atas "
             "hak kelas atau di luar tanggungan penjamin utama.",
    )
    sep_id = fields.Many2one("hms.sep", "SEP", ondelete="restrict", index=True,
                             domain="[('encounter_id', '=', encounter_id)]")
    kind = fields.Selection(
        [("bpjs_inacbg", "BPJS — INA-CBG"),
         ("bpjs_non_inacbg", "BPJS — Non INA-CBG"),
         ("insurance", "Asuransi Swasta"),
         ("company", "Perusahaan / Penjamin Kerja Sama")],
        string="Jenis Klaim", required=True, default="bpjs_inacbg", index=True,
        help="Permenkes 3/2023 Ps. 36 ayat (2): pelayanan Non INA-CBG diajukan "
             "terpisah dari klaim INA-CBG, dengan berkas dan batch sendiri.",
    )
    # `precompute=True` bukan optimasi: tanpa itu Odoo menghitung kolom
    # computed SETELAH INSERT, dan kolom NOT NULL menolak barisnya lebih dulu.
    # Gejalanya IntegrityError saat membuat klaim pertama, bukan saat memuat
    # modul — jadi ia lolos instalasi dan gagal di tangan pengguna.
    care_type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("inpatient", "Rawat Inap")],
        string="Jenis Rawat", required=True, compute="_compute_care_type",
        store=True, precompute=True,
        help="Diturunkan dari jenis kunjungan; dipakai memisahkan batch RJ dan RI. "
             "BUKAN nilai `jenis_rawat` E-Klaim — enumerasi itu belum terverifikasi.",
    )

    state = fields.Selection(CLAIM_STATES, default="to_code", required=True, index=True,
                             tracking=False)

    coder_id = fields.Many2one("res.users", "Koder", readonly=True, copy=False, index=True)
    coded_at = fields.Datetime("Selesai Dikoding", readonly=True, copy=False)
    verifier_id = fields.Many2one("res.users", "Verifikator Internal",
                                  readonly=True, copy=False)
    verified_at = fields.Datetime("Waktu Verifikasi Internal", readonly=True, copy=False)
    review_note = fields.Text("Catatan Review Internal")
    finalized_at = fields.Datetime("Waktu Finalisasi", readonly=True, copy=False)
    finalized_by_id = fields.Many2one("res.users", "Difinalkan Oleh", readonly=True, copy=False)

    discharge_at = fields.Datetime(
        "Pelayanan Selesai", compute="_compute_discharge_at", store=True,
        precompute=True, index=True,
        help="Titik awal perhitungan kedaluwarsa klaim.",
    )
    expiry_months_applied = fields.Integer(
        "Kedaluwarsa Terpakai (bulan)", readonly=True,
        help="Nilai hms.settings.claim_expiry_months yang berlaku untuk klaim "
             "ini. Ikut berubah bila kebijakan dikoreksi selagi klaim belum "
             "diajukan; beku setelah diajukan.",
    )
    deadline_at = fields.Datetime(
        "Batas Pengajuan", compute="_compute_deadline_at", store=True,
        precompute=True, index=True,
        help="Perpres 82/2018 Ps. 77: klaim diajukan paling lambat 6 bulan "
             "sejak pelayanan selesai.",
    )
    days_to_deadline = fields.Integer("Sisa Hari", compute="_compute_days_to_deadline")
    is_expired = fields.Boolean("Sudah Lewat Batas", compute="_compute_days_to_deadline")

    submission_count = fields.Integer("Jumlah Pengajuan", readonly=True, default=0, copy=False)
    submitted_at = fields.Datetime("Waktu Pengajuan Terakhir", readonly=True, copy=False)
    batch_id = fields.Many2one("hms.claim.batch", "Batch Pengajuan", ondelete="restrict",
                               index=True, copy=False)

    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True,
    )
    bill_id = fields.Many2one("hms.bill", "Tagihan Rumah Sakit", readonly=True)
    hospital_bill_amount = fields.Monetary(
        "Tarif Rumah Sakit", help="Total tagihan rumah sakit untuk episode ini.",
    )
    grouped_tariff = fields.Monetary(
        "Tarif Grouper",
        help="Hasil grouping INA-CBG. DIISI MANUSIA dari aplikasi E-Klaim — "
             "sistem ini belum memanggil E-Klaim sama sekali.",
    )
    topup_amount = fields.Monetary("Top-up / Special CMG")
    approved_amount = fields.Monetary("Nilai Disetujui Penjamin", readonly=True, copy=False)
    paid_amount = fields.Monetary("Nilai Dibayar", readonly=True, copy=False)
    variance_amount = fields.Monetary(
        "Selisih Tarif", compute="_compute_variance", store=True,
        help="Tarif rumah sakit dikurangi tarif grouper (termasuk top-up). "
             "Positif berarti rumah sakit menagih lebih besar daripada yang "
             "dibayar paket.",
    )
    is_high_variance = fields.Boolean(
        "Selisih Melewati Ambang", compute="_compute_variance", store=True,
        help="Selisih melewati hms.settings.claim_variance_threshold. Klaim "
             "seperti ini tidak boleh diverifikasi oleh kodernya sendiri.",
    )

    pending_reason = fields.Text("Alasan Pending")
    pending_category = fields.Selection(
        [("coding", "Koding"), ("document", "Kelengkapan Berkas"),
         ("signature", "Tanda Tangan / Autentikasi"), ("support", "Hasil Penunjang"),
         ("administrative", "Administratif (jam MRS/KRS, data pasien)"),
         ("medical_necessity", "Kesesuaian Medis"), ("other", "Lainnya")],
        string="Kategori Pending",
    )
    pending_at = fields.Datetime("Waktu Dikembalikan", readonly=True, copy=False)
    pending_age_days = fields.Integer("Umur Pending (hari)", compute="_compute_pending_age")
    needs_escalation = fields.Boolean("Perlu Eskalasi", compute="_compute_pending_age")
    correction_note = fields.Text("Catatan Perbaikan Sebelum Diajukan Ulang")
    rejection_reason = fields.Text("Alasan Tidak Layak")
    dispute_level = fields.Selection(
        [("branch", "Kantor Cabang"), ("regional", "Kedeputian Wilayah"),
         ("central", "Pusat")],
        string="Tingkat Dispute",
    )
    dispute_opened_at = fields.Datetime("Dispute Dibuka", readonly=True, copy=False)

    is_readmission = fields.Boolean(
        "Readmisi", readonly=True, copy=False,
        help="Rawat inap ulang dengan diagnosis utama sama dalam rentang "
             "hms.settings.readmission_window_days.",
    )
    readmission_reason = fields.Text("Alasan Readmisi")
    readmission_source_id = fields.Many2one("hms.encounter", "Kunjungan Sebelumnya",
                                            readonly=True, copy=False)
    is_fragmentation = fields.Boolean(
        "Terindikasi Fragmentasi", readonly=True, copy=False,
        help="Kunjungan rawat jalan berulang di unit yang sama dalam rentang "
             "hms.settings.fragmentation_window_days.",
    )
    fragmentation_note = fields.Text("Penjelasan Fragmentasi")

    code_ids = fields.One2many("hms.claim.code", "claim_id", "Kode Klaim")
    query_ids = fields.One2many("hms.coding.query", "claim_id", "Pertanyaan Koder")
    adjustment_ids = fields.One2many("hms.claim.adjustment", "claim_id", "Penyesuaian")
    open_query_count = fields.Integer("Pertanyaan Terbuka", compute="_compute_open_queries")
    klpcm_open_count = fields.Integer(related="encounter_id.klpcm_open_count",
                                      string="KLPCM Terbuka")
    adjustment_total = fields.Monetary("Total Penyesuaian", compute="_compute_adjustment_total")

    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor klaim harus unik.")
    # Satu episode pelayanan hanya boleh punya satu klaim per jenis: klaim
    # INA-CBG dan Non INA-CBG memang diajukan terpisah (Permenkes 3/2023
    # Ps. 36 ayat (2)), tetapi dua klaim INA-CBG untuk kunjungan yang sama
    # adalah repeat billing (Permenkes 16/2019).
    _encounter_kind_uniq = models.Constraint(
        "unique(encounter_id, kind)",
        "Kunjungan ini sudah punya klaim dengan jenis yang sama.",
    )
    _open_claim_idx = models.Index(
        "(state, deadline_at) WHERE state NOT IN ('paid', 'rejected', 'expired')"
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends("encounter_id.type")
    def _compute_care_type(self):
        for claim in self:
            claim.care_type = (
                "inpatient" if claim.encounter_id.type == "inpatient" else "outpatient"
            )

    @api.depends("encounter_id.closed_at", "encounter_id.arrival_at")
    def _compute_discharge_at(self):
        for claim in self:
            claim.discharge_at = (
                claim.encounter_id.closed_at or claim.encounter_id.arrival_at
            )

    @api.depends("discharge_at", "expiry_months_applied")
    def _compute_deadline_at(self):
        for claim in self:
            months = claim.expiry_months_applied or 0
            if claim.discharge_at and months > 0:
                claim.deadline_at = claim.discharge_at + relativedelta(months=months)
            else:
                claim.deadline_at = False

    @api.depends("deadline_at")
    def _compute_days_to_deadline(self):
        now = fields.Datetime.now()
        for claim in self:
            if claim.deadline_at:
                claim.days_to_deadline = (claim.deadline_at - now).days
                claim.is_expired = claim.deadline_at < now
            else:
                claim.days_to_deadline = 0
                claim.is_expired = False

    @api.depends("hospital_bill_amount", "grouped_tariff", "topup_amount")
    def _compute_variance(self):
        threshold = self._variance_threshold()
        for claim in self:
            if not claim.grouped_tariff:
                # Selisih terhadap tarif grouper yang belum ada bukan "nol",
                # ia belum diketahui. Menandainya high-variance akan mengirim
                # setiap klaim baru ke review internal.
                claim.variance_amount = 0.0
                claim.is_high_variance = False
                continue
            claim.variance_amount = claim.hospital_bill_amount - (
                claim.grouped_tariff + claim.topup_amount
            )
            claim.is_high_variance = abs(claim.variance_amount) >= threshold

    @api.depends("query_ids.state")
    def _compute_open_queries(self):
        for claim in self:
            claim.open_query_count = len(
                claim.query_ids.filtered(lambda q: q.state == "open")
            )

    @api.depends("adjustment_ids.amount", "adjustment_ids.state")
    def _compute_adjustment_total(self):
        for claim in self:
            claim.adjustment_total = sum(
                claim.adjustment_ids.filtered(lambda a: a.state == "authorized")
                .mapped("amount")
            )

    @api.depends("state", "pending_at")
    def _compute_pending_age(self):
        limit = self.env["hms.settings"].get_settings().claim_pending_escalation_days or 60
        now = fields.Datetime.now()
        for claim in self:
            if claim.state == "pending" and claim.pending_at:
                claim.pending_age_days = (now - claim.pending_at).days
            else:
                claim.pending_age_days = 0
            claim.needs_escalation = claim.pending_age_days > limit

    @api.depends("name", "encounter_id")
    def _compute_display_name(self):
        for claim in self:
            claim.display_name = (
                f"{claim.name} — {claim.encounter_id.name}"
                if claim.encounter_id else claim.name
            )

    # ------------------------------------------------------------------
    # Parameter kebijakan
    # ------------------------------------------------------------------
    @api.model
    def _settings(self):
        return self.env["hms.settings"].get_settings()

    @api.model
    def _variance_threshold(self):
        value = self._settings().claim_variance_threshold
        return value if value and value > 0 else 0.0

    @api.model
    def _expiry_months(self):
        months = self._settings().claim_expiry_months
        # Nol/negatif berarti parameter belum diisi; jatuh ke norma
        # Perpres 82/2018 Ps. 77 daripada menerbitkan klaim tanpa tenggat.
        return months if months and months > 0 else 6

    @api.model
    def _sync_expiry_months(self, settings):
        """Geser tenggat klaim yang belum diajukan setelah kebijakan dikoreksi.

        Dipanggil dari ``hms.settings.write``. ``sudo()`` di sini adalah
        pembukuan, bukan keputusan: yang memutuskan adalah orang yang berhak
        mengubah pengaturan rumah sakit, dan konsekuensinya menyentuh baris
        klaim yang ia sendiri belum tentu boleh sunting satu per satu.
        """
        for setting in settings:
            months = setting.claim_expiry_months
            if not months or months <= 0:
                continue
            claims = self.sudo().search([
                ("company_id", "=", setting.company_id.id),
                ("state", "in", PRE_SUBMISSION_STATES),
            ])
            if claims:
                claims.write({"expiry_months_applied": months})
                _logger.info(
                    "SIMRS: %s klaim pra-pengajuan mengikuti kedaluwarsa baru %s bulan",
                    len(claims), months,
                )
        return True

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        months = self._expiry_months()
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code("hms.claim") or "/"
            vals.setdefault("expiry_months_applied", months)
        claims = super().create(vals_list)
        for claim in claims:
            claim._pull_hospital_bill()
        return claims

    def unlink(self):
        if any(claim.state != "to_code" for claim in self):
            raise UserError(_(
                "Klaim yang sudah mulai dikoding tidak dapat dihapus — ia "
                "menjadi bukti apa yang pernah diajukan ke penjamin."
            ))
        return super().unlink()

    @api.model
    def create_for_encounter(self, encounter, kind="bpjs_inacbg"):
        """Buat klaim untuk satu kunjungan, kalau belum ada.

        Sengaja BUKAN otomatis lewat cron. Membuat klaim adalah pernyataan
        bahwa episode ini memang akan ditagihkan ke penjamin — keputusan
        petugas casemix, bukan efek samping pasien pulang. Klaim yang lahir
        sendiri untuk setiap kunjungan menghasilkan daftar kerja yang isinya
        sebagian besar bukan pekerjaan.
        """
        existing = self.search([
            ("encounter_id", "=", encounter.id), ("kind", "=", kind),
        ], limit=1)
        if existing:
            return existing
        if encounter.state not in ("finished", "discharged"):
            raise UserError(_(
                "Kunjungan %s belum selesai dilayani, klaimnya belum bisa dibuka."
            ) % encounter.name)
        sep = self.env["hms.sep"].search(
            [("encounter_id", "=", encounter.id)], limit=1
        )
        return self.create({
            "encounter_id": encounter.id,
            "payer_id": encounter.payer_id.id,
            "sep_id": sep.id if sep else False,
            "kind": kind,
        })

    def _pull_hospital_bill(self):
        """Ambil total tagihan rumah sakit dari ``hms.bill``.

        Disalin, bukan dibaca lewat related: tarif rumah sakit yang dilaporkan
        ke penjamin adalah angka pada saat klaim disusun. Tagihan yang
        kemudian dibuka ulang dan dikoreksi tidak boleh diam-diam mengubah
        angka yang sudah dikirim.
        """
        for claim in self:
            bill = self.env["hms.bill"].search(
                [("encounter_id", "=", claim.encounter_id.id)], limit=1
            )
            if bill:
                claim.write({
                    "bill_id": bill.id,
                    "hospital_bill_amount": bill.amount_total,
                })
        return True

    def action_refresh_hospital_bill(self):
        return self._pull_hospital_bill()

    # ------------------------------------------------------------------
    # Penjaga bersama
    # ------------------------------------------------------------------
    def _ensure_state(self, allowed, what):
        self.ensure_one()
        if self.state not in allowed:
            raise UserError(_(
                "Klaim %(n)s berstatus '%(s)s'; %(w)s hanya dapat dilakukan dari "
                "status %(a)s."
            ) % {
                "n": self.name,
                "s": dict(CLAIM_STATES).get(self.state),
                "w": what,
                "a": ", ".join(dict(CLAIM_STATES)[s] for s in allowed),
            })

    def _check_not_expired(self, what):
        """Menolak, dan HANYA menolak.

        Godaannya besar untuk sekalian menulis ``state = 'expired'`` di sini
        supaya klaimnya tidak dicoba lagi besok. Itu tidak akan pernah
        bekerja: begitu ``UserError`` naik, Odoo membatalkan transaksinya dan
        penulisan tadi ikut hilang — pola "catat lalu tolak" yang sudah
        memakan waktu di ``custom_hms_billing.apply_discount`` dan yang paling
        berbahaya justru karena tampak berhasil di layar.

        Penandaannya karena itu ditempatkan di tempat yang memang selesai
        tanpa exception: ``_cron_expire_claims`` harian, dan ``action_expire``
        untuk petugas yang mau menutupnya sekarang.
        """
        self.ensure_one()
        if self.deadline_at and self.deadline_at < fields.Datetime.now():
            raise UserError(_(
                "Klaim %(n)s sudah melewati batas pengajuan %(d)s "
                "(Perpres 82/2018 Ps. 77: 6 bulan sejak pelayanan selesai). "
                "%(w)s tidak dapat dilanjutkan; kerugiannya dibukukan sebagai "
                "penyesuaian klaim kedaluwarsa."
            ) % {"n": self.name,
                 "d": fields.Datetime.to_string(self.deadline_at),
                 "w": what})

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def action_start_coding(self):
        """Menunggu Koding -> Sedang Dikoding. Gerbang KLPCM ada di sini."""
        for claim in self:
            claim._ensure_state(("to_code",), _("mulai koding"))
            claim._check_not_expired(_("Koding"))
            if claim.encounter_id.state not in ("finished", "discharged"):
                raise UserError(_(
                    "Kunjungan %s belum selesai dilayani."
                ) % claim.encounter_id.name)
            open_klpcm = self.env["hms.klpcm"].search([
                ("encounter_id", "=", claim.encounter_id.id),
                ("state", "=", "open"),
            ])
            if open_klpcm:
                raise UserError(_(
                    "Berkas kunjungan %(n)s belum lengkap — %(c)s temuan KLPCM "
                    "masih terbuka:\n- %(l)s\n\n"
                    "Koding klaim dari berkas tidak lengkap menghasilkan klaim "
                    "yang dikembalikan penjamin berbulan-bulan kemudian. "
                    "Lengkapi dokumennya lebih dulu."
                ) % {
                    "n": claim.encounter_id.name,
                    "c": len(open_klpcm),
                    "l": "\n- ".join(
                        f"{dict(k._fields['component'].selection)[k.component]}"
                        f"{' (' + k.detail + ')' if k.detail else ''}"
                        for k in open_klpcm
                    ),
                })
            claim.write({"state": "coding", "coder_id": self.env.uid})
            # Aturan pre-grouping dijalankan DI SINI, bukan hanya saat koding
            # selesai. Alasannya sama dengan di atas: bila satu-satunya tempat
            # ia dijalankan adalah `action_code_done`, maka pada kasus yang
            # justru paling penting — readmisi tanpa alasan, yang ditolak —
            # penandaannya ikut hilang bersama rollback, dan koder melihat
            # penolakan tanpa melihat mengapa.
            claim._run_pregrouping_rules()
            claim.env["hms.event"].emit("claim.coding_started", {
                "claim": claim.name, "encounter_id": claim.encounter_id.id,
            })
        return True

    def action_code_done(self):
        """Sedang Dikoding -> Review Internal. Aturan pre-grouping jalan di sini."""
        for claim in self:
            claim._ensure_state(("coding",), _("menyelesaikan koding"))
            claim._check_not_expired(_("Koding"))
            principal = claim.code_ids.filtered(
                lambda c: c.kind == "icd10" and c.role == "principal"
            )
            if not principal:
                raise UserError(_(
                    "Klaim %s belum punya diagnosis utama (ICD-10, peran "
                    "'Diagnosis Utama'). Grouper tidak dapat bekerja tanpanya."
                ) % claim.name)
            if claim.open_query_count:
                raise UserError(_(
                    "Masih ada %(c)s pertanyaan koder yang belum dijawab DPJP "
                    "pada klaim %(n)s. Koding yang diselesaikan sambil menunggu "
                    "jawaban adalah koding yang akan diulang."
                ) % {"c": claim.open_query_count, "n": claim.name})
            claim._run_pregrouping_rules()
            if claim.is_readmission and not claim.readmission_reason:
                raise UserError(_(
                    "Kunjungan ini terdeteksi readmisi dari %(p)s dengan "
                    "diagnosis utama yang sama dalam %(d)s hari. Alasan "
                    "readmisi wajib diisi sebelum koding diselesaikan — "
                    "readmisi tanpa penjelasan adalah temuan audit klaim."
                ) % {
                    "p": claim.readmission_source_id.name or "-",
                    "d": self._settings().readmission_window_days,
                })
            claim.write({
                "state": "internal_review",
                "coded_at": fields.Datetime.now(),
            })
            claim.env["hms.event"].emit("claim.coded", {
                "claim": claim.name,
                "principal": principal[:1].code_display,
                "is_readmission": claim.is_readmission,
                "is_fragmentation": claim.is_fragmentation,
            })
        return True

    def action_verify_internal(self):
        """Review Internal -> Terverifikasi Internal.

        Empat mata wajib untuk klaim berselisih besar: koder yang sama tidak
        boleh memverifikasi pekerjaannya sendiri ketika selisih tarif rumah
        sakit terhadap tarif grouper melewati ambang RS. Di bawah ambang,
        verifikasi sendiri diterima — memaksa dua orang pada setiap klaim
        rawat jalan hanya menghasilkan verifikasi yang dicap tanpa dibaca.
        """
        for claim in self:
            claim._ensure_state(("internal_review",), _("verifikasi internal"))
            if claim.is_high_variance:
                if self.env.uid == claim.coder_id.id:
                    raise UserError(_(
                        "Selisih tarif klaim %(n)s sebesar %(v)s melewati ambang "
                        "review internal. Klaim seperti ini harus diverifikasi "
                        "orang lain, bukan oleh kodernya sendiri."
                    ) % {"n": claim.name,
                         "v": claim.variance_amount})
                if not claim.review_note:
                    raise UserError(_(
                        "Catatan review internal wajib diisi untuk klaim dengan "
                        "selisih tarif di atas ambang."
                    ))
            claim.write({
                "state": "internal_verified",
                "verifier_id": self.env.uid,
                "verified_at": fields.Datetime.now(),
            })
        return True

    def action_return_to_coding(self):
        """Review Internal -> Sedang Dikoding, dengan catatan apa yang salah."""
        for claim in self:
            claim._ensure_state(("internal_review",), _("mengembalikan ke koder"))
            if not claim.review_note:
                raise UserError(_(
                    "Tulis apa yang harus diperbaiki sebelum mengembalikan klaim "
                    "ke koder."
                ))
            claim.write({"state": "coding"})
        return True

    def action_finalize(self):
        """Terverifikasi -> Final. Di sinilah kunjungannya ikut terkunci.

        Finalisasi adalah pernyataan "inilah berkas yang kami ajukan". Sejak
        titik itu dokumentasi klinis yang menjadi isinya tidak boleh berubah
        diam-diam lagi; penguncian dan satu-satunya pintu keluarnya ada di
        ``models/hms_encounter_lock.py``.
        """
        for claim in self:
            claim._ensure_state(("internal_verified",), _("finalisasi"))
            claim._check_not_expired(_("Finalisasi"))
            claim.write({
                "state": "finalized",
                "finalized_at": fields.Datetime.now(),
                "finalized_by_id": self.env.uid,
            })
            claim.encounter_id._casemix_lock(claim)
            claim.env["hms.event"].emit("claim.finalized", {"claim": claim.name})
        return True

    def action_issue_adjustment(self, values=None):
        """Terbitkan satu ``hms.claim.adjustment`` untuk klaim ini.

        Diletakkan di sini, bukan di controller, karena syaratnya adalah
        aturan bisnis: penyesuaian hanya masuk akal untuk klaim yang sudah
        keluar dari rumah sakit. Menerbitkan "selisih verifikasi" atas klaim
        yang masih di meja koder berarti membukukan kerugian atas angka yang
        belum pernah diajukan ke siapa pun.
        """
        self.ensure_one()
        values = dict(values or {})
        if self.state in PRE_SUBMISSION_STATES:
            raise UserError(_(
                "Klaim %(n)s masih berstatus '%(s)s' — belum pernah diajukan "
                "ke penjamin, jadi belum ada selisih yang bisa dibukukan. "
                "Perbaiki angkanya langsung selama klaim masih di rumah sakit."
            ) % {"n": self.name, "s": dict(CLAIM_STATES).get(self.state)})
        values.update({"claim_id": self.id})
        return self.env["hms.claim.adjustment"].create(values)

    def action_submit(self):
        """Final -> Diajukan. Tenggat enam bulan benar-benar menolak di sini."""
        for claim in self:
            claim._ensure_state(("finalized",), _("pengajuan"))
            claim._check_not_expired(_("Pengajuan"))
            if not claim.batch_id:
                raise UserError(_(
                    "Klaim %s belum masuk batch pengajuan. Penjamin menerima "
                    "berkas per batch, bukan satuan."
                ) % claim.name)
            claim.write({
                "state": "submitted",
                "submitted_at": fields.Datetime.now(),
                "submission_count": claim.submission_count + 1,
            })
            claim.env["hms.event"].emit("claim.submitted", {
                "claim": claim.name, "attempt": claim.submission_count,
            })
        return True

    def action_start_verification(self):
        for claim in self:
            claim._ensure_state(("submitted", "resubmitted"), _("verifikasi penjamin"))
            claim.write({"state": "bpjs_verifying"})
        return True

    def action_approve(self, amount=None):
        for claim in self:
            claim._ensure_state(("bpjs_verifying", "dispute"), _("penetapan layak"))
            approved = amount if amount is not None else claim.approved_amount
            if not approved:
                raise UserError(_(
                    "Nilai yang disetujui penjamin wajib diisi sebelum klaim "
                    "%s ditetapkan layak."
                ) % claim.name)
            claim.write({"state": "approved", "approved_amount": approved})
            claim.env["hms.event"].emit("claim.approved", {
                "claim": claim.name, "amount": approved,
            })
        return True

    def action_set_pending(self):
        for claim in self:
            claim._ensure_state(("bpjs_verifying",), _("penetapan pending"))
            if not claim.pending_reason or not claim.pending_category:
                raise UserError(_(
                    "Alasan dan kategori pending wajib diisi. Klaim pending "
                    "tanpa alasan tidak bisa diperbaiki, hanya bisa diajukan "
                    "ulang dengan kesalahan yang sama."
                ))
            claim.write({"state": "pending", "pending_at": fields.Datetime.now()})
            claim.env["hms.event"].emit("claim.pending", {
                "claim": claim.name, "category": claim.pending_category,
            })
        return True

    def action_resubmit(self):
        """Pending -> Diajukan Ulang. Masih harus muat di dalam enam bulan."""
        for claim in self:
            claim._ensure_state(("pending",), _("pengajuan ulang"))
            claim._check_not_expired(_("Pengajuan ulang"))
            if not claim.correction_note:
                raise UserError(_(
                    "Tulis perbaikan apa yang dilakukan sebelum klaim %s "
                    "diajukan ulang."
                ) % claim.name)
            claim.write({
                "state": "resubmitted",
                "submitted_at": fields.Datetime.now(),
                "submission_count": claim.submission_count + 1,
            })
            claim.env["hms.event"].emit("claim.resubmitted", {
                "claim": claim.name, "attempt": claim.submission_count,
            })
        return True

    def action_open_dispute(self):
        for claim in self:
            claim._ensure_state(("bpjs_verifying", "pending", "rejected"), _("dispute"))
            if not claim.dispute_level:
                raise UserError(_("Tingkat dispute wajib dipilih."))
            claim.write({"state": "dispute", "dispute_opened_at": fields.Datetime.now()})
        return True

    def action_reject(self):
        for claim in self:
            claim._ensure_state(("bpjs_verifying", "dispute"), _("penetapan tidak layak"))
            if not claim.rejection_reason:
                raise UserError(_("Alasan tidak layak wajib diisi."))
            claim.write({"state": "rejected"})
            claim.env["hms.event"].emit("claim.rejected", {"claim": claim.name})
        return True

    def action_mark_paid(self, amount=None):
        """Disetujui -> Dibayar. Selisih pembayaran harus punya bukunya."""
        for claim in self:
            claim._ensure_state(("approved",), _("pencatatan pembayaran"))
            paid = amount if amount is not None else claim.paid_amount
            if not paid:
                raise UserError(_("Nilai pembayaran wajib diisi."))
            gap = claim.approved_amount - paid - claim.adjustment_total
            if abs(gap) > 0.01:
                raise UserError(_(
                    "Nilai dibayar %(p)s tidak sama dengan nilai disetujui "
                    "%(a)s, dan selisih %(g)s belum dibukukan. Catat selisihnya "
                    "sebagai penyesuaian klaim yang diotorisasi lebih dulu — "
                    "klaim yang dibayar tidak boleh diubah lagi selain lewat "
                    "penyesuaian."
                ) % {"p": paid, "a": claim.approved_amount, "g": gap})
            claim.write({"state": "paid", "paid_amount": paid})
            claim.env["hms.event"].emit("claim.paid", {
                "claim": claim.name, "amount": paid,
            })
        return True

    def action_expire(self):
        for claim in self:
            if claim.state in ("paid", "rejected", "expired"):
                continue
            if not claim.deadline_at or claim.deadline_at >= fields.Datetime.now():
                raise UserError(_(
                    "Klaim %s belum melewati batas pengajuan."
                ) % claim.name)
            claim.write({"state": "expired"})
            claim.env["hms.event"].emit("claim.expired", {"claim": claim.name})
        return True

    @api.model
    def _cron_expire_claims(self):
        stale = self.sudo().search([
            ("state", "in", PRE_SUBMISSION_STATES + ("pending",)),
            ("deadline_at", "!=", False),
            ("deadline_at", "<", fields.Datetime.now()),
        ])
        if stale:
            stale.write({"state": "expired"})
            _logger.info("SIMRS: %s klaim ditandai kedaluwarsa", len(stale))
        return len(stale)

    # ------------------------------------------------------------------
    # Aturan pre-grouping yang bisa dihitung tanpa E-Klaim
    # ------------------------------------------------------------------
    def _principal_icd10(self):
        """Diagnosis utama menurut koder, kalau belum ada menurut dokter."""
        self.ensure_one()
        coded = self.code_ids.filtered(
            lambda c: c.kind == "icd10" and c.role == "principal"
        )
        if coded:
            return coded[0].icd10_id
        clinical = self.env["hms.diagnosis"].search([
            ("encounter_id", "=", self.encounter_id.id),
            ("rank", "=", "primary"),
        ], order="stage desc, id desc", limit=1)
        return clinical.icd10_id

    def _detect_readmission(self):
        """Rawat inap ulang dengan diagnosis utama sama dalam jendela kebijakan.

        Pembandingnya adalah ``hms.diagnosis`` kunjungan sebelumnya — catatan
        dokter, bukan kode klaim. Dua alasan: kunjungan lama mungkin belum
        pernah dikoding sama sekali, dan membandingkan kode klaim dengan kode
        klaim membuat readmisi bisa "hilang" hanya dengan mengoding kunjungan
        lama secara berbeda.
        """
        self.ensure_one()
        if self.care_type != "inpatient":
            return False
        window = self._settings().readmission_window_days or 30
        principal = self._principal_icd10()
        if not principal:
            return False
        arrival = self.encounter_id.arrival_at
        if not arrival:
            return False
        earliest = arrival - relativedelta(days=window)
        previous = self.env["hms.encounter"].search([
            ("id", "!=", self.encounter_id.id),
            ("patient_id", "=", self.encounter_id.patient_id.id),
            ("type", "=", "inpatient"),
            ("state", "in", ("finished", "discharged")),
            ("closed_at", ">=", earliest),
            ("closed_at", "<=", arrival),
        ], order="closed_at desc")
        for encounter in previous:
            same = self.env["hms.diagnosis"].search_count([
                ("encounter_id", "=", encounter.id),
                ("rank", "=", "primary"),
                ("icd10_id", "=", principal.id),
            ])
            if same:
                self.write({
                    "is_readmission": True,
                    "readmission_source_id": encounter.id,
                })
                return True
        # Idempoten dua arah. Deteksi yang hanya bisa menyalakan flag akan
        # membuat penandaan lama bertahan setelah jendela kebijakan dipersempit
        # atau diagnosis utama dikoreksi — dan flag readmisi yang salah
        # menuntut alasan atas sesuatu yang tidak terjadi.
        if self.is_readmission:
            self.write({"is_readmission": False, "readmission_source_id": False})
        return False

    def _detect_fragmentation(self):
        """Kunjungan rawat jalan berulang di unit yang sama dalam jendela.

        Tidak memutuskan apa pun sendiri — ia menandai, dan koder yang
        menjelaskan. Sebagian kunjungan berulang memang sah (kontrol terjadwal,
        seri kemoterapi); yang tidak sah adalah episode yang sengaja dipecah
        supaya dibayar dua kali (services unbundling, Permenkes 16/2019).
        """
        self.ensure_one()
        if self.care_type != "outpatient":
            return False
        window = self._settings().fragmentation_window_days or 7
        arrival = self.encounter_id.arrival_at
        if not arrival:
            return False
        earliest = arrival - relativedelta(days=window)
        twin = self.env["hms.encounter"].search_count([
            ("id", "!=", self.encounter_id.id),
            ("patient_id", "=", self.encounter_id.patient_id.id),
            ("unit_id", "=", self.encounter_id.unit_id.id),
            ("type", "in", ("outpatient", "daycare")),
            ("state", "in", ("finished", "discharged")),
            ("arrival_at", ">=", earliest),
            ("arrival_at", "<", arrival),
        ])
        if twin:
            self.write({"is_fragmentation": True})
            return True
        if self.is_fragmentation:
            self.write({"is_fragmentation": False})
        return False

    def _run_pregrouping_rules(self):
        for claim in self:
            claim._detect_readmission()
            claim._detect_fragmentation()
        return True

    def action_run_pregrouping(self):
        return self._run_pregrouping_rules()
