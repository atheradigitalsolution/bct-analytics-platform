# -*- coding: utf-8 -*-
"""lgx.job — tulang punggung komersial dan keuangan.

Satu model untuk forwarding, trucking dan gudang. Yang membuat itu mungkin:
lapisan komersialnya identik di ketiganya — pelanggan, rute, baris biaya, faktur,
margin — dan hanya lapisan operasionalnya yang berbeda. Operasi menggantung di
bawah job lewat One2many yang ditambahkan modul segmen, bukan lewat pewarisan.

DUA TAHAP PENUTUPAN
-------------------
Aturan polos "tidak boleh tutup selama ada estimasi tanpa aktual" akan membuat
hampir semua job menggantung, karena tagihan vendor datang dua sampai enam
minggu kemudian dan demurrage bahkan lebih lambat. Yang terjadi di lapangan
kemudian adalah staf menolkan estimasi supaya job bisa ditutup — persis
kebocoran yang aturan itu ingin cegah.

Karena itu:

* ``completed``           pekerjaan fisik selesai. Ditolak bila masih ada
                          kontainer belum kembali, uang jalan belum
                          dipertanggungjawabkan, atau stop dropoff tanpa POD.
* ``closed_provisioned``  penutupan finansial. Sisa estimasi DIBEKUKAN dan
                          diposting sebagai provisi, bukan dihapus.
* ``closed``              seluruh provisi sudah terpakai atau dilepas.

``close_blocked_reason`` menyebut penghalangnya secara spesifik. Menolak tanpa
menyebut alasan adalah cara tercepat membuat orang mencari jalan memutar.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

JOB_TYPES = [
    ("ff_import", "Forwarding — Impor"),
    ("ff_export", "Forwarding — Ekspor"),
    ("ff_domestic", "Forwarding — Domestik"),
    ("customs_only", "Kepabeanan Saja"),
    ("trucking", "Trucking"),
    ("warehouse", "Gudang 3PL"),
    ("project", "Project / Multimoda"),
]

JPT_JOB_TYPES = ("ff_import", "ff_export", "ff_domestic", "project")

TRANSPORT_MODES = [
    ("sea", "Laut"),
    ("air", "Udara"),
    ("land", "Darat"),
    ("rail", "Kereta"),
    ("multimodal", "Multimoda"),
]


class LgxJob(models.Model):
    _name = "lgx.job"
    _description = "Job Logistik"
    _inherit = ["lgx.numbering.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _lgx_sequence_code = "lgx.job"

    # --- identitas ---------------------------------------------------------
    job_type = fields.Selection(JOB_TYPES, "Jenis Job", required=True, default="ff_import",
                                tracking=True, index=True)
    transport_mode = fields.Selection(TRANSPORT_MODES, "Moda", required=True, default="sea", tracking=True)
    direction = fields.Selection(
        [("import", "Impor"), ("export", "Ekspor"), ("domestic", "Domestik"), ("cross_trade", "Cross Trade")],
        string="Arah", compute="_compute_direction", store=True, readonly=False,
    )
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    operating_unit_id = fields.Many2one(
        "operating.unit", "Cabang", index=True, tracking=True,
        domain="[('company_id','=',company_id)]",
        help="Cabang adalah dimensi operating.unit, bukan perusahaan terpisah. "
             "NITKU yang dipakai faktur pajak job ini diambil dari sini.",
    )
    description = fields.Char("Keterangan")

    # --- komersial ---------------------------------------------------------
    customer_id = fields.Many2one("res.partner", "Pelanggan", required=True, tracking=True, index=True)
    salesperson_id = fields.Many2one("res.users", "Penanggung Jawab Penjualan",
                                     default=lambda s: s.env.user, tracking=True)
    operator_id = fields.Many2one("res.users", "Penanggung Jawab Operasi", tracking=True)
    customer_reference = fields.Char("Referensi Pelanggan", index=True,
                                     help="Nomor PO atau referensi internal pelanggan. Dicari di pelacakan.")

    # --- pihak -------------------------------------------------------------
    shipper_id = fields.Many2one("res.partner", "Shipper")
    consignee_id = fields.Many2one("res.partner", "Consignee")
    notify_party_id = fields.Many2one("res.partner", "Notify Party")
    agent_id = fields.Many2one("res.partner", "Agen", domain="[('lgx_is_agent','=',True)]")
    is_nomination = fields.Boolean(
        "Job Nominasi", tracking=True,
        help="Pekerjaan yang datang dari agen luar negeri. Bagian agen dihitung "
             "sebagai baris biaya, bukan dipotong dari pendapatan.",
    )

    # --- rute dan jadwal ---------------------------------------------------
    origin_location_id = fields.Many2one("lgx.location", "Asal", index=True)
    destination_location_id = fields.Many2one("lgx.location", "Tujuan", index=True)
    incoterm_id = fields.Many2one("account.incoterms", "Incoterm")
    etd = fields.Date("ETD", tracking=True)
    eta = fields.Date("ETA", tracking=True)
    atd = fields.Date("ATD")
    ata = fields.Date("ATA")
    target_close_date = fields.Date("Target Tutup")
    closed_date = fields.Date("Tanggal Tutup", readonly=True, copy=False)

    # --- kurs --------------------------------------------------------------
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    company_currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    fx_rate_book = fields.Float(
        "Kurs Pembukuan", digits=(16, 6), default=1.0, tracking=True,
        help="Dikunci pada tanggal job. Menjaga margin dari fluktuasi kurs "
             "setelah harga disepakati.",
    )
    fx_rate_tax = fields.Float(
        "Kurs Pajak (KMK)", digits=(16, 6), default=1.0, tracking=True,
        help="Kurs Menteri Keuangan yang berlaku pada tanggal faktur pajak atau "
             "tanggal PIB. WAJIB berbeda dari kurs pembukuan: memakai satu kurs "
             "untuk keduanya membuat nilai rupiah di faktur pajak dan PIB salah, "
             "dan itu kategori kesalahan yang langsung terlihat saat pemeriksaan.",
    )
    fx_rate_date = fields.Date("Tanggal Kurs", default=fields.Date.context_today)
    fx_rate_source = fields.Char("Sumber Kurs", default="manual")

    # --- anak --------------------------------------------------------------
    charge_ids = fields.One2many("lgx.job.charge", "job_id", "Baris Charge")
    milestone_ids = fields.One2many("lgx.milestone", "job_id", "Milestone")
    milestone_progress = fields.Float("Progres Milestone (%)", compute="_compute_milestone_progress")
    next_milestone_id = fields.Many2one("lgx.milestone", "Milestone Berikutnya",
                                        compute="_compute_milestone_progress")

    # --- keuangan ----------------------------------------------------------
    # Talangan DIPISAHKAN dari jasa di setiap agregat. Menggabungkannya membuat
    # margin_pct tidak berarti pada job impor, karena bea masuk saja bisa
    # berkali lipat nilai jasanya.
    revenue_estimated = fields.Monetary("Pendapatan Jasa (Estimasi)", compute="_compute_totals", store=True)
    revenue_actual = fields.Monetary("Pendapatan Jasa (Aktual)", compute="_compute_totals", store=True)
    revenue_total = fields.Monetary("Pendapatan Jasa", compute="_compute_totals", store=True,
                                    help="Nilai berlaku: aktual bila sudah diketahui, selain itu estimasi.")
    cost_estimated = fields.Monetary("Biaya Jasa (Estimasi)", compute="_compute_totals", store=True)
    cost_actual = fields.Monetary("Biaya Jasa (Aktual)", compute="_compute_totals", store=True)
    cost_total = fields.Monetary("Biaya Jasa", compute="_compute_totals", store=True)
    disbursement_billed = fields.Monetary("Talangan Ditagihkan", compute="_compute_totals", store=True)
    disbursement_incurred = fields.Monetary("Talangan Dikeluarkan", compute="_compute_totals", store=True)
    disbursement_balance = fields.Monetary(
        "Saldo Talangan", compute="_compute_totals", store=True,
        help="Dikeluarkan dikurangi ditagihkan. Saldo positif pada job tertutup "
             "berarti ada talangan yang tidak pernah ditagihkan — kas yang hilang "
             "diam-diam.",
    )
    invoice_value = fields.Monetary("Nilai Tagihan (jasa + talangan)", compute="_compute_totals", store=True)
    margin = fields.Monetary("Margin", compute="_compute_totals", store=True, tracking=True)
    margin_pct = fields.Float("Margin (%)", compute="_compute_totals", store=True, tracking=True,
                              digits=(16, 2))
    cost_accrual_open = fields.Monetary(
        "Akrual Belum Ditagih", compute="_compute_totals", store=True,
        help="Estimasi biaya yang belum punya tagihan vendor. Porsi ini adalah "
             "ukuran seberapa dipercaya angka margin hari ini.",
    )
    variance_total = fields.Monetary("Varians Biaya", compute="_compute_totals", store=True)

    # --- status ------------------------------------------------------------
    state = fields.Selection(
        [
            ("draft", "Draf"),
            ("confirmed", "Dikonfirmasi"),
            ("in_progress", "Berjalan"),
            ("completed", "Selesai Operasi"),
            ("closed_provisioned", "Tutup dengan Provisi"),
            ("closed", "Tutup"),
            ("cancelled", "Batal"),
        ],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    close_blocked_reason = fields.Text("Penghalang Penutupan", compute="_compute_close_blocked_reason")
    cancel_reason = fields.Char("Alasan Pembatalan")

    _margin_pct_range = models.Constraint(
        "check(margin_pct >= -100000 and margin_pct <= 100000)",
        "Margin persen di luar rentang yang masuk akal — biasanya tanda pendapatan nol.",
    )
    _eta_after_etd = models.Constraint(
        "check(etd is null or eta is null or eta >= etd)",
        "ETA tidak boleh lebih awal dari ETD.",
    )
    _fx_positive = models.Constraint(
        "check(fx_rate_book > 0 and fx_rate_tax > 0)",
        "Kurs harus lebih besar dari nol.",
    )

    # --- computes ----------------------------------------------------------
    @api.depends("job_type")
    def _compute_direction(self):
        mapping = {"ff_import": "import", "ff_export": "export", "ff_domestic": "domestic"}
        for job in self:
            if job.job_type in mapping:
                job.direction = mapping[job.job_type]
            elif not job.direction:
                job.direction = "domestic"

    @api.depends(
        "charge_ids.amount_estimated", "charge_ids.amount_actual", "charge_ids.is_actual_known",
        "charge_ids.kind", "charge_ids.nature", "charge_ids.state",
    )
    def _compute_totals(self):
        for job in self:
            live = job.charge_ids.filtered(lambda c: c.state != "cancelled")
            svc_rev = live.filtered(lambda c: c.kind == "revenue" and c.nature == "service")
            svc_cost = live.filtered(lambda c: c.kind == "cost" and c.nature == "service")
            disb_rev = live.filtered(lambda c: c.kind == "revenue" and c.nature == "disbursement")
            disb_cost = live.filtered(lambda c: c.kind == "cost" and c.nature == "disbursement")

            job.revenue_estimated = sum(svc_rev.mapped("amount_estimated"))
            job.revenue_actual = sum(svc_rev.mapped("amount_actual"))
            job.revenue_total = sum(svc_rev.mapped("amount_effective"))
            job.cost_estimated = sum(svc_cost.mapped("amount_estimated"))
            job.cost_actual = sum(svc_cost.mapped("amount_actual"))
            job.cost_total = sum(svc_cost.mapped("amount_effective"))
            job.disbursement_billed = sum(disb_rev.mapped("amount_effective"))
            job.disbursement_incurred = sum(disb_cost.mapped("amount_effective"))
            job.disbursement_balance = job.disbursement_incurred - job.disbursement_billed
            job.invoice_value = job.revenue_total + job.disbursement_billed
            job.margin = job.revenue_total - job.cost_total
            job.margin_pct = (job.margin / job.revenue_total * 100.0) if job.revenue_total else 0.0
            job.cost_accrual_open = sum(
                c.amount_estimated for c in svc_cost + disb_cost if not c.is_actual_known
            )
            job.variance_total = sum(live.mapped("amount_variance"))

    @api.depends("milestone_ids.actual_date", "milestone_ids.planned_date")
    def _compute_milestone_progress(self):
        for job in self:
            all_ms = job.milestone_ids
            done = all_ms.filtered("actual_date")
            job.milestone_progress = (len(done) / len(all_ms) * 100.0) if all_ms else 0.0
            pending = all_ms.filtered(lambda m: not m.actual_date).sorted(
                key=lambda m: (m.sequence, m.planned_date or fields.Date.today())
            )
            job.next_milestone_id = pending[:1]

    @api.depends("state", "charge_ids.is_actual_known", "charge_ids.state", "milestone_ids.actual_date")
    def _compute_close_blocked_reason(self):
        for job in self:
            job.close_blocked_reason = "\n".join(job._lgx_close_blockers()) or False

    # --- titik perluasan untuk modul segmen --------------------------------
    def _lgx_completion_blockers(self):
        """Alasan job belum boleh masuk ``completed`` (penutupan OPERASIONAL).

        Modul segmen menimpa method ini dan MENAMBAH ke hasil super(), bukan
        menggantinya. custom_lgx_ff menambahkan kontainer yang belum kembali,
        custom_lgx_tms menambahkan POD yang hilang dan uang jalan yang belum
        dipertanggungjawabkan.
        """
        self.ensure_one()
        blockers = []
        mandatory = self.milestone_ids.filtered(lambda m: m.is_mandatory and not m.actual_date)
        if mandatory:
            blockers.append(_(
                "Milestone wajib belum tercapai: %s",
                ", ".join(mandatory.mapped("milestone_type_id.name")),
            ))
        return blockers

    def _lgx_close_blockers(self):
        """Alasan job belum boleh masuk ``closed`` PENUH.

        Berbeda dari ``_lgx_completion_blockers``: di sini yang diuji adalah
        kelengkapan finansial. Estimasi tanpa aktual TIDAK menghalangi
        ``closed_provisioned`` — ia dibekukan menjadi provisi.
        """
        self.ensure_one()
        blockers = []
        open_est = self.charge_ids.filtered(
            lambda c: c.state not in ("cancelled", "closed") and not c.is_actual_known
        )
        if open_est:
            blockers.append(_(
                "%s baris masih bernilai estimasi tanpa aktual (%s). Tutup finansial "
                "dengan provisi, atau tunggu tagihan vendor.",
                len(open_est), ", ".join(open_est[:5].mapped("charge_code_id.code")),
            ))
        if self.currency_id.compare_amounts(self.disbursement_balance, 0.0) != 0:
            blockers.append(_(
                "Akun kliring talangan belum nol: %s. Ada biaya yang ditalangi "
                "tetapi tidak pernah ditagihkan kembali.",
                self.disbursement_balance,
            ))
        return blockers

    # --- alur status -------------------------------------------------------
    def action_confirm(self):
        for job in self:
            if job.state != "draft":
                raise UserError(_("Hanya job draf yang dapat dikonfirmasi."))
            if not job.charge_ids:
                raise UserError(_(
                    "Job %s belum punya satu pun baris charge. Job tanpa charge "
                    "tidak membentuk akrual dan tidak dapat difakturkan.", job.name,
                ))
            job._generate_milestones()
            job.charge_ids.filtered(lambda c: c.state == "estimated").action_confirm()
            job.state = "confirmed"
        return True

    def action_start(self):
        for job in self:
            if job.state != "confirmed":
                raise UserError(_("Hanya job yang sudah dikonfirmasi dapat dijalankan."))
            job.state = "in_progress"
        return True

    def action_complete(self):
        for job in self:
            if job.state not in ("confirmed", "in_progress"):
                raise UserError(_("Job %s tidak sedang berjalan.", job.name))
            blockers = job._lgx_completion_blockers()
            if blockers:
                raise UserError(_(
                    "Job %s belum dapat diselesaikan:\n\n%s", job.name, "\n".join("• " + b for b in blockers),
                ))
            job.state = "completed"
        return True

    def action_close(self):
        """Tutup penuh. Menolak bila masih ada penghalang finansial."""
        for job in self:
            if job.state not in ("completed", "closed_provisioned"):
                raise UserError(_("Job %s harus selesai operasi sebelum ditutup.", job.name))
            blockers = job._lgx_close_blockers()
            if blockers:
                raise UserError(_(
                    "Job %s belum dapat ditutup penuh:\n\n%s\n\n"
                    "Gunakan 'Tutup dengan Provisi' bila tagihan vendor memang belum datang.",
                    job.name, "\n".join("• " + b for b in blockers),
                ))
            job.write({"state": "closed", "closed_date": fields.Date.context_today(job)})
        return True

    def action_cancel(self):
        for job in self:
            if job.state in ("closed", "closed_provisioned"):
                raise UserError(_("Job yang sudah ditutup tidak dapat dibatalkan."))
            invoiced = job.charge_ids.filtered(lambda c: c.state == "invoiced")
            if invoiced:
                raise UserError(_(
                    "Job %s memiliki %s baris yang sudah difakturkan. Batalkan atau "
                    "kreditkan fakturnya lebih dulu.", job.name, len(invoiced),
                ))
            job.state = "cancelled"
        return True

    def action_draft(self):
        for job in self:
            if job.state != "cancelled":
                raise UserError(_("Hanya job batal yang dapat dikembalikan ke draf."))
            job.state = "draft"
        return True

    # --- milestone ---------------------------------------------------------
    def _generate_milestones(self):
        """Isi rangkaian milestone dari template, sekali, saat konfirmasi.

        Idempoten: milestone yang sudah ada tidak digandakan, sehingga
        mengkonfirmasi ulang job yang dikembalikan ke draf tidak menghasilkan
        dua rangkaian.
        """
        Template = self.env["lgx.milestone.template"]
        Milestone = self.env["lgx.milestone"]
        for job in self:
            existing = set(job.milestone_ids.mapped("milestone_type_id").ids)
            templates = Template.search([
                ("job_type", "=", job.job_type),
                ("transport_mode", "in", (job.transport_mode, "any")),
            ], order="sequence")
            vals = []
            for tpl in templates:
                if tpl.milestone_type_id.id in existing:
                    continue
                planned = False
                if job.etd and tpl.offset_days:
                    planned = fields.Date.add(job.etd, days=tpl.offset_days)
                elif job.etd:
                    planned = job.etd
                vals.append({
                    "job_id": job.id,
                    "milestone_type_id": tpl.milestone_type_id.id,
                    "sequence": tpl.sequence,
                    "planned_date": planned,
                    "is_mandatory": tpl.is_mandatory,
                    "source": "manual",
                })
                existing.add(tpl.milestone_type_id.id)
            if vals:
                Milestone.create(vals)
        return True

    def lgx_log_milestone(self, code, actual_date=None, location=None, source="manual", note=None):
        """Catat tercapainya sebuah milestone berdasarkan KODE.

        Dipakai modul segmen, cron NLE, dan fasad API. Memakai kode dan bukan id
        supaya pemanggil tidak perlu tahu id database — sebuah endpoint yang
        menerima id milestone dari luar adalah endpoint yang bisa dipakai menulis
        ke job orang lain.
        """
        self.ensure_one()
        ms_type = self.env["lgx.milestone.type"].search([("code", "=", code)], limit=1)
        if not ms_type:
            raise UserError(_("Jenis milestone '%s' tidak dikenal.", code))
        milestone = self.milestone_ids.filtered(lambda m: m.milestone_type_id == ms_type)[:1]
        vals = {
            "actual_date": actual_date or fields.Datetime.now(),
            "source": source,
        }
        if location:
            vals["location_id"] = location.id if hasattr(location, "id") else location
        if note:
            vals["note"] = note
        # sudo() untuk PENULISANNYA, dan `created_by_id` diisi pengguna
        # SUNGGUHAN supaya jejaknya tetap jujur.
        #
        # Mencatat milestone adalah AKIBAT tindakan pemanggil, bukan data yang
        # ia sunting. Ditemukan saat menguji aplikasi pengemudi: menekan
        # "Terkirim" ditolak karena pengemudi tidak berhak MENULIS lgx.milestone.
        # Memberi hak tulis penuh akan membuat pengemudi bisa menyunting
        # milestone mana pun pada job-nya — termasuk memundurkan tanggal. Jalur
        # terkendali ini yang boleh menulis, bukan penggunanya.
        vals.setdefault("created_by_id", self.env.uid)
        if milestone:
            milestone.sudo().write(vals)
        else:
            vals.update({"job_id": self.id, "milestone_type_id": ms_type.id})
            milestone = self.env["lgx.milestone"].sudo().create(vals)
        return milestone

    # --- util --------------------------------------------------------------
    def lgx_is_jpt(self):
        """True bila job ini tergolong jasa pengurusan transportasi.

        Dipakai penentuan PPN besaran tertentu. Trucking murni dan gudang bukan
        JPT; keduanya mengikuti perlakuan PPN masing-masing.
        """
        self.ensure_one()
        return self.job_type in JPT_JOB_TYPES

    @api.constrains("operating_unit_id", "company_id")
    def _check_operating_unit_company(self):
        for job in self:
            if job.operating_unit_id and job.operating_unit_id.company_id != job.company_id:
                raise ValidationError(_(
                    "Cabang %s bukan milik perusahaan %s.",
                    job.operating_unit_id.display_name, job.company_id.display_name,
                ))

    @api.depends("name", "customer_id")
    def _compute_display_name(self):
        for job in self:
            job.display_name = f"{job.name} — {job.customer_id.name}" if job.customer_id else job.name
