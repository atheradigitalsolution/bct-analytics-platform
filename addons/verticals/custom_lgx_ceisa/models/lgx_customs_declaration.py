# -*- coding: utf-8 -*-
"""Pengiriman deklarasi ke CEISA lewat antrian, dan penarikan statusnya.

Tombol di layar TIDAK memanggil CEISA. Ia membuat satu `lgx.integration.message`
berstatus `pending` lalu mengantrikan job — dan itu seluruh perbedaan antara
sistem yang tetap responsif saat Bea Cukai lambat dan sistem yang menahan kursor
database selama jaringan menggantung.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Nomor dokumen pabean di CEISA memakai kode angka, bukan nama internal kita.
CEISA_DOC_CODES = {
    "bc20_pib": "20",
    "bc30_peb": "30",
    "bc11_manifest": "11",
    "bc23_tpb_in": "23",
    "bc25_tpb_out": "25",
    "bc16_plb_in": "16",
    "bc28_plb_out": "28",
}

# Pemetaan jalur respons CEISA ke nilai internal. Dipisahkan dari kode supaya
# istilah yang berubah di sisi mereka tidak menjadi perubahan logika di sisi kita.
CHANNEL_MAP = {"HIJAU": "green", "KUNING": "yellow", "MERAH": "red"}


class LgxCustomsDeclaration(models.Model):
    _inherit = "lgx.customs.declaration"

    ceisa_message_ids = fields.One2many(
        "lgx.integration.message", "ceisa_declaration_id", "Pesan CEISA",
        domain=[("channel", "=", "ceisa")],
    )
    ceisa_message_count = fields.Integer("Jumlah Pesan CEISA", compute="_compute_ceisa_stats")
    ceisa_last_state = fields.Selection(
        [("pending", "Menunggu kirim"), ("sent", "Terkirim"), ("acked", "Dijawab"),
         ("failed", "Gagal"), ("cancelled", "Dibatalkan")],
        string="Status Pengiriman CEISA", compute="_compute_ceisa_stats", store=True,
    )

    @api.depends("ceisa_message_ids.state")
    def _compute_ceisa_stats(self):
        for declaration in self:
            messages = declaration.ceisa_message_ids.sorted("id")
            declaration.ceisa_message_count = len(messages)
            declaration.ceisa_last_state = messages[-1].state if messages else False

    # --- pengiriman --------------------------------------------------------
    def action_send_ceisa(self):
        """Antrikan pengiriman. TIDAK memanggil CEISA dari sini."""
        Message = self.env["lgx.integration.message"]
        queued = Message.browse()
        for declaration in self:
            declaration._check_ceisa_ready()
            message = Message.create({
                "channel": "ceisa",
                "direction": "out",
                "document_model": declaration._name,
                "document_id": declaration.id,
                "ceisa_declaration_id": declaration.id,
                "state": "pending",
                "company_id": declaration.company_id.id,
            })
            declaration.with_delay(
                channel="root.lgx_ceisa",
                description=_("CEISA: kirim %s", declaration.name),
                max_retries=8,
                # identity_key membuat dua penekanan tombol menghasilkan SATU job.
                # Tanpa itu, staf yang menekan tombol dua kali karena layar terasa
                # lambat mengirim dokumen yang sama dua kali ke Bea Cukai.
                identity_key="lgx-ceisa-submit-%s-%s" % (declaration.id, message.id),
            )._job_submit_to_ceisa(message.id)
            queued |= message
            declaration.message_post(body=_(
                "Pengiriman ke CEISA 4.0 diantrikan (pesan %s). HTTP-nya terjadi di "
                "runner antrian, bukan di dalam transaksi ini.", message.name,
            ))
        return queued

    def _check_ceisa_ready(self):
        self.ensure_one()
        if not self.company_id.lgx_ceisa_enabled:
            raise UserError(_(
                "Integrasi CEISA 4.0 belum diaktifkan untuk perusahaan %s. "
                "Selama mati, deklarasi dikerjakan lewat mode manual.",
                self.company_id.display_name,
            ))
        if self.submission_mode != "ceisa":
            raise UserError(_(
                "Kantor pabean %s belum diwajibkan CEISA 4.0, jadi dokumen ini "
                "dikerjakan lewat jalur manual.\n\n"
                "Penetapan mandatory berjalan bertahap per kantor dan per layanan; "
                "mengirim ke kantor yang belum wajib hanya menghasilkan penolakan "
                "yang tidak ada artinya, dan antrian yang penuh galat permanen "
                "adalah antrian yang berhenti dibaca orang.",
                self.customs_office_id.display_name,
            ))
        if self.state == "draft":
            raise UserError(_(
                "Deklarasi %s masih draf. Ajukan lebih dulu — pemeriksaan Ahli "
                "Kepabeanan dan kelengkapan prinsipal berjalan di sana.", self.name,
            ))
        if self.doc_type not in CEISA_DOC_CODES:
            raise UserError(_(
                "Jenis dokumen %s belum punya padanan kode CEISA.", self.doc_type,
            ))
        return True

    def _ceisa_payload(self):
        """Bentuk payload. Dipisah supaya dapat diuji tanpa menyentuh jaringan.

        ⚠ Nama field mengikuti perkiraan terbaik dari dokumentasi publik dan
        belum diverifikasi ke lingkungan development sungguhan (butir A20).
        """
        self.ensure_one()
        return {
            "kodeDokumen": CEISA_DOC_CODES[self.doc_type],
            "kodeKantor": self.customs_office_id.code,
            "nomorAju": self.aju_number or None,
            "npwpPengusaha": (self.principal_npwp or "").replace(".", "").replace("-", ""),
            "nibPengusaha": self.principal_nib,
            "jenisAkses": self.customs_access_type,
            "npwpPpjk": (self.ppjk_id.vat or "") if self.ppjk_id else None,
            "nomorSertifikatAhli": self.customs_expert_id.certificate_no or None,
            "kodeValuta": self.currency_id.name,
            "ndpbm": self.fx_rate_tax,
            "nilaiPabean": self.total_cif,
            "totalBm": self.total_bm,
            "totalPpn": self.total_ppn_impor,
            "totalPpnbm": self.total_ppnbm,
            "totalPph": self.total_pph22,
            "barang": [{
                "seriBarang": index + 1,
                "posTarif": line.hs_code_id.code,
                "uraian": line.description,
                "jumlahSatuan": line.quantity,
                "kodeSatuan": line.uom_id.name or None,
                "negaraAsal": line.country_of_origin_id.code or None,
                "nilaiPabean": line.customs_value,
                "tarifBm": line.bm_rate,
                "nilaiBm": line.bm_amount,
                "nilaiPpn": line.ppn_amount,
                "nilaiPph": line.pph22_amount,
            } for index, line in enumerate(self.line_ids)],
        }

    def _job_submit_to_ceisa(self, message_id):
        """Dijalankan di runner antrian. Di SINI HTTP-nya terjadi."""
        self.ensure_one()
        message = self.env["lgx.integration.message"].browse(message_id).exists()
        if not message:
            return _("Pesan integrasi %s sudah tidak ada; pengiriman dilewati.", message_id)
        if message.state == "cancelled":
            return _("Pesan %s dibatalkan sebelum sempat dikirim.", message.name)
        client = self.env["lgx.ceisa.client"]
        body = client._call(self.company_id, "POST", "/openapi/v1/document",
                            payload=self._ceisa_payload(), message=message)
        aju = body.get("nomorAju") or body.get("aju")
        values = {}
        if aju and aju != self.aju_number:
            values["aju_number"] = aju
        if self.state == "submitted":
            values["state"] = "received"
        if values:
            self.write(values)
        self.message_post(body=_(
            "CEISA 4.0 menerima dokumen. Nomor AJU: %s.", aju or _("tidak disebutkan")))
        return _("Terkirim, AJU %s", aju)

    # --- penarikan status --------------------------------------------------
    def action_pull_ceisa_status(self):
        for declaration in self:
            declaration.with_delay(
                channel="root.lgx_ceisa",
                description=_("CEISA: tarik status %s", declaration.name),
                max_retries=5,
            )._job_pull_ceisa_status()
        return True

    def _job_pull_ceisa_status(self):
        self.ensure_one()
        if not self.aju_number:
            return _("Deklarasi %s belum punya nomor AJU; tidak ada yang ditarik.", self.name)
        message = self.env["lgx.integration.message"].create({
            "channel": "ceisa",
            "direction": "in",
            "document_model": self._name,
            "document_id": self.id,
            "ceisa_declaration_id": self.id,
            "state": "pending",
            "company_id": self.company_id.id,
        })
        body = self.env["lgx.ceisa.client"]._call(
            self.company_id, "GET", "/openapi/v1/document/%s" % self.aju_number, message=message)
        return self._apply_ceisa_status(body)

    def _apply_ceisa_status(self, body):
        """Terapkan status dari CEISA. Idempoten, dan tidak pernah mundur.

        Status yang bisa mundur adalah status yang membuat milestone job
        bergoyang maju-mundur setiap kali cron berjalan — dan pelacakan yang
        bergoyang adalah pelacakan yang berhenti dipercaya pelanggan.
        """
        self.ensure_one()
        order = ["draft", "submitted", "received", "responded", "released", "done"]
        values = {}
        registration = body.get("nomorPendaftaran")
        if registration and not self.registration_number:
            values["registration_number"] = registration
            values["registration_date"] = body.get("tanggalPendaftaran") or fields.Date.context_today(self)
        channel = CHANNEL_MAP.get((body.get("jalur") or "").upper())
        if channel and channel != self.channel:
            values["channel"] = channel
        remote_state = {
            "RECEIVED": "received", "RESPONDED": "responded",
            "RELEASED": "released", "DONE": "done",
        }.get((body.get("status") or "").upper())
        if remote_state and order.index(remote_state) > order.index(self.state):
            values["state"] = remote_state
        if not values:
            return _("Status CEISA tidak berubah untuk %s.", self.name)
        self.write(values)
        if values.get("state") == "responded":
            self.job_id.lgx_log_milestone("customs_responded", source="ceisa")
            if self.channel == "red":
                self.job_id.lgx_log_milestone("customs_red_lane", source="ceisa")
        if values.get("state") == "released":
            self.job_id.lgx_log_milestone("customs_released", source="ceisa")
        self.message_post(body=_(
            "Status ditarik dari CEISA 4.0: %s%s",
            values.get("state") or self.state,
            _(", jalur %s", self.channel) if self.channel else "",
        ))
        return _("Status diperbarui: %s", values)

    @api.model
    def _cron_pull_ceisa_status(self):
        """Tarik status untuk deklarasi yang masih berjalan.

        Job yang sudah `closed` TIDAK ikut ditarik: menarik status dokumen pada
        job yang bukunya sudah tutup hanya menghasilkan perubahan yang tidak
        boleh lagi memengaruhi apa pun.
        """
        declarations = self.search([
            ("state", "in", ("submitted", "received", "responded")),
            ("aju_number", "!=", False),
            ("submission_mode", "=", "ceisa"),
            ("company_id.lgx_ceisa_enabled", "=", True),
            ("job_id.state", "not in", ("closed", "cancelled")),
        ])
        for declaration in declarations:
            declaration.with_delay(
                channel="root.lgx_ceisa",
                description=_("CEISA: tarik status %s", declaration.name),
                max_retries=5,
                identity_key="lgx-ceisa-pull-%s-%s" % (
                    declaration.id, fields.Date.context_today(self)),
            )._job_pull_ceisa_status()
        return len(declarations)


class LgxIntegrationMessage(models.Model):
    _inherit = "lgx.integration.message"

    ceisa_declaration_id = fields.Many2one("lgx.customs.declaration", "Deklarasi CEISA",
                                           index=True, ondelete="cascade")
