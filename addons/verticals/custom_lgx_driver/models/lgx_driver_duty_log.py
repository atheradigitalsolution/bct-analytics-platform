# -*- coding: utf-8 -*-
"""Log jam kerja pengemudi, dihitung dari waktu AKTUAL trip.

Bukan dari jadwal. Jadwal adalah niat; yang diperiksa pengawas adalah apa yang
benar-benar terjadi, dan satu-satunya sumber itu di sistem ini adalah
``actual_start`` dan ``actual_end`` trip.

⚠ Keempat ambang berasal dari sumber SEKUNDER dan belum dibaca langsung dari
Pasal 90 dan 92 UU 22/2009 (butir A12c). Karena itu semuanya parameter sistem:
ketika angka aslinya dikonfirmasi, tidak ada kode yang perlu berubah.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LgxDriverDutyLog(models.Model):
    _name = "lgx.driver.duty.log"
    _description = "Log Jam Kerja Pengemudi"
    _order = "date desc, driver_id"
    # activity.mixin dibutuhkan karena log yang butuh pembenaran menempel pada
    # seseorang lewat aktivitas terjadwal; daftar di layar yang tidak menempel
    # pada siapa pun adalah daftar yang tidak dibaca siapa pun.
    _inherit = ["mail.thread", "mail.activity.mixin"]

    driver_id = fields.Many2one("lgx.driver", "Pengemudi", required=True, index=True,
                                ondelete="cascade")
    company_id = fields.Many2one(related="driver_id.company_id", store=True, index=True)
    date = fields.Date("Tanggal", required=True, index=True)
    trip_ids = fields.Many2many("lgx.trip", "lgx_duty_log_trip_rel", "log_id", "trip_id",
                                string="Trip Terkait")

    driving_minutes = fields.Integer("Menit Mengemudi")
    rest_minutes = fields.Integer("Menit Istirahat")
    working_minutes = fields.Integer("Menit Kerja")
    max_continuous_driving_minutes = fields.Integer("Mengemudi Berturut Terpanjang (menit)")

    violation_4h_rest = fields.Boolean("Langgar Istirahat 4 Jam", compute="_compute_violations",
                                       store=True)
    violation_8h_daily = fields.Boolean("Langgar 8 Jam Sehari", compute="_compute_violations",
                                        store=True)
    violation_12h_absolute = fields.Boolean("Langgar 12 Jam Mutlak", compute="_compute_violations",
                                            store=True)
    has_violation = fields.Boolean("Ada Pelanggaran", compute="_compute_violations", store=True)
    violation_summary = fields.Char("Ringkasan", compute="_compute_violations", store=True)

    justification = fields.Text("Alasan Perpanjangan")
    approved_by_id = fields.Many2one("res.users", "Disetujui Oleh")
    approved_at = fields.Datetime("Waktu Persetujuan")

    _driver_date_uniq = models.Constraint(
        "unique(driver_id, date)", "Log jam kerja pengemudi ini untuk tanggal tersebut sudah ada.",
    )
    _minutes_non_negative = models.Constraint(
        "check(driving_minutes >= 0 and rest_minutes >= 0 and working_minutes >= 0)",
        "Menit pada log jam kerja tidak boleh negatif.",
    )

    def _thresholds(self):
        params = self.env["ir.config_parameter"].sudo()
        return {
            "continuous": int(params.get_param("lgx.duty_max_continuous_driving_minutes", 240)),
            "rest": int(params.get_param("lgx.duty_required_rest_minutes", 30)),
            "daily": int(params.get_param("lgx.duty_max_daily_working_minutes", 480)),
            "absolute": int(params.get_param("lgx.duty_absolute_max_working_minutes", 720)),
        }

    @api.depends("driving_minutes", "rest_minutes", "working_minutes",
                 "max_continuous_driving_minutes")
    def _compute_violations(self):
        thresholds = self._thresholds()
        for log in self:
            log.violation_4h_rest = (
                log.max_continuous_driving_minutes > thresholds["continuous"]
                and log.rest_minutes < thresholds["rest"]
            )
            log.violation_8h_daily = log.working_minutes > thresholds["daily"]
            log.violation_12h_absolute = log.working_minutes > thresholds["absolute"]
            flags = []
            if log.violation_4h_rest:
                flags.append(_("mengemudi >%s menit tanpa istirahat %s menit",
                               thresholds["continuous"], thresholds["rest"]))
            if log.violation_12h_absolute:
                flags.append(_("kerja >%s menit (batas mutlak)", thresholds["absolute"]))
            elif log.violation_8h_daily:
                flags.append(_("kerja >%s menit", thresholds["daily"]))
            log.has_violation = bool(flags)
            log.violation_summary = "; ".join(flags) or False

    needs_justification = fields.Boolean(
        "Butuh Pembenaran", compute="_compute_needs_justification", store=True,
        help="Jam kerja melewati batas harian tetapi belum punya alasan dan penyetuju.",
    )

    @api.depends("violation_8h_daily", "justification", "approved_by_id")
    def _compute_needs_justification(self):
        """Ditandai, BUKAN ditolak.

        Godaan awalnya adalah membuat ini constraint yang menolak penyimpanan.
        Itu salah arah: log ini merekam apa yang SUDAH terjadi. Menolak
        menyimpannya berarti pelanggaran yang sebenarnya terjadi tidak tercatat
        di mana pun — persis kebalikan dari jejak audit yang Pasal 92 membuat
        perusahaan membutuhkannya.

        Jadi pelanggaran selalu tersimpan, dan yang ditagih adalah alasannya.
        """
        for log in self:
            log.needs_justification = bool(
                log.violation_8h_daily and not (log.justification and log.approved_by_id)
            )

    def action_approve_extension(self):
        for log in self:
            if not log.justification:
                raise UserError(_("Isi alasan perpanjangan lebih dulu."))
            log.write({
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
            })
        return True

    @api.model
    def _cron_build_duty_logs(self, for_date=None):
        """Bangun log dari trip yang selesai kemarin.

        Idempoten per (pengemudi, tanggal): menjalankan ulang untuk tanggal yang
        sama memperbarui baris yang ada, tidak menggandakannya.
        """
        target = for_date or fields.Date.subtract(fields.Date.context_today(self), days=1)
        Trip = self.env["lgx.trip"]
        start = fields.Datetime.to_datetime("%s 00:00:00" % target)
        end = fields.Datetime.to_datetime("%s 23:59:59" % target)
        trips = Trip.search([
            ("actual_start", ">=", start),
            ("actual_start", "<=", end),
            ("driver_id", "!=", False),
            ("state", "not in", ("cancelled",)),
        ])
        built = 0
        for driver in trips.mapped("driver_id"):
            driver_trips = trips.filtered(lambda t: t.driver_id == driver).sorted("actual_start")
            driving = 0
            longest = 0
            for trip in driver_trips:
                if trip.actual_start and trip.actual_end:
                    minutes = int((trip.actual_end - trip.actual_start).total_seconds() / 60)
                    driving += minutes
                    longest = max(longest, minutes)
            gaps = []
            previous_end = None
            for trip in driver_trips:
                if previous_end and trip.actual_start and trip.actual_start > previous_end:
                    gaps.append(int((trip.actual_start - previous_end).total_seconds() / 60))
                previous_end = trip.actual_end or previous_end
            rest = sum(gaps)
            log = self.search([("driver_id", "=", driver.id), ("date", "=", target)], limit=1)
            vals = {
                "driving_minutes": driving,
                "rest_minutes": rest,
                "working_minutes": driving + rest,
                "max_continuous_driving_minutes": longest,
                "trip_ids": [(6, 0, driver_trips.ids)],
            }
            if log:
                # Jangan menimpa alasan dan persetujuan yang sudah tercatat.
                log.write(vals)
            else:
                vals.update({"driver_id": driver.id, "date": target})
                log = self.create(vals)
            if log.needs_justification:
                responsible = driver.user_id or self.env.user
                log.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("Jam kerja %s pada %s melewati batas harian", driver.name, target),
                    note=_("%s. Perpanjangan membutuhkan alasan tercatat dan penyetuju; "
                           "sanksi Pasal 92 UU 22/2009 jatuh pada perusahaan.",
                           log.violation_summary or ""),
                    user_id=responsible.id,
                )
            built += 1
        return built
