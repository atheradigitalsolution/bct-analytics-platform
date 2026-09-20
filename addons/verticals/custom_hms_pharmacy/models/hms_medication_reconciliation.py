# -*- coding: utf-8 -*-
"""Rekonsiliasi obat pada admisi, transfer, dan pemulangan (PKPO 4).

Rekonsiliasi adalah membandingkan **obat yang benar-benar diminum pasien di
rumah** dengan **obat yang diresepkan rumah sakit**, lalu memutuskan satu per
satu: lanjut, stop, ganti, atau tunda. Yang membuatnya berguna adalah
keputusan per-obat berikut alasannya — daftar obat tanpa keputusan hanyalah
anamnesis yang disalin.

Dua keputusan desain:

**Nama obat rumah adalah teks bebas, bukan Many2one wajib.** Pasien datang
membawa obat dari apotek luar, obat warung, dan jamu; memaksa setiap baris
memilih ``hms.medicine`` berarti separuh obat yang dibawa pasien tidak akan
pernah tercatat, dan justru obat itulah yang menimbulkan interaksi. Padanan
formularium RS (``medicine_id``) tetap disediakan, tetapi opsional.

**"Tidak ada obat rumah" adalah jawaban yang sah dan harus dinyatakan.**
Tanpa ``no_home_medication``, rekonsiliasi kosong tidak bisa dibedakan dari
rekonsiliasi yang belum dikerjakan — dan keduanya terlihat persis sama pada
laporan kepatuhan.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

DECISIONS = [
    ("continue", "Lanjut"),
    ("stop", "Stop"),
    ("substitute", "Ganti / Substitusi"),
    ("hold", "Tunda Sementara"),
]
# Keputusan selain "lanjut" berarti terapi pasien berubah; PKPO menuntut
# alasannya tertulis, bukan tersirat.
DECISIONS_NEEDING_REASON = ("stop", "substitute", "hold")


class HmsMedicationReconciliation(models.Model):
    _name = "hms.medication.reconciliation"
    _description = "Rekonsiliasi Obat"
    _inherit = ["hms.audited"]
    _order = "performed_at desc, id desc"

    name = fields.Char("Nomor", required=True, readonly=True, copy=False,
                       default=lambda s: _("Baru"), index=True)
    encounter_id = fields.Many2one("hms.encounter", "Kunjungan", required=True,
                                   ondelete="restrict", index=True)
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    moment = fields.Selection(
        [("admission", "Saat Masuk (Admisi)"),
         ("transfer", "Saat Pindah Unit"),
         ("discharge", "Saat Pulang")],
        string="Momen Rekonsiliasi", required=True, default="admission", index=True,
        help="PKPO 4: rekonsiliasi wajib dilakukan saat masuk, saat pindah "
             "unit/level perawatan, dan sebelum pulang.",
    )
    from_unit_id = fields.Many2one("hms.unit", "Dari Unit")
    to_unit_id = fields.Many2one("hms.unit", "Ke Unit")

    performed_by_id = fields.Many2one("hms.practitioner", "Dilakukan Oleh", required=True)
    performed_at = fields.Datetime("Waktu Rekonsiliasi", required=True,
                                   default=fields.Datetime.now, index=True)
    information_source = fields.Selection(
        [("patient", "Pasien"), ("family", "Keluarga"), ("packaging", "Kemasan Obat Dibawa"),
         ("referral", "Surat Rujukan"), ("previous_record", "Rekam Medis Sebelumnya"),
         ("pharmacy_record", "Catatan Apotek")],
        string="Sumber Informasi", default="patient", required=True,
    )

    no_home_medication = fields.Boolean(
        "Tidak Ada Obat Rumah",
        help="Nyatakan secara eksplisit bila pasien tidak membawa/meminum obat "
             "apa pun dari rumah. Tanpa pernyataan ini, rekonsiliasi kosong "
             "tidak dapat dibedakan dari rekonsiliasi yang belum dikerjakan.",
    )
    line_ids = fields.One2many("hms.medication.reconciliation.line", "reconciliation_id",
                               "Baris Rekonsiliasi")
    line_count = fields.Integer(compute="_compute_counts", store=True)
    discrepancy_count = fields.Integer("Jumlah Perubahan Terapi",
                                       compute="_compute_counts", store=True)

    state = fields.Selection(
        [("draft", "Draf"), ("in_progress", "Dikerjakan"), ("completed", "Selesai"),
         ("cancelled", "Dibatalkan")],
        default="draft", required=True, index=True,
    )
    completed_at = fields.Datetime("Waktu Penyelesaian", readonly=True, copy=False)
    completed_by_id = fields.Many2one("res.users", "Diselesaikan Oleh", readonly=True,
                                      copy=False)
    note = fields.Text("Catatan")

    _name_uniq = models.Constraint("unique(name)", "Nomor rekonsiliasi obat harus unik.")

    @api.depends("line_ids", "line_ids.decision")
    def _compute_counts(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.discrepancy_count = len(
                rec.line_ids.filtered(lambda l: l.decision and l.decision != "continue")
            )

    @api.constrains("no_home_medication", "line_ids")
    def _check_no_home_medication_is_honest(self):
        for rec in self:
            if rec.no_home_medication and rec.line_ids:
                raise ValidationError(_(
                    "Rekonsiliasi %s ditandai 'tidak ada obat rumah' tetapi memuat "
                    "baris obat. Hapus salah satunya."
                ) % rec.name)

    @api.constrains("encounter_id", "moment", "state")
    def _check_one_admission_and_discharge_per_encounter(self):
        """Admisi dan pemulangan terjadi sekali; transfer bisa berkali-kali."""
        for rec in self:
            if rec.moment not in ("admission", "discharge") or rec.state == "cancelled":
                continue
            twin = self.search_count([
                ("id", "!=", rec.id),
                ("encounter_id", "=", rec.encounter_id.id),
                ("moment", "=", rec.moment),
                ("state", "!=", "cancelled"),
            ])
            if twin:
                raise ValidationError(_(
                    "Kunjungan ini sudah memiliki rekonsiliasi %s. Gunakan "
                    "rekonsiliasi yang ada, atau batalkan yang lama lebih dulu."
                ) % dict(self._fields["moment"].selection).get(rec.moment))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("Baru"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "hms.medication.reconciliation"
                ) or "/"
        return super().create(vals_list)

    # --- workflow ---------------------------------------------------------
    def action_start(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Rekonsiliasi %s sudah dikerjakan.") % rec.name)
            rec.state = "in_progress"
        return True

    def action_complete(self):
        """Gerbangnya ada di sini: tiap baris harus punya keputusan beralasan."""
        for rec in self:
            if rec.state not in ("draft", "in_progress"):
                raise UserError(_("Rekonsiliasi %s sudah selesai atau dibatalkan.") % rec.name)
            if not rec.line_ids and not rec.no_home_medication:
                raise UserError(_(
                    "Rekonsiliasi %s belum memuat obat rumah apa pun. Bila pasien "
                    "memang tidak membawa obat, centang 'Tidak Ada Obat Rumah' "
                    "agar tercatat sebagai pernyataan, bukan sebagai kekosongan."
                ) % rec.name)
            undecided = rec.line_ids.filtered(lambda l: not l.decision)
            if undecided:
                raise UserError(_(
                    "Rekonsiliasi %(name)s masih memuat %(n)s obat tanpa keputusan "
                    "(lanjut/stop/ganti/tunda)."
                ) % {"name": rec.name, "n": len(undecided)})
            unreasoned = rec.line_ids.filtered(
                lambda l: l.decision in DECISIONS_NEEDING_REASON and not l.reason
            )
            if unreasoned:
                raise UserError(_(
                    "Perubahan terapi wajib beralasan. Obat berikut belum memiliki "
                    "alasan: %s."
                ) % ", ".join(unreasoned.mapped("home_medicine_name")))
            missing_substitute = rec.line_ids.filtered(
                lambda l: l.decision == "substitute" and not l.substitute_medicine_id
            )
            if missing_substitute:
                raise UserError(_(
                    "Keputusan 'ganti' harus menyebut obat penggantinya: %s."
                ) % ", ".join(missing_substitute.mapped("home_medicine_name")))
            rec.write({
                "state": "completed",
                "completed_at": fields.Datetime.now(),
                "completed_by_id": self.env.uid,
            })
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == "completed":
                raise UserError(_(
                    "Rekonsiliasi yang sudah selesai adalah bagian rekam medis; "
                    "buat rekonsiliasi baru bila keadaannya berubah."
                ))
            rec.state = "cancelled"
        return True


class HmsMedicationReconciliationLine(models.Model):
    _name = "hms.medication.reconciliation.line"
    _description = "Baris Rekonsiliasi Obat"
    _order = "reconciliation_id, sequence, id"

    reconciliation_id = fields.Many2one("hms.medication.reconciliation", required=True,
                                        ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)

    home_medicine_name = fields.Char(
        "Obat Rumah", required=True,
        help="Ditulis apa adanya seperti yang dibawa/disebut pasien, termasuk "
             "obat bebas dan jamu.",
    )
    medicine_id = fields.Many2one(
        "hms.medicine", "Padanan di Formularium RS",
        help="Opsional: obat rumah sering tidak punya padanan di RS.",
    )
    dose = fields.Char("Dosis")
    frequency = fields.Char("Frekuensi")
    route_id = fields.Many2one("hms.route", "Rute")
    last_taken = fields.Date("Terakhir Diminum")

    decision = fields.Selection(DECISIONS, string="Keputusan", index=True)
    substitute_medicine_id = fields.Many2one("hms.medicine", "Diganti Dengan")
    reason = fields.Text("Alasan")
    decided_by_id = fields.Many2one("hms.practitioner", "Diputuskan Oleh")
    is_discrepancy = fields.Boolean("Perubahan Terapi", compute="_compute_discrepancy",
                                    store=True)

    @api.depends("decision")
    def _compute_discrepancy(self):
        for line in self:
            line.is_discrepancy = bool(line.decision) and line.decision != "continue"
