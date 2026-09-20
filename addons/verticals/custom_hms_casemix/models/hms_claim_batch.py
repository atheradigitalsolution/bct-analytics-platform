# -*- coding: utf-8 -*-
"""Batch pengajuan klaim — periode layanan x jenis rawat x reguler/susulan.

=============================================================================
KEPUTUSAN: KUNCI BATCH ADALAH EMPAT SUMBU, DAN DIJAGA DI POSTGRES
=============================================================================

Penjamin menerima berkas per batch, dan batch yang sama tidak boleh dikirim
dua kali. Sumbunya empat: **periode layanan**, **jenis rawat** (RJ/RI),
**reguler atau susulan**, dan **penjamin**. Dua di antaranya sering dilupakan:
klaim rawat jalan dan rawat inap tidak boleh bercampur, dan klaim susulan
(perbaikan atas berkas yang pernah pending) diajukan sebagai berkas terpisah.

Keunikan itu dijaga ``models.Constraint`` sehingga benar-benar ada di
Postgres. Di Odoo 19, ``_sql_constraints`` diabaikan diam-diam — modul akan
terpasang "sukses" sementara dua batch kembar bisa berdiri berdampingan dan
baru ketahuan saat jumlah berkas tidak cocok dengan hitungan petugas KC.
"""
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class HmsClaimBatch(models.Model):
    _name = "hms.claim.batch"
    _description = "Batch Pengajuan Klaim"
    _order = "service_period desc, id desc"

    name = fields.Char("Nomor Batch", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    service_period = fields.Date(
        "Periode Layanan", required=True, index=True,
        help="Bulan layanan yang diajukan. Selalu disimpan sebagai tanggal 1 "
             "bulan tersebut supaya keunikan batch bisa dijaga basis data.",
    )
    care_type = fields.Selection(
        [("outpatient", "Rawat Jalan"), ("inpatient", "Rawat Inap")],
        string="Jenis Rawat", required=True, default="outpatient", index=True,
    )
    batch_type = fields.Selection(
        [("regular", "Reguler"), ("supplementary", "Susulan")],
        string="Jenis Berkas", required=True, default="regular", index=True,
        help="Berkas susulan memuat klaim yang pernah pending dan sudah "
             "diperbaiki; ia diajukan terpisah dari berkas reguler.",
    )
    payer_id = fields.Many2one("hms.payer", "Penjamin", required=True, index=True)

    claim_ids = fields.One2many("hms.claim", "batch_id", "Klaim")
    claim_count = fields.Integer("Jumlah Klaim", compute="_compute_totals", store=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda s: s.env.company.currency_id, required=True,
    )
    amount_hospital = fields.Monetary("Total Tarif RS", compute="_compute_totals", store=True)
    amount_grouped = fields.Monetary("Total Tarif Grouper",
                                     compute="_compute_totals", store=True)

    fpk_no = fields.Char("Nomor FPK",
                         help="Formulir Pengajuan Klaim yang menyertai berkas.")
    submitted_at = fields.Datetime("Waktu Pengajuan", readonly=True, copy=False)
    submitted_by_id = fields.Many2one("res.users", "Diajukan Oleh", readonly=True, copy=False)
    ba_no = fields.Char("Nomor Berita Acara")
    ba_date = fields.Date("Tanggal Berita Acara")
    reconciliation_state = fields.Selection(
        [("draft", "Disusun"), ("submitted", "Diajukan"),
         ("verified", "Hasil Verifikasi Diterima"),
         ("reconciled", "Direkonsiliasi"), ("closed", "Ditutup")],
        string="Status Batch", default="draft", required=True, index=True,
    )
    note = fields.Text("Catatan")
    company_id = fields.Many2one("res.company", default=lambda s: s.env.company, required=True)

    _name_uniq = models.Constraint("unique(name)", "Nomor batch harus unik.")
    _batch_key_uniq = models.Constraint(
        "unique(company_id, service_period, care_type, batch_type, payer_id)",
        "Batch untuk periode, jenis rawat, jenis berkas dan penjamin ini sudah ada.",
    )

    @api.depends("claim_ids.hospital_bill_amount", "claim_ids.grouped_tariff")
    def _compute_totals(self):
        for batch in self:
            batch.claim_count = len(batch.claim_ids)
            batch.amount_hospital = sum(batch.claim_ids.mapped("hospital_bill_amount"))
            batch.amount_grouped = sum(batch.claim_ids.mapped("grouped_tariff"))

    @api.depends("name", "service_period", "care_type", "batch_type")
    def _compute_display_name(self):
        care = dict(self._fields["care_type"].selection)
        kind = dict(self._fields["batch_type"].selection)
        for rec in self:
            period = rec.service_period.strftime("%Y-%m") if rec.service_period else "-"
            rec.display_name = (
                f"{rec.name} — {period} {care.get(rec.care_type, '')} "
                f"{kind.get(rec.batch_type, '')}"
            )

    @api.constrains("service_period")
    def _check_period_is_first_of_month(self):
        for rec in self:
            if rec.service_period and rec.service_period.day != 1:
                raise ValidationError(_(
                    "Periode layanan harus tanggal 1 bulan yang bersangkutan. "
                    "Tanpa itu, dua batch untuk bulan yang sama bisa berdiri "
                    "berdampingan tanpa terdeteksi."
                ))

    def _existing_with_same_key(self, values):
        """Batch lain dengan kunci empat sumbu yang sama, kalau ada.

        Keunikan sesungguhnya tetap dijaga ``_batch_key_uniq`` di Postgres —
        dua permintaan bersamaan tidak bisa dihalangi pemeriksaan Python.
        Yang dikerjakan pemeriksaan ini hanya **pesannya**: constraint basis
        data naik sebagai ``IntegrityError``, dan sebuah IntegrityError yang
        sampai ke petugas adalah 500 tanpa keterangan. Jadi kejadian yang
        lazim (petugas menyusun batch yang sudah pernah dibuat) dijawab
        kalimat, dan kejadian yang langka (balapan) tetap dijawab basis data.
        """
        domain = [
            ("company_id", "=", values.get("company_id") or self.env.company.id),
            ("service_period", "=", values.get("service_period")),
            ("care_type", "=", values.get("care_type") or "outpatient"),
            ("batch_type", "=", values.get("batch_type") or "regular"),
            ("payer_id", "=", values.get("payer_id")),
        ]
        if self:
            domain.append(("id", "not in", self.ids))
        return self.search(domain, limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hms.claim.batch") or "/"
            period = vals.get("service_period")
            if period:
                vals["service_period"] = fields.Date.to_date(period).replace(day=1)
            twin = self._existing_with_same_key(vals)
            if twin:
                raise ValidationError(_(
                    "Batch %(n)s sudah memuat kombinasi periode %(p)s, %(c)s, "
                    "%(k)s dan penjamin %(y)s. Satu kombinasi hanya boleh "
                    "diajukan satu kali; tambahkan klaimnya ke batch itu, atau "
                    "buat berkas susulan."
                ) % {
                    "n": twin.name,
                    "p": twin.service_period.strftime("%Y-%m"),
                    "c": dict(self._fields["care_type"].selection)[twin.care_type],
                    "k": dict(self._fields["batch_type"].selection)[twin.batch_type],
                    "y": twin.payer_id.display_name,
                })
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Penyusunan isi batch
    # ------------------------------------------------------------------
    def _candidate_domain(self):
        """Klaim yang boleh masuk batch ini.

        Empat sumbu kunci batch dipakai ulang sebagai saringan, ditambah dua
        syarat yang tidak kelihatan dari kuncinya: klaim harus sudah
        ``finalized`` (batch bukan tempat menyimpan pekerjaan yang belum
        selesai) dan belum terikat batch lain (satu klaim tidak boleh
        diajukan lewat dua berkas).

        Periode dicocokkan pada ``discharge_at``, bukan pada tanggal klaim
        dibuat: yang ditagihkan adalah bulan pelayanannya, dan berkas yang
        disusun terlambat tetap milik bulan pasien dilayani.
        """
        self.ensure_one()
        period_start = self.service_period
        next_month = (period_start + relativedelta(months=1))
        return [
            ("state", "=", "finalized"),
            ("batch_id", "=", False),
            ("care_type", "=", self.care_type),
            ("payer_id", "=", self.payer_id.id),
            ("company_id", "=", self.company_id.id),
            ("discharge_at", ">=", fields.Datetime.to_datetime(period_start)),
            ("discharge_at", "<", fields.Datetime.to_datetime(next_month)),
        ]

    def candidate_claims(self):
        self.ensure_one()
        return self.env["hms.claim"].search(self._candidate_domain())

    def _ensure_draft(self, what):
        self.ensure_one()
        if self.reconciliation_state != "draft":
            raise UserError(_(
                "Batch %(b)s sudah diajukan; isinya tidak dapat %(w)s lagi. "
                "Klaim yang terlambat diajukan lewat berkas susulan."
            ) % {"b": self.name, "w": what})

    def action_collect_claims(self):
        """Susun batch dari seluruh klaim final yang cocok dengan kuncinya."""
        for batch in self:
            batch._ensure_draft(_("diubah"))
            candidates = batch.candidate_claims()
            if not candidates:
                raise UserError(_(
                    "Tidak ada klaim final %(c)s periode %(p)s untuk penjamin "
                    "%(y)s yang belum masuk batch."
                ) % {"c": dict(batch._fields["care_type"].selection)[batch.care_type],
                     "p": batch.service_period.strftime("%Y-%m"),
                     "y": batch.payer_id.display_name})
            candidates.write({"batch_id": batch.id})
        return True

    def action_add_claims(self, claim_ids):
        """Masukkan klaim tertentu, dengan penolakan yang menyebut sebabnya."""
        self.ensure_one()
        self._ensure_draft(_("diubah"))
        claims = self.env["hms.claim"].browse([int(i) for i in claim_ids or []]).exists()
        if not claims:
            raise UserError(_("Tidak ada klaim yang dipilih."))
        allowed = self.env["hms.claim"].search(
            self._candidate_domain() + [("id", "in", claims.ids)]
        )
        rejected = claims - allowed
        if rejected:
            raise UserError(_(
                "Klaim %(l)s tidak dapat masuk batch %(b)s: hanya klaim "
                "berstatus Final, belum terikat batch lain, dengan jenis "
                "rawat, penjamin dan periode layanan yang sama dengan kunci "
                "batch yang boleh diajukan bersama."
            ) % {"l": ", ".join(rejected.mapped("name")[:5]), "b": self.name})
        allowed.write({"batch_id": self.id})
        return True

    def action_remove_claims(self, claim_ids):
        self.ensure_one()
        self._ensure_draft(_("diubah"))
        claims = self.claim_ids.filtered(lambda c: c.id in {int(i) for i in claim_ids or []})
        if not claims:
            raise UserError(_("Klaim tersebut tidak ada di batch ini."))
        claims.write({"batch_id": False})
        return True

    def action_submit(self):
        """Ajukan seluruh klaim di batch ini sekaligus.

        Berhenti pada klaim pertama yang tidak lolos, dan tidak mengajukan
        sebagian: berkas yang dikirim setengah menghasilkan FPK yang jumlahnya
        tidak cocok dengan isinya, dan petugas KC yang menghitungnya yang
        menanggung akibatnya.
        """
        for batch in self:
            if batch.reconciliation_state != "draft":
                raise UserError(_("Batch %s sudah diajukan.") % batch.name)
            if not batch.claim_ids:
                raise UserError(_("Batch %s belum berisi klaim.") % batch.name)
            not_final = batch.claim_ids.filtered(lambda c: c.state != "finalized")
            if not_final:
                raise UserError(_(
                    "Batch %(b)s memuat %(c)s klaim yang belum final: %(l)s."
                ) % {"b": batch.name, "c": len(not_final),
                     "l": ", ".join(not_final.mapped("name")[:5])})
            mismatched = batch.claim_ids.filtered(
                lambda c: c.care_type != batch.care_type or c.payer_id != batch.payer_id
            )
            if mismatched:
                raise UserError(_(
                    "Batch %(b)s memuat klaim dengan jenis rawat atau penjamin "
                    "yang berbeda: %(l)s."
                ) % {"b": batch.name, "l": ", ".join(mismatched.mapped("name")[:5])})
            batch.claim_ids.action_submit()
            batch.write({
                "reconciliation_state": "submitted",
                "submitted_at": fields.Datetime.now(),
                "submitted_by_id": self.env.uid,
            })
        return True

    def action_mark_verified(self):
        for batch in self:
            if batch.reconciliation_state != "submitted":
                raise UserError(_("Batch %s belum diajukan.") % batch.name)
            batch.write({"reconciliation_state": "verified"})
        return True

    def action_reconcile(self):
        for batch in self:
            if batch.reconciliation_state != "verified":
                raise UserError(_(
                    "Rekonsiliasi dilakukan setelah hasil verifikasi penjamin "
                    "diterima."
                ))
            if not batch.ba_no:
                raise UserError(_(
                    "Nomor berita acara wajib diisi sebelum batch "
                    "direkonsiliasi — rekonsiliasi tanpa berita acara tidak "
                    "bisa dipertanggungjawabkan ke bendahara."
                ))
            batch.write({"reconciliation_state": "reconciled"})
        return True

    def action_close(self):
        for batch in self:
            if batch.reconciliation_state != "reconciled":
                raise UserError(_("Batch hanya dapat ditutup setelah direkonsiliasi."))
            batch.write({"reconciliation_state": "closed"})
        return True

    def unlink(self):
        if any(b.reconciliation_state != "draft" for b in self):
            raise UserError(_("Batch yang sudah diajukan tidak dapat dihapus."))
        return super().unlink()
