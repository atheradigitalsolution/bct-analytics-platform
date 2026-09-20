# -*- coding: utf-8 -*-
"""Lab results: entry, validation by the analyst, verification by the doctor."""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HmsLabResult(models.Model):
    _name = "hms.lab.result"
    _description = "Hasil Laboratorium"
    _inherit = ["hms.audited", "hms.critical.ack"]
    _order = "order_line_id, parameter_id"

    order_line_id = fields.Many2one("hms.order.line", "Baris Order", required=True,
                                    ondelete="cascade", index=True)
    order_id = fields.Many2one(related="order_line_id.order_id", store=True, index=True)
    encounter_id = fields.Many2one(related="order_line_id.encounter_id", store=True, index=True)
    patient_id = fields.Many2one(related="order_line_id.patient_id", store=True, index=True)
    parameter_id = fields.Many2one("hms.lab.parameter", "Parameter", required=True, index=True)

    value_numeric = fields.Float("Nilai", digits=(16, 4))
    value_text = fields.Char("Nilai (Teks)")
    uom_name = fields.Char(related="parameter_id.uom_name", readonly=True, string="Satuan")
    ref_display = fields.Char("Rujukan", compute="_compute_evaluation", store=True)
    flag = fields.Selection(
        [("normal", "Normal"), ("low", "Rendah (L)"), ("high", "Tinggi (H)"),
         ("critical_low", "Kritis Rendah (LL)"), ("critical_high", "Kritis Tinggi (HH)")],
        compute="_compute_evaluation", store=True, string="Penanda",
    )
    is_critical = fields.Boolean(compute="_compute_evaluation", store=True)

    state = fields.Selection(
        [("pending", "Menunggu Hasil"), ("entered", "Hasil Masuk"),
         ("validated", "Divalidasi Analis"), ("verified", "Diverifikasi Dokter"),
         ("rejected", "Ditolak")],
        default="pending", required=True, index=True,
    )
    entered_by_id = fields.Many2one("hms.practitioner", "Diinput Oleh", readonly=True)
    entered_at = fields.Datetime(readonly=True)
    validated_by_id = fields.Many2one("hms.practitioner", "Divalidasi Analis", readonly=True)
    verified_by_id = fields.Many2one("hms.practitioner", "Diverifikasi Dokter PJ", readonly=True)
    verified_at = fields.Datetime(readonly=True)
    note = fields.Char("Catatan")

    _line_param_uniq = models.Constraint(
        "unique(order_line_id, parameter_id)",
        "Satu parameter hanya boleh punya satu hasil per baris order.",
    )

    @api.depends("value_numeric", "parameter_id", "patient_id.gender", "patient_id.age_years")
    def _compute_evaluation(self):
        for res in self:
            rng = res.parameter_id.find_range(
                gender=res.patient_id.gender, age_years=res.patient_id.age_years
            )
            if not rng or res.parameter_id.value_type != "numeric":
                res.ref_display = rng.note if rng else False
                res.flag = "normal"
                res.is_critical = False
                continue
            low, high = rng.ref_low, rng.ref_high
            res.ref_display = f"{low:g} – {high:g} {res.parameter_id.uom_name or ''}".strip()
            value = res.value_numeric
            if rng.critical_low and value and value <= rng.critical_low:
                res.flag = "critical_low"
            elif rng.critical_high and value and value >= rng.critical_high:
                res.flag = "critical_high"
            elif high and value > high:
                res.flag = "high"
            elif low and value < low:
                res.flag = "low"
            else:
                res.flag = "normal"
            res.is_critical = res.flag in ("critical_low", "critical_high")

    def _current_practitioner(self):
        practitioner = self.env["hms.practitioner"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        if not practitioner:
            raise UserError(
                _("Pengguna %s belum terhubung ke data praktisi.") % self.env.user.name
            )
        return practitioner

    def action_enter(self):
        practitioner = self._current_practitioner()
        for res in self:
            if res.state not in ("pending", "entered", "rejected"):
                raise UserError(_("Hasil sudah divalidasi dan tidak dapat diubah di sini."))
            res.write({
                "state": "entered",
                "entered_by_id": practitioner.id,
                "entered_at": fields.Datetime.now(),
            })
        return True

    def action_validate(self):
        practitioner = self._current_practitioner()
        for res in self:
            if res.state != "entered":
                raise UserError(_("Hanya hasil yang sudah diinput yang dapat divalidasi."))
            res.write({"state": "validated", "validated_by_id": practitioner.id})
        return True

    def action_verify(self):
        """Doctor's verification. Only now does the result reach the chart."""
        practitioner = self._current_practitioner()
        for res in self:
            if res.state != "validated":
                raise UserError(
                    _("Hasil %s belum divalidasi analis.") % res.parameter_id.name
                )
            res.write({
                "state": "verified",
                "verified_by_id": practitioner.id,
                "verified_at": fields.Datetime.now(),
            })
            res.env["hms.event"].emit("result.verified", {
                "result_id": res.id,
                "order_line_id": res.order_line_id.id,
                "encounter_id": res.encounter_id.id,
                "patient_id": res.patient_id.id,
                "parameter": res.parameter_id.name,
                "flag": res.flag,
            })
            if res.is_critical:
                # A critical value is a patient-safety event, not a data point.
                res.env["hms.event"].emit("result.critical", {
                    "result_id": res.id,
                    "encounter_id": res.encounter_id.id,
                    "patient_id": res.patient_id.id,
                    "patient": res.patient_id.name,
                    "parameter": res.parameter_id.name,
                    "value": res.value_numeric,
                    "flag": res.flag,
                    "practitioner_id": res.encounter_id.practitioner_id.id,
                })
        self._close_completed_lines()
        return True

    def _close_completed_lines(self):
        """Mark the order line done once every parameter is verified."""
        for line in self.mapped("order_line_id"):
            results = self.search([("order_line_id", "=", line.id)])
            if results and all(r.state == "verified" for r in results):
                if line.state in ("ordered", "in_progress"):
                    line.action_done()

    def action_reject(self):
        for res in self:
            res.write({"state": "rejected"})
        return True

    # ------------------------------------------------------------------
    # Closed-loop nilai kritis (TBaK: Tulis — Baca kembali — Konfirmasi).
    #
    # Sebuah nilai kritis yang terdeteksi tapi tidak pernah dibaca dokter
    # bukan nilai kritis yang tertangani. Akreditasi menuntut bukti empat
    # hal: siapa melapor, kepada siapa, kapan, dan kapan diakui.
    # ------------------------------------------------------------------
    notified_at = fields.Datetime(
        "Dilaporkan Pada", readonly=True,
        help="Saat hasil kritis ini dilaporkan ke klinisi. Diisi oleh "
             "tombol Laporkan, bukan diketik manual.",
    )
    notified_by_id = fields.Many2one(
        "res.users", "Dilaporkan Oleh", readonly=True,
        help="Petugas penunjang yang melakukan pelaporan.",
    )
    notified_to_id = fields.Many2one(
        "hms.practitioner", "Dilaporkan Kepada",
        help="Klinisi yang dihubungi. Default-nya dokter penanggung jawab kunjungan.",
    )
    notify_channel = fields.Selection(
        [("phone", "Telepon"), ("in_person", "Langsung / Tatap Muka"),
         ("system", "Melalui Sistem")],
        string="Cara Pelaporan",
        help="Cara hasil kritis disampaikan ke klinisi.",
    )
    acknowledged_at = fields.Datetime(
        "Diakui Pada", readonly=True,
        help="Saat klinisi mengakui hasil kritis ini. Tidak pernah ditimpa "
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
        help="Selisih menit antara verifikasi hasil dan pengakuan klinisi. "
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
        for res in self:
            if res.verified_at and res.acknowledged_at:
                delta = res.acknowledged_at - res.verified_at
                res.ack_minutes = max(0, int(delta.total_seconds() // 60))
            else:
                res.ack_minutes = 0

    @api.depends("is_critical", "state", "verified_at", "acknowledged_at")
    def _compute_ack_state(self):
        """Hitung status closed-loop.

        CATATAN DESAIN — kenapa stored padahal bergantung waktu berjalan.

        `overdue` adalah fungsi dari *sekarang*, jadi computed-stored murni
        tidak akan pernah berpindah sendiri dari `pending` ke `overdue`:
        tidak ada dependensi yang berubah saat tenggat lewat. Pilihan yang
        diambil adalah (a) stored + cron penyapu
        (`_cron_refresh_ack_state`, tiap 5 menit, ada di
        `data/hms_lab_cron.xml` dan diuji di `tests/test_lab.py`).

        Alasan memilih stored daripada non-stored: konsumen berikutnya
        (indikator mutu INM "pelaporan hasil kritis lab" dan layar dokter)
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
        for res in self:
            if not res.is_critical:
                res.ack_state = "not_required"
            elif res.acknowledged_at:
                res.ack_state = "acknowledged"
            elif res.state != "verified" or not res.verified_at:
                # Jam baru berjalan setelah hasil dilepas ke rekam medis.
                # Sebelum verifikasi belum ada apa pun yang bisa diakui.
                res.ack_state = "not_required"
            elif limit_minutes > 0 and (now - res.verified_at) > timedelta(minutes=limit_minutes):
                res.ack_state = "overdue"
            else:
                res.ack_state = "pending"

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
        """Catat pelaporan hasil kritis ke klinisi.

        `notified_at` pertama yang menang: indikator mutu mengukur jarak dari
        verifikasi ke laporan PERTAMA. Panggilan berikutnya (mis. dokter
        pertama tidak terhubung) boleh mengganti tujuan dan kanalnya, tapi
        tidak memutar balik jam.
        """
        for res in self:
            if not res.is_critical:
                raise UserError(
                    _("Hasil %s bukan nilai kritis; tidak ada yang perlu dilaporkan.")
                    % res.parameter_id.name
                )
            vals = {
                "notified_at": res.notified_at or fields.Datetime.now(),
                "notified_by_id": res.notified_by_id.id or self.env.user.id,
            }
            if practitioner_id:
                vals["notified_to_id"] = practitioner_id
            elif not res.notified_to_id:
                vals["notified_to_id"] = res.encounter_id.practitioner_id.id
            if channel:
                vals["notify_channel"] = channel
            res.write(vals)
        return True

    def action_acknowledge(self, readback=None):
        """Pengakuan klinisi atas hasil kritis — sisi 'tertutup' dari lingkaran.

        Sengaja TANPA elevasi hak akses. Yang mengakui nilai kritis harus benar-benar
        berhak membaca hasilnya; meng-elevate hak justru menghapus makna
        buktinya — yang tercatat menjadi "sistem", bukan "dokter".
        """
        for res in self:
            if res.state != "verified":
                raise UserError(
                    _("Hasil %s belum diverifikasi; belum ada yang bisa diakui.")
                    % res.parameter_id.name
                )
            if not res.is_critical:
                raise UserError(
                    _("Hasil %s bukan nilai kritis; tidak perlu pengakuan.")
                    % res.parameter_id.name
                )
            if res.acknowledged_at:
                # Idempoten: pengakuan PERTAMA adalah buktinya. Menimpanya
                # berarti memperbaiki angka keterlambatan setelah kejadian.
                if readback and not res.ack_readback:
                    res.write({"ack_readback": readback})
                continue
            vals = {
                "acknowledged_at": fields.Datetime.now(),
                # Bukan dari parameter: pemanggil tidak boleh menitipkan
                # identitas orang lain sebagai pengaku.
                "acknowledged_by_id": self.env.user.id,
            }
            if readback:
                vals["ack_readback"] = readback
            res.write(vals)
            res.env["hms.event"].emit("result.acknowledged", {
                "result_id": res.id,
                "encounter_id": res.encounter_id.id,
                "patient_id": res.patient_id.id,
                "parameter": res.parameter_id.name,
                "flag": res.flag,
                "acknowledged_by": self.env.user.name,
                "ack_minutes": res.ack_minutes,
            })
        return True
