# -*- coding: utf-8 -*-
"""Lab order lines create their result shells when work starts.

Gerbang mutu pra-analitik ada di sini, bukan di layar. Sebuah spesimen yang
hemolisis, salah tabung, atau tidak beridentitas TIDAK boleh menghasilkan
angka — dan penolakannya harus meninggalkan alasan yang bisa dihitung, karena
angka penolakan spesimen adalah indikator mutu laboratorium tersendiri.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError

SPECIMEN_STATES = [
    ("pending", "Belum Diterima"),
    ("received", "Diterima"),
    ("rejected", "Ditolak"),
]

# Kategori penolakan pra-analitik yang lazim dipakai laboratorium klinik.
# Disimpan sebagai pilihan, bukan teks bebas, supaya bisa dikelompokkan:
# "berapa persen spesimen ditolak, dan karena apa" tidak bisa dijawab dari
# kolom Char.
SPECIMEN_REJECT_REASONS = [
    ("hemolysis", "Hemolisis"),
    ("insufficient", "Volume Tidak Cukup"),
    ("clotted", "Terdapat Bekuan"),
    ("wrong_container", "Salah Tabung / Wadah"),
    ("unlabeled", "Identitas Spesimen Tidak Lengkap"),
    ("contaminated", "Terkontaminasi"),
    ("delayed", "Terlambat Sampai (lewat batas stabilitas)"),
    ("other", "Lainnya"),
]


class HmsOrderLine(models.Model):
    _inherit = "hms.order.line"

    lab_result_ids = fields.One2many("hms.lab.result", "order_line_id", "Hasil Lab")
    lab_result_count = fields.Integer(compute="_compute_lab_result_count")
    has_critical_result = fields.Boolean(compute="_compute_lab_result_count")

    specimen_state = fields.Selection(
        SPECIMEN_STATES, "Status Spesimen", default="pending", required=True, index=True,
        help="Gerbang pra-analitik. Spesimen yang ditolak menghentikan "
             "pemeriksaan; hasil tidak pernah dibuat untuknya.",
    )
    specimen_received_at = fields.Datetime("Spesimen Diterima", readonly=True)
    specimen_received_by_id = fields.Many2one(
        "res.users", "Penerima Spesimen", readonly=True,
        help="Petugas yang menerima spesimen. Selalu pengguna yang login.",
    )
    specimen_rejected_at = fields.Datetime("Spesimen Ditolak", readonly=True)
    specimen_rejected_by_id = fields.Many2one("res.users", "Penolak Spesimen", readonly=True)
    specimen_reject_reason = fields.Selection(
        SPECIMEN_REJECT_REASONS, "Alasan Penolakan",
        help="Wajib diisi saat menolak spesimen.",
    )
    specimen_reject_note = fields.Char("Keterangan Penolakan")

    @api.depends("lab_result_ids.state", "lab_result_ids.is_critical")
    def _compute_lab_result_count(self):
        for line in self:
            line.lab_result_count = len(line.lab_result_ids)
            line.has_critical_result = any(line.lab_result_ids.mapped("is_critical"))

    def action_start(self):
        """Starting a lab line materialises one empty result per parameter.

        Created on start rather than on order: a cancelled order should not
        leave a row of blank results behind for an analyst to wonder about.

        Daftar parameternya diminta ke ``hms.tariff._hms_lab_parameters()``,
        yang mendahulukan katalog ``hms.lab.test`` dan jatuh kembali ke
        ``hms.lab.parameter.tariff_ids`` bila tarifnya belum dikatalogkan.
        """
        for line in self.filtered(lambda l: l.order_type == "lab"):
            if line.specimen_state == "rejected":
                raise UserError(
                    _("Spesimen untuk '%(n)s' ditolak (%(r)s). Pemeriksaan tidak "
                      "dapat dikerjakan; mintakan pengambilan ulang lewat order baru.")
                    % {"n": line.name,
                       "r": dict(SPECIMEN_REJECT_REASONS).get(
                           line.specimen_reject_reason, _("tanpa alasan"))}
                )
        res = super().action_start()
        Result = self.env["hms.lab.result"]
        for line in self.filtered(lambda l: l.order_type == "lab"):
            if line.lab_result_ids:
                continue
            parameters = line.tariff_id._hms_lab_parameters()
            Result.create([
                {"order_line_id": line.id, "parameter_id": parameter.id}
                for parameter in parameters
            ])
        return res

    # --- gerbang pra-analitik --------------------------------------------
    def action_receive_specimen(self):
        """Terima spesimen, lalu mulai pemeriksaannya.

        Satu tombol, dua akibat, karena di lab keduanya memang satu kejadian:
        spesimen yang diterima petugas langsung masuk worklist. Memisahkannya
        menghasilkan antrian 'sudah diterima tapi belum dikerjakan' yang tidak
        pernah dibersihkan siapa pun.
        """
        for line in self:
            if line.order_type != "lab":
                raise UserError(
                    _("Penerimaan spesimen hanya berlaku untuk baris order laboratorium.")
                )
            if line.specimen_state == "rejected":
                raise UserError(
                    _("Spesimen untuk '%s' sudah ditolak dan tidak dapat diterima kembali.")
                    % line.name
                )
            if line.specimen_state != "received":
                line.write({
                    "specimen_state": "received",
                    "specimen_received_at": fields.Datetime.now(),
                    "specimen_received_by_id": self.env.uid,
                })
            if line.state == "ordered":
                line.action_start()
        return True

    def action_reject_specimen(self, reason=None, note=None):
        """Tolak spesimen dengan alasan, dan hentikan barisnya.

        Penolakan tanpa alasan ditolak di sini, bukan di form: jalur API
        memakai metode yang sama, dan alasan penolakan adalah satu-satunya
        hal yang membuat angka penolakan berguna.
        """
        for line in self:
            if line.order_type != "lab":
                raise UserError(
                    _("Penolakan spesimen hanya berlaku untuk baris order laboratorium.")
                )
            reason_value = reason or line.specimen_reject_reason
            if not reason_value:
                raise UserError(
                    _("Alasan penolakan spesimen wajib diisi untuk '%s'.") % line.name
                )
            if line.state == "done":
                raise UserError(
                    _("Pemeriksaan '%s' sudah selesai; spesimennya tidak dapat ditolak lagi.")
                    % line.name
                )
            vals = {
                "specimen_state": "rejected",
                "specimen_reject_reason": reason_value,
                "specimen_rejected_at": fields.Datetime.now(),
                "specimen_rejected_by_id": self.env.uid,
                "cancel_reason": _("Spesimen ditolak: %s")
                                 % dict(SPECIMEN_REJECT_REASONS)[reason_value],
            }
            if note:
                vals["specimen_reject_note"] = note
            line.write(vals)
            if line.state != "cancelled":
                line.action_cancel()
        return True


class HmsTariff(models.Model):
    _inherit = "hms.tariff"

    lab_parameter_ids = fields.Many2many(
        "hms.lab.parameter", "hms_tariff_lab_parameter_rel", "tariff_id", "parameter_id",
        string="Parameter Laboratorium",
        help="Parameter yang dihasilkan pemeriksaan ini. Worklist lab membuat "
             "satu baris hasil kosong per parameter. Dipakai bila tarif ini "
             "belum punya entri di katalog hms.lab.test.",
    )
    lab_test_ids = fields.One2many(
        "hms.lab.test", "tariff_id", "Katalog Pemeriksaan Lab",
    )

    def _hms_lab_parameters(self):
        """Parameter yang harus dihasilkan tarif ini, dengan fallback.

        Katalog ``hms.lab.test`` menang bila ada; kalau tidak, hubungan lama
        ``hms.lab.parameter.tariff_ids`` tetap dipakai apa adanya. Lihat
        docstring ``models/hms_lab_test.py`` untuk alasan berjenjangnya.

        Dibaca tanpa ``sudo()``: petugas yang memulai pemeriksaan memang
        berhak membaca master lab (``group_hms_staff`` punya akses baca ke
        ``hms.lab.test``), jadi tidak ada yang perlu dielevasi.
        """
        self.ensure_one()
        test = self.env["hms.lab.test"].search([("tariff_id", "=", self.id)], limit=1)
        if test and test.parameter_ids:
            return test.parameter_ids
        return self.lab_parameter_ids


class HmsEncounter(models.Model):
    _inherit = "hms.encounter"

    lab_result_ids = fields.One2many("hms.lab.result", "encounter_id", "Hasil Laboratorium")
