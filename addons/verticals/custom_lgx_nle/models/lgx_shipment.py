# -*- coding: utf-8 -*-
"""DO Online, SP2, dan rekonsiliasi status dari Customs API."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Pemetaan status dokumen NLE ke kode milestone internal. Sebagai DATA dan bukan
# rangkaian if: istilah di sisi mereka berubah lebih sering daripada alur kita,
# dan perubahan istilah tidak boleh menjadi perubahan logika.
NLE_DOCUMENT_MILESTONES = {
    "MANIFEST": "cargo_received",
    "PIB_DITERIMA": "customs_submitted",
    "RESPON_JALUR": "customs_responded",
    "SPPB_TERBIT": "customs_released",
    "GATE_OUT": "container_picked_up",
}


class LgxShipment(models.Model):
    _inherit = "lgx.shipment"

    nle_do_id = fields.Char("ID Dokumen DO Online", readonly=True, copy=False,
                            help="UUID yang dikembalikan NLE; bukti DO benar-benar terkirim.")
    nle_do_number = fields.Char("Nomor DO Online", readonly=True, copy=False)
    nle_sp2_number = fields.Char("Nomor SP2", readonly=True, copy=False)
    nle_last_document_status = fields.Char("Status Dokumen (NLE)", readonly=True, copy=False)
    nle_last_sync = fields.Datetime("Sinkron Terakhir", readonly=True, copy=False)
    nle_message_ids = fields.One2many("lgx.integration.message", "nle_shipment_id",
                                      "Pesan NLE", domain=[("channel", "=", "nle")])
    nle_message_count = fields.Integer("Jumlah Pesan NLE", compute="_compute_nle_stats")

    @api.depends("nle_message_ids")
    def _compute_nle_stats(self):
        for shipment in self:
            shipment.nle_message_count = len(shipment.nle_message_ids)

    # --- prasyarat ---------------------------------------------------------
    def _check_nle_ready(self):
        self.ensure_one()
        company = self.company_id
        if not company.lgx_nle_enabled:
            raise UserError(_(
                "Integrasi NLE belum diaktifkan untuk perusahaan %s.", company.display_name))
        if not company.sudo().lgx_nle_id_platform:
            raise UserError(_(
                "`id_platform` belum diisi. Ia diperoleh lewat registrasi ke NLE, dan "
                "request tanpa itu ditolak dengan pesan yang tidak menyebutkan penyebabnya."
            ))
        if not self.master_doc_no and not self.house_doc_no:
            raise UserError(_(
                "Shipment %s belum punya nomor B/L. DO Online dikunci pada nomor B/L; "
                "tanpa itu tidak ada yang dapat dicocokkan di sisi pelayaran.", self.name,
            ))
        return True

    # --- DO Online ---------------------------------------------------------
    def action_request_do_online(self):
        """Antrikan permintaan DO Online. HTTP-nya di runner, bukan di sini."""
        Message = self.env["lgx.integration.message"]
        for shipment in self:
            shipment._check_nle_ready()
            if shipment.nle_do_id:
                raise UserError(_(
                    "DO Online untuk shipment %s sudah terbit (%s). Meminta ulang akan "
                    "menghasilkan DO kedua untuk B/L yang sama.",
                    shipment.name, shipment.nle_do_number or shipment.nle_do_id,
                ))
            message = Message.create({
                "channel": "nle", "direction": "out",
                "document_model": shipment._name, "document_id": shipment.id,
                "nle_shipment_id": shipment.id,
                "state": "pending", "company_id": shipment.company_id.id,
            })
            shipment.with_delay(
                channel="root.lgx_nle",
                description=_("NLE: DO Online %s", shipment.name),
                max_retries=6,
                identity_key="lgx-nle-do-%s" % shipment.id,
            )._job_request_do_online(message.id)
        return True

    def _do_payload(self):
        self.ensure_one()
        company = self.company_id.sudo()
        containers = self.container_ids
        return {
            "shipping_name": self.carrier_id.name or "",
            "forwarder_name": company.name,
            "bl_no": self.master_doc_no or self.house_doc_no,
            "do_number": self.nle_do_number or "",
            "npwp_cargo_owner": (self.job_id.customer_id.vat or "").replace(".", "").replace("-", ""),
            "id_platform": company.lgx_nle_id_platform,
            "container": [{
                "container_no": container.container_no,
                "size": container.container_type_id.size_ft,
                "type": container.container_type_id.code,
                "seal_no": container.seal_no or "",
            } for container in containers],
        }

    def _job_request_do_online(self, message_id):
        self.ensure_one()
        message = self.env["lgx.integration.message"].browse(message_id).exists()
        if not message or message.state == "cancelled":
            return _("Pesan %s tidak lagi perlu dikirim.", message_id)
        body = self.env["lgx.nle.client"]._call(
            self.company_id, "POST", "/V1/NLE/document_do/final",
            payload=self._do_payload(), message=message)
        self.write({
            "nle_do_id": body.get("id_document"),
            "nle_do_number": body.get("do_number") or self.nle_do_number,
        })
        if self.job_id:
            self.job_id.lgx_log_milestone("do_issued", source="nle")
        self.message_post(body=_("DO Online terbit lewat NLE: %s (id %s).",
                                 self.nle_do_number or "-", self.nle_do_id))
        return _("DO Online %s", self.nle_do_number)

    # --- SP2 ---------------------------------------------------------------
    def action_request_sp2(self):
        Message = self.env["lgx.integration.message"]
        for shipment in self:
            shipment._check_nle_ready()
            if not shipment.container_ids:
                raise UserError(_(
                    "SP2 adalah surat penyerahan PETIKEMAS; shipment %s belum punya "
                    "satu pun kontainer.", shipment.name,
                ))
            message = Message.create({
                "channel": "nle", "direction": "out",
                "document_model": shipment._name, "document_id": shipment.id,
                "nle_shipment_id": shipment.id,
                "state": "pending", "company_id": shipment.company_id.id,
            })
            shipment.with_delay(
                channel="root.lgx_nle",
                description=_("NLE: SP2 %s", shipment.name),
                max_retries=6,
                identity_key="lgx-nle-sp2-%s" % shipment.id,
            )._job_request_sp2(message.id)
        return True

    def _job_request_sp2(self, message_id):
        self.ensure_one()
        message = self.env["lgx.integration.message"].browse(message_id).exists()
        if not message or message.state == "cancelled":
            return _("Pesan %s tidak lagi perlu dikirim.", message_id)
        body = self.env["lgx.nle.client"]._call(
            self.company_id, "POST", "/V1/NLE/sp2",
            payload={
                "bl_no": self.master_doc_no or self.house_doc_no,
                "container_no": self.container_ids[0].container_no,
                "id_platform": self.company_id.sudo().lgx_nle_id_platform,
            },
            message=message)
        self.nle_sp2_number = body.get("sp2_number")
        self.message_post(body=_("SP2 terbit lewat NLE: %s.", self.nle_sp2_number or "-"))
        return _("SP2 %s", self.nle_sp2_number)

    # --- Customs API: rekonsiliasi status ----------------------------------
    def action_pull_nle_status(self):
        for shipment in self:
            shipment.with_delay(
                channel="root.lgx_nle",
                description=_("NLE: tarik status %s", shipment.name),
                max_retries=5,
            )._job_pull_nle_status()
        return True

    def _job_pull_nle_status(self):
        self.ensure_one()
        reference = self.master_doc_no or self.house_doc_no
        if not reference:
            return _("Shipment %s belum punya nomor B/L.", self.name)
        message = self.env["lgx.integration.message"].create({
            "channel": "nle", "direction": "in",
            "document_model": self._name, "document_id": self.id,
            "nle_shipment_id": self.id,
            "state": "pending", "company_id": self.company_id.id,
        })
        body = self.env["lgx.nle.client"]._call(
            self.company_id, "GET", "/V1/NLE/customs/status",
            params={"bl_no": reference}, message=message)
        return self._apply_nle_status(body)

    def _apply_nle_status(self, body):
        """Terapkan status dari NLE. Idempoten; milestone tidak digandakan.

        `lgx_log_milestone` memperbarui baris yang sudah ada alih-alih membuat
        baris kedua, jadi cron dua-jam-sekali tidak menghasilkan dua puluh
        milestone yang sama dalam sehari.
        """
        self.ensure_one()
        document_status = (body.get("document_status") or "").upper()
        updated = []
        if document_status and document_status != self.nle_last_document_status:
            milestone_code = NLE_DOCUMENT_MILESTONES.get(document_status)
            if milestone_code and self.job_id:
                self.job_id.lgx_log_milestone(milestone_code, source="nle")
                updated.append(milestone_code)
            self.nle_last_document_status = document_status

        # Status kontainer dari NLE mengisi TANGGAL GERBANG, dan itulah yang
        # membuat perhitungan detensi berhenti bergantung pada staf yang ingat
        # mengetiknya. Hanya mengisi yang masih kosong: angka yang sudah
        # diketik orang tidak boleh ditimpa oleh tebakan dari luar.
        today = fields.Date.context_today(self)
        for remote in body.get("container") or []:
            container = self.container_ids.filtered(
                lambda c: c.container_no == (remote.get("container_no") or "").upper())
            if not container:
                continue
            if remote.get("status") == "GATE_OUT" and not container.gate_out_date:
                container.gate_out_date = today
                updated.append("gate_out:%s" % container.container_no)

        self.nle_last_sync = fields.Datetime.now()
        if updated:
            self.message_post(body=_(
                "Status ditarik dari NLE: %s.", ", ".join(updated)))
        return _("Status NLE: %s", document_status or _("tidak berubah"))

    @api.model
    def _cron_pull_nle_status(self):
        shipments = self.search([
            ("state", "in", ("booked", "in_transit", "arrived", "released")),
            ("company_id.lgx_nle_enabled", "=", True),
            ("job_id.state", "not in", ("closed", "closed_provisioned", "cancelled")),
            "|", ("master_doc_no", "!=", False), ("house_doc_no", "!=", False),
        ])
        for shipment in shipments:
            shipment.with_delay(
                channel="root.lgx_nle",
                description=_("NLE: tarik status %s", shipment.name),
                max_retries=5,
                identity_key="lgx-nle-pull-%s-%s" % (shipment.id, fields.Date.context_today(self)),
            )._job_pull_nle_status()
        return len(shipments)


class LgxIntegrationMessage(models.Model):
    _inherit = "lgx.integration.message"

    nle_shipment_id = fields.Many2one("lgx.shipment", "Shipment NLE", index=True,
                                      ondelete="cascade")
