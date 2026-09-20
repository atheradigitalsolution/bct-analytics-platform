# -*- coding: utf-8 -*-
"""Rencana kontrol pasca-pelayanan.

APA YANG PUTUS SEBELUM MODUL INI
--------------------------------
``hms.summary`` sudah punya ``followup_instruction``, ``followup_date`` dan
``followup_unit_id``. Ketiganya tetap ada dan tetap berarti sama: itulah yang
DITULIS dokter di resume, dan itulah yang tercetak untuk pasien. Yang tidak
ada adalah sisi rumah sakitnya — tidak ada satu pun baris yang bisa dijawab
oleh pertanyaan "siapa saja yang seharusnya kontrol minggu ini, dan siapa
yang tidak datang". Tanggal di dalam resume yang sudah final tidak bisa
berpindah status, tidak bisa dipasangkan ke slot, dan tidak bisa ditandai
terpenuhi.

``hms.followup.plan`` adalah sisi itu. Ia LAHIR dari resume (lihat
``HmsSummary.action_finalize`` di bawah) dan sejak itu punya hidupnya
sendiri: dijadwalkan ke slot, dipenuhi oleh kunjungan berikutnya, atau
ditandai tidak datang.

SURAT KONTROL BPJS SENGAJA DIKOSONGKAN
--------------------------------------
``bpjs_control_no`` ada sebagai tempat, tanpa format dan tanpa generator.
Nomor Surat Kontrol diterbitkan VClaim BPJS, bukan oleh rumah sakit, dan
akses VClaim-nya belum ada (gap G1/G2). Mengarang formatnya akan
menghasilkan nomor yang terlihat sah di layar, tercetak untuk pasien, lalu
ditolak di loket BPJS. Field ini diisi nanti oleh modul bridging, dari
jawaban VClaim yang sebenarnya.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

FOLLOWUP_KINDS = [
    ("control", "Kontrol Ulang"),
    ("rujuk_balik", "Rujuk Balik ke FKTP"),
    ("internal_referral", "Rujukan Internal / Konsul Poli Lain"),
]

FOLLOWUP_STATES = [
    ("planned", "Direncanakan"),
    ("scheduled", "Terjadwal"),
    ("fulfilled", "Terpenuhi"),
    ("missed", "Tidak Datang"),
    ("cancelled", "Dibatalkan"),
]


class HmsFollowupPlan(models.Model):
    _name = "hms.followup.plan"
    _description = "Rencana Kontrol"
    _inherit = ["hms.audited"]
    _order = "planned_date, id"

    encounter_id = fields.Many2one(
        "hms.encounter", "Kunjungan Asal", required=True, ondelete="cascade", index=True,
    )
    patient_id = fields.Many2one(related="encounter_id.patient_id", store=True, index=True)
    summary_id = fields.Many2one(
        "hms.summary", "Resume Sumber", ondelete="set null", index=True,
        help="Resume medis yang melahirkan rencana ini. Kosong bila rencana "
             "dibuat langsung, mis. oleh petugas pendaftaran.",
    )
    practitioner_id = fields.Many2one("hms.practitioner", "Dokter Kontrol", index=True)
    unit_id = fields.Many2one("hms.unit", "Poli Kontrol", index=True)
    planned_date = fields.Date("Tanggal Rencana", required=True, index=True)
    kind = fields.Selection(FOLLOWUP_KINDS, "Jenis", default="control", required=True, index=True)
    instruction = fields.Text("Anjuran untuk Pasien")

    slot_id = fields.Many2one(
        "hms.schedule.slot", "Slot Jadwal", ondelete="set null",
        help="Opsional. Rencana kontrol boleh berdiri tanpa slot — pasien yang "
             "diminta kontrol Senin depan belum tentu sudah memilih jamnya.",
    )
    fulfilled_encounter_id = fields.Many2one(
        "hms.encounter", "Kunjungan Pemenuhan", ondelete="set null", readonly=True,
    )
    fulfilled_at = fields.Datetime("Dipenuhi Pada", readonly=True)
    days_late = fields.Integer(
        "Selisih Hari", compute="_compute_days_late", store=True,
        help="Selisih antara tanggal rencana dan tanggal kunjungan pemenuhan. "
             "Negatif berarti pasien datang lebih awal.",
    )

    bpjs_control_no = fields.Char(
        "No. Surat Kontrol BPJS", copy=False,
        help="SENGAJA KOSONG. Nomor Surat Kontrol diterbitkan VClaim BPJS, "
             "bukan oleh rumah sakit. Akses VClaim belum tersedia di "
             "lingkungan ini (gap G1/G2), sehingga tidak ada format yang "
             "boleh dikarang di sini — nomor karangan akan ditolak di loket "
             "BPJS setelah terlanjur tercetak untuk pasien. Diisi kemudian "
             "oleh modul bridging dari jawaban VClaim yang sebenarnya.",
    )

    state = fields.Selection(
        FOLLOWUP_STATES, default="planned", required=True, index=True,
    )
    cancel_reason = fields.Char("Alasan Pembatalan")

    _plan_uniq = models.Constraint(
        "unique(summary_id, kind)",
        "Satu resume hanya melahirkan satu rencana kontrol per jenis.",
    )

    @api.depends("planned_date", "fulfilled_encounter_id.arrival_at")
    def _compute_days_late(self):
        for rec in self:
            arrival = rec.fulfilled_encounter_id.arrival_at
            if rec.planned_date and arrival:
                rec.days_late = (arrival.date() - rec.planned_date).days
            else:
                rec.days_late = 0

    @api.constrains("slot_id", "planned_date")
    def _check_slot(self):
        for rec in self:
            if rec.slot_id and rec.slot_id.date != rec.planned_date:
                raise ValidationError(
                    _("Tanggal slot (%(s)s) berbeda dari tanggal rencana kontrol (%(p)s).")
                    % {"s": rec.slot_id.date, "p": rec.planned_date}
                )

    @api.depends("patient_id", "planned_date", "kind")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s (%s)" % (
                rec.patient_id.name or "",
                rec.planned_date or "",
                dict(FOLLOWUP_KINDS).get(rec.kind, ""),
            )

    # --- state machine ----------------------------------------------------
    def action_schedule(self, slot=None):
        """Pasangkan rencana ke slot praktik yang nyata."""
        for rec in self:
            if rec.state not in ("planned", "scheduled"):
                raise UserError(
                    _("Rencana kontrol ini sudah %s.") % dict(FOLLOWUP_STATES)[rec.state]
                )
            vals = {"state": "scheduled"}
            if slot is not None:
                vals["slot_id"] = slot.id
                vals["planned_date"] = slot.date
                vals["practitioner_id"] = slot.practitioner_id.id
                vals["unit_id"] = slot.unit_id.id
            elif not rec.slot_id:
                # Terjadwal tanpa slot tetap sah: banyak poli memakai
                # nomor urut harian, bukan jam. Yang penting statusnya
                # berpindah supaya baris ini keluar dari daftar "belum
                # ditindaklanjuti".
                pass
            rec.write(vals)
        return True

    def action_fulfill(self, encounter):
        """Tandai rencana terpenuhi oleh kunjungan berikutnya."""
        for rec in self:
            if rec.state in ("fulfilled", "cancelled"):
                raise UserError(_("Rencana kontrol ini sudah ditutup."))
            if encounter.patient_id != rec.patient_id:
                raise UserError(
                    _("Kunjungan pemenuhan harus milik pasien yang sama.")
                )
            rec.write({
                "state": "fulfilled",
                "fulfilled_encounter_id": encounter.id,
                "fulfilled_at": fields.Datetime.now(),
            })
        return True

    def action_mark_missed(self):
        for rec in self:
            if rec.state not in ("planned", "scheduled"):
                raise UserError(
                    _("Hanya rencana yang belum terpenuhi yang dapat ditandai tidak datang.")
                )
            rec.write({"state": "missed"})
        return True

    def action_cancel(self, reason=None):
        for rec in self:
            if rec.state == "fulfilled":
                raise UserError(
                    _("Rencana kontrol yang sudah terpenuhi tidak dapat dibatalkan.")
                )
            rec.write({"state": "cancelled", "cancel_reason": reason or rec.cancel_reason})
        return True

    @api.model
    def _cron_mark_missed(self, limit=1000):
        """Tandai rencana yang lewat tenggat sebagai tidak datang.

        Tenggatnya parameter rumah sakit (``hms.settings``), bukan angka di
        dalam kode: poli yang memanggil pasien per gelombang mingguan punya
        toleransi berbeda dari poli dengan slot per jam.
        """
        settings = self.env["hms.settings"].get_settings()
        grace = settings.followup_missed_grace_days or 0
        if grace <= 0:
            return 0
        deadline = fields.Date.subtract(fields.Date.context_today(self), days=grace)
        stale = self.search([
            ("state", "in", ("planned", "scheduled")),
            ("planned_date", "<", deadline),
        ], limit=limit)
        if not stale:
            return 0
        stale.write({"state": "missed"})
        return len(stale)


class HmsSummary(models.Model):
    _inherit = "hms.summary"

    followup_plan_ids = fields.One2many(
        "hms.followup.plan", "summary_id", "Rencana Kontrol", readonly=True,
    )

    def action_finalize(self):
        """Resume final yang menyebut tanggal kontrol MELAHIRKAN rencananya.

        Dibuat SESUDAH super() supaya resume yang ditolak finalisasinya
        (mis. diagnosis utama kosong) tidak meninggalkan rencana kontrol
        yatim — ingat bahwa membuat record lalu melempar UserError berarti
        record itu tidak pernah tersimpan, dan kebalikannya juga berlaku:
        record yang dibuat sebelum gerbang akan ikut hilang tanpa jejak.

        ``followup_date``/``followup_instruction``/``followup_unit_id`` pada
        resume TIDAK disentuh. Rencana ini menyalin isinya, tidak
        memindahkannya: resume tetap dokumen yang berdiri sendiri, dan yang
        tercetak untuk pasien tetap berasal dari sana.
        """
        res = super().action_finalize()
        Plan = self.env["hms.followup.plan"]
        for rec in self:
            if not rec.followup_date:
                continue
            if Plan.search_count([("summary_id", "=", rec.id), ("kind", "=", "control")]):
                continue
            Plan.create({
                "encounter_id": rec.encounter_id.id,
                "summary_id": rec.id,
                "practitioner_id": rec.practitioner_id.id,
                "unit_id": rec.followup_unit_id.id or rec.encounter_id.unit_id.id,
                "planned_date": rec.followup_date,
                "kind": "control",
                "instruction": rec.followup_instruction,
            })
        return res
