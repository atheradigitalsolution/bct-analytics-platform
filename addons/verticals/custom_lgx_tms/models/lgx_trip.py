# -*- coding: utf-8 -*-
"""Trip: penugasan, muatan legal, dan POD yang menahan status.

TIGA ATURAN YANG MENAHAN UANG
-----------------------------
1. **Bentrok jadwal.** Kendaraan yang sudah ditugaskan pada trip lain dengan
   jadwal bertumpuk tidak boleh dipilih. Dicek di ORM dan bukan hanya lewat
   domain di layar, karena penugasan juga datang dari API dispatch.
2. **ODOL.** Muatan diuji terhadap JBI kendaraan. Sebelum tanggal penegakan ia
   peringatan yang dapat dilewati DENGAN ALASAN TERCATAT; sejak tanggal itu ia
   penolakan. Kendaraan tanpa data JBI dinyatakan tidak dapat divalidasi — bukan
   diluluskan diam-diam.
3. **POD.** Trip tidak dapat masuk `delivered` selama ada stop `dropoff` tanpa
   bukti terima. Di trucking, POD yang hilang adalah pendapatan yang hilang;
   2–5% pendapatan lazim menguap hanya karena POD kertas tidak kembali ke kantor.
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LgxTrip(models.Model):
    _name = "lgx.trip"
    _description = "Trip Angkutan Darat"
    _order = "planned_start desc, id desc"
    _inherit = ["lgx.numbering.mixin", "mail.thread", "mail.activity.mixin"]
    _lgx_sequence_code = "lgx.trip"

    job_id = fields.Many2one("lgx.job", "Job", ondelete="set null", index=True, tracking=True,
                             help="Opsional: trip internal atau reposisi armada tidak punya job.")
    company_id = fields.Many2one("res.company", "Perusahaan", required=True,
                                 default=lambda s: s.env.company, index=True)
    operating_unit_id = fields.Many2one("operating.unit", "Cabang")
    currency_id = fields.Many2one("res.currency", "Mata Uang", required=True,
                                  default=lambda s: s.env.company.currency_id)
    trip_type = fields.Selection(
        [("ftl", "FTL"), ("ltl", "LTL"), ("container_haulage", "Haulage Kontainer"),
         ("distribution", "Distribusi"), ("shuttle", "Shuttle"), ("repositioning", "Reposisi")],
        string="Jenis Trip", required=True, default="ftl", tracking=True,
    )

    vehicle_id = fields.Many2one("fleet.vehicle", "Kendaraan", tracking=True, index=True,
                                 domain="[('lgx_is_freight','=',True)]")
    trailer_id = fields.Many2one("fleet.vehicle", "Trailer / Chassis")
    driver_id = fields.Many2one("lgx.driver", "Pengemudi", tracking=True, index=True)
    helper_ids = fields.Many2many("lgx.driver", "lgx_trip_helper_rel", "trip_id", "driver_id",
                                  string="Kernet / Pendamping")

    route_id = fields.Many2one("lgx.route", "Rute")
    origin_location_id = fields.Many2one("lgx.location", "Asal")
    destination_location_id = fields.Many2one("lgx.location", "Tujuan")
    stop_ids = fields.One2many("lgx.trip.stop", "trip_id", "Stop")
    stop_count = fields.Integer("Jumlah Stop", compute="_compute_stop_stats", store=True)
    pod_complete = fields.Boolean("POD Lengkap", compute="_compute_stop_stats", store=True)
    pod_missing_count = fields.Integer("Stop Tanpa POD", compute="_compute_stop_stats", store=True)

    # Nomor kontainer sebagai Char, BUKAN Many2one ke lgx.container.
    #
    # custom_lgx_tms sengaja tidak bergantung pada custom_lgx_ff: klien trucking
    # murni tidak boleh dipaksa memasang seluruh lapisan forwarding hanya untuk
    # mengelola trip. Many2one ke model milik modul yang tidak menjadi dependency
    # kebetulan bekerja selama keduanya terpasang, lalu gagal saat salah satunya
    # di-upgrade sendirian — dan itu ketahuan pertama kali di produksi.
    #
    # Tautan sesungguhnya ke lgx.container hidup di jembatan custom_lgx_tms_ff.
    container_no = fields.Char("Nomor Kontainer",
                               help="Diisi untuk haulage kontainer.")
    container_type_id = fields.Many2one("lgx.container.type", "Tipe Kontainer")
    cargo_weight_kg = fields.Float("Berat Muatan (kg)", tracking=True)
    cargo_volume_cbm = fields.Float("Volume Muatan (CBM)")
    package_count = fields.Integer("Jumlah Koli")
    commodity_id = fields.Many2one("lgx.commodity", "Komoditas")

    odol_status = fields.Selection(
        [("ok", "Dalam Batas"), ("unknown", "Tidak Dapat Divalidasi"),
         ("warning", "Melebihi JBI — peringatan"), ("blocked", "Melebihi JBI — ditolak")],
        string="Status ODOL", compute="_compute_odol", store=True,
    )
    odol_message = fields.Char("Keterangan ODOL", compute="_compute_odol", store=True)
    odol_override_reason = fields.Char(
        "Alasan Melanjutkan Meski Melebihi",
        help="Wajib diisi untuk melanjutkan selama masa peringatan. Sejak tanggal "
             "penegakan, alasan tidak lagi cukup.",
    )

    planned_start = fields.Datetime("Rencana Berangkat", tracking=True)
    planned_end = fields.Datetime("Rencana Kembali")
    actual_start = fields.Datetime("Aktual Berangkat", tracking=True)
    actual_end = fields.Datetime("Aktual Kembali", tracking=True)
    duration_hours = fields.Float("Durasi (jam)", compute="_compute_duration", store=True)

    odometer_start = fields.Float("Odometer Awal")
    odometer_end = fields.Float("Odometer Akhir")
    distance_km = fields.Float("Jarak Tempuh (km)", compute="_compute_distance", store=True,
                               readonly=False)
    laden_km = fields.Float("Km Bermuatan")
    empty_km = fields.Float("Km Kosong", compute="_compute_distance", store=True)

    advance_id = fields.Many2one("lgx.trip.advance", "Uang Jalan", copy=False)
    advance_state = fields.Selection(related="advance_id.state", string="Status Uang Jalan",
                                     store=True)
    expense_ids = fields.One2many("lgx.trip.expense", "trip_id", "Biaya Perjalanan")
    expense_total = fields.Monetary("Total Biaya", compute="_compute_expense_total", store=True)

    state = fields.Selection(
        [("draft", "Draf"), ("assigned", "Ditugaskan"), ("dispatched", "Berangkat"),
         ("in_transit", "Dalam Perjalanan"), ("delivered", "Terkirim"),
         ("settled", "Dipertanggungjawabkan"), ("closed", "Tutup"), ("cancelled", "Batal")],
        string="Status", default="draft", required=True, tracking=True, index=True,
    )
    note = fields.Text("Catatan")

    _odometer_order = models.Constraint(
        "check(odometer_end = 0 or odometer_start = 0 or odometer_end >= odometer_start)",
        "Odometer akhir tidak boleh lebih kecil dari odometer awal.",
    )
    _cargo_non_negative = models.Constraint(
        "check(cargo_weight_kg >= 0)", "Berat muatan tidak boleh negatif.",
    )

    # --- computes ----------------------------------------------------------
    @api.depends("stop_ids.stop_type", "stop_ids.pod_signature", "stop_ids.pod_photo_ids",
                 "stop_ids.received_by_name")
    def _compute_stop_stats(self):
        for trip in self:
            trip.stop_count = len(trip.stop_ids)
            dropoffs = trip.stop_ids.filtered(lambda s: s.stop_type == "dropoff")
            missing = dropoffs.filtered(lambda s: not s.has_pod)
            trip.pod_missing_count = len(missing)
            trip.pod_complete = bool(dropoffs) and not missing

    @api.depends("cargo_weight_kg", "vehicle_id", "vehicle_id.lgx_jbi_kg",
                 "vehicle_id.lgx_kerb_weight_kg", "planned_start")
    def _compute_odol(self):
        for trip in self:
            if not trip.vehicle_id:
                trip.odol_status = "unknown"
                trip.odol_message = _("Kendaraan belum ditugaskan.")
                continue
            on_date = (trip.planned_start.date() if trip.planned_start
                       else fields.Date.context_today(trip))
            status, message = trip.vehicle_id.lgx_check_load(trip.cargo_weight_kg, on_date)
            trip.odol_status = status
            trip.odol_message = message or _("Muatan dalam batas JBI.")

    @api.depends("actual_start", "actual_end")
    def _compute_duration(self):
        for trip in self:
            if trip.actual_start and trip.actual_end:
                trip.duration_hours = (trip.actual_end - trip.actual_start).total_seconds() / 3600.0
            else:
                trip.duration_hours = 0.0

    @api.depends("odometer_start", "odometer_end", "laden_km")
    def _compute_distance(self):
        for trip in self:
            if trip.odometer_end and trip.odometer_start:
                trip.distance_km = trip.odometer_end - trip.odometer_start
            trip.empty_km = max(0.0, (trip.distance_km or 0.0) - (trip.laden_km or 0.0))

    @api.depends("expense_ids.amount")
    def _compute_expense_total(self):
        for trip in self:
            trip.expense_total = sum(trip.expense_ids.mapped("amount"))

    # --- validasi ----------------------------------------------------------
    def _check_vehicle_conflict(self):
        """Kendaraan tidak boleh ditugaskan pada dua trip dengan jadwal bertumpuk."""
        for trip in self:
            if not trip.vehicle_id or not trip.planned_start:
                continue
            end = trip.planned_end or trip.planned_start
            conflicts = self.search([
                ("id", "!=", trip.id),
                ("vehicle_id", "=", trip.vehicle_id.id),
                ("state", "not in", ("cancelled", "closed")),
                ("planned_start", "<=", end),
                ("planned_end", ">=", trip.planned_start),
            ])
            if conflicts:
                raise ValidationError(_(
                    "Kendaraan %s sudah ditugaskan pada trip %s dengan jadwal yang bertumpuk.",
                    trip.vehicle_id.display_name, ", ".join(conflicts.mapped("name")),
                ))

    def _check_driver_eligible(self):
        """SIM mati menolak penugasan; KIR mati memperingatkan (dapat dikonfigurasi memblokir)."""
        params = self.env["ir.config_parameter"].sudo()
        block_on_kir = params.get_param("lgx.block_dispatch_on_expired_kir", "0") == "1"
        for trip in self:
            driver = trip.driver_id
            if driver and driver.sim_is_expired:
                raise ValidationError(_(
                    "SIM pengemudi %s sudah lewat masa berlaku pada %s. Penugasan ditolak.",
                    driver.name, driver.sim_expiry_date,
                ))
            vehicle = trip.vehicle_id
            if vehicle and vehicle.lgx_document_status == "expired":
                message = _(
                    "Kendaraan %s memiliki dokumen yang sudah mati: %s.",
                    vehicle.display_name, vehicle.lgx_document_issue,
                )
                if block_on_kir:
                    raise ValidationError(message)
                trip.message_post(body=message)

    def _check_odol(self):
        for trip in self:
            if trip.odol_status == "blocked":
                raise UserError(_(
                    "%s\n\nPenegakan Zero ODOL sudah berlaku sejak %s, jadi penugasan "
                    "ditolak. Tanggal penegakan adalah parameter sistem "
                    "'lgx.odol_enforcement_date'.",
                    trip.odol_message, trip.vehicle_id.lgx_odol_enforcement_date(),
                ))
            if trip.odol_status == "warning" and not trip.odol_override_reason:
                raise UserError(_(
                    "%s\n\nSelama masa peringatan, melanjutkan menuntut alasan tercatat. "
                    "Isi 'Alasan Melanjutkan Meski Melebihi' pada trip ini.",
                    trip.odol_message,
                ))
            if trip.odol_status == "unknown" and trip.vehicle_id:
                trip.message_post(body=_(
                    "Muatan tidak dapat divalidasi terhadap kapasitas legal: %s", trip.odol_message))

    # --- alur --------------------------------------------------------------
    def action_assign(self):
        for trip in self:
            if trip.state not in ("draft", "assigned"):
                raise UserError(_("Trip %s sudah melewati tahap penugasan.", trip.name))
            if not trip.vehicle_id or not trip.driver_id:
                raise UserError(_(
                    "Trip %s harus menunjuk kendaraan dan pengemudi sebelum ditugaskan.", trip.name))
            trip._check_vehicle_conflict()
            trip._check_driver_eligible()
            trip._check_odol()
            trip.state = "assigned"
            if trip.job_id:
                trip.job_id.lgx_log_milestone("trip_assigned", source="manual")
        return True

    def action_dispatch(self):
        for trip in self:
            if trip.state != "assigned":
                raise UserError(_("Trip %s belum ditugaskan.", trip.name))
            trip._check_odol()
            trip.write({
                "state": "dispatched",
                "actual_start": trip.actual_start or fields.Datetime.now(),
            })
            if trip.job_id:
                trip.job_id.lgx_log_milestone("trip_dispatched", source="manual")
        return True

    def action_in_transit(self):
        self.filtered(lambda t: t.state == "dispatched").write({"state": "in_transit"})
        return True

    def action_deliver(self):
        """POD adalah syarat, bukan pengingat."""
        for trip in self:
            if trip.state not in ("dispatched", "in_transit"):
                raise UserError(_("Trip %s belum berangkat.", trip.name))
            missing = trip.stop_ids.filtered(
                lambda s: s.stop_type == "dropoff" and not s.has_pod)
            if missing:
                raise UserError(_(
                    "Trip %s tidak dapat dinyatakan terkirim: %s stop bongkar belum "
                    "punya POD (%s).\n\n"
                    "POD adalah satu-satunya dasar penagihan di trucking; tanpa itu "
                    "pekerjaan ini tidak dapat ditagihkan.",
                    trip.name, len(missing),
                    ", ".join(missing.mapped("partner_id.display_name") or [_("tanpa nama")]),
                ))
            trip.write({"state": "delivered", "actual_end": trip.actual_end or fields.Datetime.now()})
            if trip.job_id:
                trip.job_id.lgx_log_milestone("pod_captured", source="manual")
                trip.job_id.lgx_log_milestone("delivered", source="manual")
        return True

    def action_settle(self):
        for trip in self:
            if trip.state != "delivered":
                raise UserError(_("Trip %s belum terkirim.", trip.name))
            if trip.advance_id and trip.advance_id.state != "settled":
                raise UserError(_(
                    "Uang jalan trip %s belum dipertanggungjawabkan (status: %s). "
                    "Pertanggungjawaban yang tidak pernah ditutup adalah bentuk kebocoran "
                    "yang paling sulit ditemukan belakangan.",
                    trip.name, trip.advance_id.state,
                ))
            trip.state = "settled"
            if trip.job_id:
                trip.job_id.lgx_log_milestone("advance_settled", source="manual")
        return True

    def action_close(self):
        for trip in self:
            if trip.state != "settled":
                raise UserError(_(
                    "Trip %s belum dipertanggungjawabkan.", trip.name))
            trip.state = "closed"
        return True

    def action_cancel(self):
        for trip in self:
            if trip.state in ("settled", "closed"):
                raise UserError(_("Trip yang sudah dipertanggungjawabkan tidak dapat dibatalkan."))
            trip.state = "cancelled"
        return True

    def action_create_advance(self):
        """Uang jalan dengan nilai yang DISARANKAN dari master rute."""
        self.ensure_one()
        if self.advance_id:
            raise UserError(_("Trip %s sudah punya uang jalan.", self.name))
        if not self.driver_id:
            raise UserError(_("Tentukan pengemudi lebih dulu."))
        suggested = 0.0
        if self.route_id:
            tariffs = self.env["lgx.route.tariff"].lgx_find(
                self.route_id, self.vehicle_id.lgx_category_id,
                self.job_id.customer_id if self.job_id else None,
            )
            if tariffs:
                suggested = tariffs[0].standard_advance
        advance = self.env["lgx.trip.advance"].create({
            "trip_id": self.id,
            "driver_id": self.driver_id.id,
            "amount_requested": suggested,
            "amount_limit": suggested,
            "currency_id": self.currency_id.id,
            "company_id": self.company_id.id,
        })
        self.advance_id = advance
        return {
            "type": "ir.actions.act_window",
            "res_model": "lgx.trip.advance",
            "res_id": advance.id,
            "view_mode": "form",
        }

    @api.onchange("route_id")
    def _onchange_route(self):
        for trip in self:
            if trip.route_id:
                trip.origin_location_id = trip.route_id.origin_location_id
                trip.destination_location_id = trip.route_id.destination_location_id
                trip.distance_km = trip.route_id.distance_km

    @api.onchange("vehicle_id")
    def _onchange_vehicle(self):
        for trip in self:
            if trip.vehicle_id and trip.vehicle_id.driver_id:
                driver = self.env["lgx.driver"].search(
                    [("partner_id", "=", trip.vehicle_id.driver_id.id)], limit=1)
                if driver and not trip.driver_id:
                    trip.driver_id = driver


class LgxTripStop(models.Model):
    _name = "lgx.trip.stop"
    _description = "Stop Trip"
    _order = "trip_id, sequence, id"

    sequence = fields.Integer(default=10)
    trip_id = fields.Many2one("lgx.trip", "Trip", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="trip_id.company_id", store=True, index=True)
    stop_type = fields.Selection(
        [("pickup", "Muat"), ("dropoff", "Bongkar")], string="Jenis", required=True, default="dropoff")
    partner_id = fields.Many2one("res.partner", "Pihak")
    address = fields.Text("Alamat")
    location_id = fields.Many2one("lgx.location", "Simpul")
    planned_arrival = fields.Datetime("Rencana Tiba")
    actual_arrival = fields.Datetime("Aktual Tiba")

    qty_planned = fields.Float("Jumlah Rencana")
    qty_delivered = fields.Float("Jumlah Diterima")
    qty_rejected = fields.Float("Jumlah Ditolak")
    rejection_reason = fields.Char("Alasan Penolakan")

    pod_signature = fields.Binary("Tanda Tangan Penerima", attachment=True)
    pod_photo_ids = fields.Many2many("ir.attachment", "lgx_trip_stop_photo_rel",
                                     "stop_id", "attachment_id", string="Foto POD")
    received_by_name = fields.Char("Nama Penerima")
    received_at = fields.Datetime("Waktu Terima")
    has_pod = fields.Boolean("POD Ada", compute="_compute_has_pod", store=True)
    pod_source = fields.Selection(
        [("manual", "Unggahan Backend"), ("device", "Aplikasi Pengemudi")],
        string="Sumber POD", default="manual",
    )
    note = fields.Char("Catatan")

    _qty_non_negative = models.Constraint(
        "check(qty_planned >= 0 and qty_delivered >= 0 and qty_rejected >= 0)",
        "Jumlah pada stop tidak boleh negatif.",
    )

    @api.depends("pod_signature", "pod_photo_ids", "received_by_name")
    def _compute_has_pod(self):
        """POD dianggap ada bila ADA BUKTI dan ADA NAMA PENERIMA.

        Tanda tangan tanpa nama penerima adalah coretan; nama tanpa bukti adalah
        pernyataan. Yang menagih adalah keduanya sekaligus.
        """
        for stop in self:
            has_evidence = bool(stop.pod_signature) or bool(stop.pod_photo_ids)
            stop.has_pod = has_evidence and bool(stop.received_by_name)

    @api.constrains("qty_rejected", "rejection_reason")
    def _check_rejection_reason(self):
        for stop in self:
            if stop.qty_rejected and not stop.rejection_reason:
                raise ValidationError(_(
                    "Ada %s unit ditolak pada stop %s tanpa alasan tercatat. Penolakan "
                    "tanpa alasan tidak dapat ditagihkan maupun diklaim ke siapa pun.",
                    stop.qty_rejected, stop.partner_id.display_name or stop.address or "-",
                ))


class LgxTripExpense(models.Model):
    _name = "lgx.trip.expense"
    _description = "Biaya Perjalanan"
    _order = "trip_id, date, id"

    trip_id = fields.Many2one("lgx.trip", "Trip", required=True, ondelete="cascade", index=True)
    advance_id = fields.Many2one("lgx.trip.advance", "Uang Jalan", index=True)
    company_id = fields.Many2one(related="trip_id.company_id", store=True, index=True)
    date = fields.Date("Tanggal", default=fields.Date.context_today, required=True)
    category = fields.Selection(
        [("fuel", "BBM"), ("toll", "Tol"), ("parking", "Parkir"), ("levy", "Retribusi"),
         ("meal", "Makan"), ("lodging", "Penginapan"), ("repair", "Perbaikan Darurat"),
         ("labor", "Bongkar Muat"), ("other", "Lainnya")],
        string="Kategori", required=True, default="fuel",
    )
    description = fields.Char("Keterangan")
    amount = fields.Monetary("Jumlah", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(related="trip_id.currency_id", readonly=True)
    quantity = fields.Float("Kuantitas", help="Liter untuk BBM; dipakai menghitung rasio konsumsi.")
    proof_ids = fields.Many2many("ir.attachment", "lgx_trip_expense_proof_rel",
                                 "expense_id", "attachment_id", string="Bukti")
    needs_proof = fields.Boolean("Wajib Berbukti", compute="_compute_needs_proof", store=True)

    _amount_positive = models.Constraint("check(amount > 0)", "Jumlah biaya harus lebih dari nol.")

    @api.depends("amount")
    def _compute_needs_proof(self):
        threshold = float(self.env["ir.config_parameter"].sudo().get_param(
            "lgx.expense_proof_threshold", 100000))
        for expense in self:
            expense.needs_proof = (expense.amount or 0.0) >= threshold

    @api.constrains("amount", "proof_ids")
    def _check_proof(self):
        for expense in self:
            if expense.needs_proof and not expense.proof_ids:
                raise ValidationError(_(
                    "Biaya %s sebesar %s melewati ambang wajib bukti. Lampirkan bukti "
                    "sebelum menyimpan — ambangnya adalah parameter sistem "
                    "'lgx.expense_proof_threshold'.",
                    expense.category, expense.amount,
                ))
