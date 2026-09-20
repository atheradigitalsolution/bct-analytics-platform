# -*- coding: utf-8 -*-
"""Radiology examinations and their expert reports."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .hms_rad_exam import MODALITIES


class HmsRadReport(models.Model):
    _name = "hms.rad.report"
    _description = "Ekspertise Radiologi"
    _inherit = ["hms.audited", "hms.critical.ack"]
    _order = "id desc"

    order_line_id = fields.Many2one("hms.order.line", "Baris Order", required=True,
                                    ondelete="cascade", index=True)
    order_id = fields.Many2one(related="order_line_id.order_id", store=True, index=True)
    encounter_id = fields.Many2one(related="order_line_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="order_line_id.patient_id", store=True, index=True)
    exam_name = fields.Char("Pemeriksaan", related="order_line_id.name", store=True)

    exam_id = fields.Many2one(
        "hms.rad.exam", "Pemeriksaan (Katalog)", index=True, ondelete="restrict",
        help="Entri katalog radiologi. Memilihnya MENGISI modalitas, regio dan "
             "kebutuhan kontras yang masih kosong — tidak pernah menimpa nilai "
             "yang sudah diketik petugas.",
    )
    preparation_note = fields.Text(
        "Persiapan Pasien", related="exam_id.preparation_note", readonly=True,
    )
    # Daftar modalitas sama persis dengan katalog (satu konstanta, dua model),
    # supaya keduanya tidak bisa menyimpang. Nilai lamanya tidak berubah.
    modality = fields.Selection(
        MODALITIES,
        required=True, default="xray",
    )
    body_part = fields.Char("Regio / Bagian Tubuh")
    contrast_used = fields.Boolean("Menggunakan Kontras")
    contrast_agent = fields.Char("Jenis Kontras")

    performed_at = fields.Datetime("Waktu Pemeriksaan")
    radiographer_id = fields.Many2one("hms.practitioner", "Radiografer",
                                      domain="[('type', '=', 'radiographer')]")
    radiologist_id = fields.Many2one("hms.practitioner", "Radiolog",
                                     domain="[('type', '=', 'doctor')]")

    clinical_info = fields.Text("Keterangan Klinis")
    technique = fields.Text("Teknik Pemeriksaan")
    findings = fields.Text("Hasil / Deskripsi")
    impression = fields.Text("Kesan")
    suggestion = fields.Text("Saran")
    is_critical = fields.Boolean(
        "Temuan Kritis",
        help="Temuan yang harus dilaporkan langsung ke dokter pengirim, mis. "
             "pneumotoraks, perdarahan intrakranial.",
    )

    image_ids = fields.Many2many("ir.attachment", string="Lampiran Citra")
    state = fields.Selection(
        [("scheduled", "Dijadwalkan"), ("performed", "Sudah Dikerjakan"),
         ("reported", "Ekspertise Ditulis"), ("verified", "Diverifikasi Radiolog"),
         ("cancelled", "Dibatalkan")],
        default="scheduled", required=True, index=True,
    )
    verified_at = fields.Datetime(readonly=True)

    _line_uniq = models.Constraint(
        "unique(order_line_id)", "Satu baris order radiologi hanya punya satu ekspertise.",
    )

    @api.onchange("exam_id")
    def _onchange_exam_id(self):
        """Isi modalitas/regio/kontras dari katalog di layar.

        Hanya mengisi yang masih kosong untuk regio; modalitas dan kontras
        memang mengikuti katalog karena keduanya adalah sifat alat, bukan
        pengamatan petugas.
        """
        for rec in self:
            if not rec.exam_id:
                continue
            defaults = rec.exam_id._report_defaults()
            rec.modality = defaults["modality"]
            rec.contrast_used = defaults["contrast_used"]
            if defaults.get("body_part"):
                rec.body_part = defaults["body_part"]

    @api.model
    def _exam_catalog_vals(self, vals):
        """Lengkapi vals dengan nilai katalog untuk field yang tidak dikirim.

        Dipasang di ``create``/``write``, bukan hanya di ``onchange``: baris
        ekspertise dibuat oleh kode (``action_order``) dan oleh API, dan
        keduanya tidak pernah menjalankan onchange. Gerbang "hanya isi yang
        tidak dikirim" menjaga sifat aditifnya — pemanggil yang menyebut
        modalitas sendiri tetap menang atas katalog.
        """
        if not vals.get("exam_id"):
            return vals
        exam = self.env["hms.rad.exam"].browse(vals["exam_id"])
        if not exam.exists():
            return vals
        for key, value in exam._report_defaults().items():
            vals.setdefault(key, value)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._exam_catalog_vals(dict(v)) for v in vals_list])

    def write(self, vals):
        return super().write(self._exam_catalog_vals(dict(vals)))

    def _current_practitioner(self):
        practitioner = self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        if not practitioner:
            raise UserError(
                _("Pengguna %s belum terhubung ke data praktisi.") % self.env.user.name
            )
        return practitioner

    def action_perform(self):
        practitioner = self._current_practitioner()
        for rec in self:
            if rec.state != "scheduled":
                raise UserError(_("Pemeriksaan sudah dikerjakan."))
            rec.write({
                "state": "performed",
                "performed_at": fields.Datetime.now(),
                "radiographer_id": rec.radiographer_id.id or practitioner.id,
            })
            rec.order_line_id.filtered(lambda l: l.state == "ordered").action_start()
        return True

    def action_report(self):
        for rec in self:
            if rec.state != "performed":
                raise UserError(_("Pemeriksaan belum dikerjakan."))
            if not rec.findings or not rec.impression:
                raise UserError(
                    _("Hasil dan kesan wajib diisi — ekspertise tanpa kesan tidak dapat "
                      "dipakai dokter pengirim.")
                )
            rec.write({"state": "reported"})
        return True

    def action_verify(self):
        practitioner = self._current_practitioner()
        for rec in self:
            if rec.state != "reported":
                raise UserError(_("Ekspertise belum ditulis."))
            rec.write({
                "state": "verified",
                "radiologist_id": rec.radiologist_id.id or practitioner.id,
                "verified_at": fields.Datetime.now(),
            })
            rec.env["hms.event"].emit("result.verified", {
                "rad_report_id": rec.id,
                "encounter_id": rec.encounter_id.id,
                "patient_id": rec.patient_id.id,
                "exam": rec.exam_name,
                "critical": rec.is_critical,
            })
            if rec.is_critical:
                rec.env["hms.event"].emit("result.critical", {
                    "rad_report_id": rec.id,
                    "encounter_id": rec.encounter_id.id,
                    "patient_id": rec.patient_id.id,
                    "patient": rec.patient_id.name,
                    "parameter": rec.exam_name,
                    "impression": (rec.impression or "")[:200],
                    "practitioner_id": rec.encounter_id.practitioner_id.id,
                })
            if rec.order_line_id.state in ("ordered", "in_progress"):
                rec.order_line_id.action_done()
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "verified":
                raise UserError(_("Ekspertise yang sudah diverifikasi tidak dapat dibatalkan."))
            rec.write({"state": "cancelled"})
        return True


    # ------------------------------------------------------------------
    # Closed-loop nilai kritis (TBaK: Tulis — Baca kembali — Konfirmasi).
    #
    # Sebuah temuan kritis yang ditulis tapi tidak pernah dibaca dokter pengirim
    # bukan nilai kritis yang tertangani. Akreditasi menuntut bukti empat
    # hal: siapa melapor, kepada siapa, kapan, dan kapan diakui.
    # ------------------------------------------------------------------
    notified_at = fields.Datetime(
        "Dilaporkan Pada", readonly=True,
        help="Saat temuan kritis ini dilaporkan ke klinisi. Diisi oleh "
             "tombol Laporkan, bukan diketik manual.",
    )
    notified_by_id = fields.Many2one(
        "res.users", "Dilaporkan Oleh", readonly=True,
        help="Petugas radiologi yang melakukan pelaporan.",
    )
    notified_to_id = fields.Many2one(
        "hms.practitioner", "Dilaporkan Kepada",
        help="Klinisi yang dihubungi. Default-nya dokter penanggung jawab kunjungan.",
    )
    notify_channel = fields.Selection(
        [("phone", "Telepon"), ("in_person", "Langsung / Tatap Muka"),
         ("system", "Melalui Sistem")],
        string="Cara Pelaporan",
        help="Cara temuan kritis disampaikan ke klinisi.",
    )
    acknowledged_at = fields.Datetime(
        "Diakui Pada", readonly=True,
        help="Saat klinisi mengakui temuan kritis ini. Tidak pernah ditimpa "
             "oleh pengakuan berikutnya.",
    )
    acknowledged_by_id = fields.Many2one(
        "res.users", "Diakui Oleh", readonly=True,
        help="Pengguna yang menekan tombol Akui. Selalu pengguna yang sedang "
             "login — tidak dapat dititipkan pemanggil.",
    )
    ack_readback = fields.Text(
        "Isi Read-back (TBaK)",
        help="Kalimat yang dibacakan ulang oleh penerima laporan, sebagai "
             "bukti isi laporan benar-benar diterima utuh.",
    )
    ack_minutes = fields.Integer(
        "Menit Sampai Diakui", compute="_compute_ack_minutes", store=True,
        help="Selisih menit antara verifikasi ekspertise dan pengakuan klinisi. "
             "Nol bila belum diakui.",
    )
    ack_state = fields.Selection(
        [("not_required", "Tidak Perlu"), ("pending", "Menunggu Pengakuan"),
         ("acknowledged", "Sudah Diakui"), ("overdue", "Terlambat")],
        string="Status Pengakuan", compute="_compute_ack_state", store=True, index=True,
        default="not_required",
        help="Status closed-loop pelaporan nilai kritis.",
    )

    @api.depends("verified_at", "acknowledged_at")
    def _compute_ack_minutes(self):
        for rec in self:
            if rec.verified_at and rec.acknowledged_at:
                delta = rec.acknowledged_at - rec.verified_at
                rec.ack_minutes = max(0, int(delta.total_seconds() // 60))
            else:
                rec.ack_minutes = 0

    @api.depends("is_critical", "state", "verified_at", "acknowledged_at")
    def _compute_ack_state(self):
        """Hitung status closed-loop.

        CATATAN DESAIN — kenapa stored padahal bergantung waktu berjalan.

        `overdue` adalah fungsi dari *sekarang*, jadi computed-stored murni
        tidak akan pernah berpindah sendiri dari `pending` ke `overdue`:
        tidak ada dependensi yang berubah saat tenggat lewat. Pilihan yang
        diambil adalah (a) stored + cron penyapu
        (`_cron_refresh_ack_state`, tiap 5 menit, ada di
        `data/hms_radiology_cron.xml` dan diuji di `tests/test_radiology.py`).

        Alasan memilih stored daripada non-stored: konsumen berikutnya
        (indikator mutu INM "pelaporan hasil kritis" dan layar dokter)
        perlu MENCARI dan MENGELOMPOKKAN baris `overdue` di seluruh basis
        data. Field non-stored tidak bisa di-`search()` tanpa menulis
        `search=` sendiri, dan pengelompokan read_group-nya tidak ada sama
        sekali. Harga yang dibayar: nilai `overdue` benar dengan galat
        paling lama satu siklus cron (5 menit) terhadap tenggat 30 menit —
        dan itu diakui di sini, bukan disembunyikan.
        """
        settings = self.env["hms.settings"].get_settings()
        limit_minutes = settings.critical_result_ack_minutes or 0
        now = fields.Datetime.now()
        for rec in self:
            if not rec.is_critical:
                rec.ack_state = "not_required"
            elif rec.acknowledged_at:
                rec.ack_state = "acknowledged"
            elif rec.state != "verified" or not rec.verified_at:
                # Jam baru berjalan setelah ekspertise dilepas ke rekam medis.
                # Sebelum verifikasi belum ada apa pun yang bisa diakui.
                rec.ack_state = "not_required"
            elif limit_minutes > 0 and (now - rec.verified_at) > timedelta(minutes=limit_minutes):
                rec.ack_state = "overdue"
            else:
                rec.ack_state = "pending"

    @api.model
    def _cron_refresh_ack_state(self, limit=1000):
        """Pindahkan baris `pending` yang tenggatnya sudah lewat menjadi `overdue`.

        Hanya baris yang benar-benar melewati ambang yang disentuh, sehingga
        cron ini membaca lewat indeks `ack_state` dan tidak menulis apa pun
        pada hari yang tenang.
        """
        settings = self.env["hms.settings"].get_settings()
        limit_minutes = settings.critical_result_ack_minutes or 0
        if limit_minutes <= 0:
            return 0
        deadline = fields.Datetime.now() - timedelta(minutes=limit_minutes)
        stale = self.search(
            [("ack_state", "=", "pending"), ("verified_at", "<", deadline)], limit=limit
        )
        if not stale:
            return 0
        self.env.add_to_compute(self._fields["ack_state"], stale)
        stale.flush_recordset(["ack_state"])
        return len(stale)

    def action_notify(self, practitioner_id=None, channel=None):
        """Catat pelaporan temuan kritis ke klinisi.

        `notified_at` pertama yang menang: indikator mutu mengukur jarak dari
        verifikasi ke laporan PERTAMA. Panggilan berikutnya (mis. dokter
        pertama tidak terhubung) boleh mengganti tujuan dan kanalnya, tapi
        tidak memutar balik jam.
        """
        for rec in self:
            if not rec.is_critical:
                raise UserError(
                    _("Ekspertise %s tidak ditandai temuan kritis; tidak ada yang perlu dilaporkan.")
                    % rec.exam_name
                )
            vals = {
                "notified_at": rec.notified_at or fields.Datetime.now(),
                "notified_by_id": rec.notified_by_id.id or self.env.user.id,
            }
            if practitioner_id:
                vals["notified_to_id"] = practitioner_id
            elif not rec.notified_to_id:
                vals["notified_to_id"] = rec.encounter_id.practitioner_id.id
            if channel:
                vals["notify_channel"] = channel
            rec.write(vals)
        return True

    def action_acknowledge(self, readback=None):
        """Pengakuan klinisi atas temuan kritis — sisi 'tertutup' dari lingkaran.

        Sengaja TANPA elevasi hak akses. Yang mengakui nilai kritis harus benar-benar
        berhak membaca ekspertisenya; meng-elevate hak justru menghapus makna
        buktinya — yang tercatat menjadi "sistem", bukan "dokter".
        """
        for rec in self:
            if rec.state != "verified":
                raise UserError(
                    _("Ekspertise %s belum diverifikasi radiolog; belum ada yang bisa diakui.")
                    % rec.exam_name
                )
            if not rec.is_critical:
                raise UserError(
                    _("Ekspertise %s tidak ditandai temuan kritis; tidak perlu pengakuan.")
                    % rec.exam_name
                )
            if rec.acknowledged_at:
                # Idempoten: pengakuan PERTAMA adalah buktinya. Menimpanya
                # berarti memperbaiki angka keterlambatan setelah kejadian.
                if readback and not rec.ack_readback:
                    rec.write({"ack_readback": readback})
                continue
            vals = {
                "acknowledged_at": fields.Datetime.now(),
                # Bukan dari parameter: pemanggil tidak boleh menitipkan
                # identitas orang lain sebagai pengaku.
                "acknowledged_by_id": self.env.user.id,
            }
            if readback:
                vals["ack_readback"] = readback
            rec.write(vals)
            rec.env["hms.event"].emit("result.acknowledged", {
                "rad_report_id": rec.id,
                "encounter_id": rec.encounter_id.id,
                "patient_id": rec.patient_id.id,
                "exam": rec.exam_name,
                "acknowledged_by": self.env.user.name,
                "ack_minutes": rec.ack_minutes,
            })
        return True


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    rad_report_ids = fields.One2many("hms.rad.report", "order_line_id", "Ekspertise Radiologi")

    def action_order(self):
        """A radiology line schedules its examination as soon as it is ordered.

        Unlike lab, the examination itself is a physical appointment that the
        radiographer needs to see on a worklist before any result exists.
        """
        res = super().action_order()
        Report = self.env["hms.rad.report"]
        for line in self.filtered(lambda l: l.order_type == "radiology"):
            if line.rad_report_ids:
                continue
            # Katalog dicari lewat tarif: memesan "USG Abdomen" harus
            # langsung menghasilkan ekspertise ber-modalitas USG, tanpa
            # radiografer memilih ulang apa yang sudah dipesan dokter.
            exam = self.env["hms.rad.exam"].search(
                [("tariff_id", "=", line.tariff_id.id)], limit=1
            )
            Report.create({
                "order_line_id": line.id,
                "clinical_info": line.order_id.clinical_note,
                "exam_id": exam.id or False,
            })
        return res


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    rad_report_ids = fields.One2many("hms.rad.report", "encounter_id", "Ekspertise Radiologi")
