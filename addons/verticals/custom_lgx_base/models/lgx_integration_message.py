# -*- coding: utf-8 -*-
"""Log pesan integrasi — satu tabel untuk CEISA, NLE, dan Coretax.

Aturan yang dijaga model ini: tidak ada panggilan HTTP sinkron dari dalam
transaksi ORM. Setiap pengiriman keluar meninggalkan satu baris di sini dengan
payload mentah dan responsnya, sehingga "sudah dikirim atau belum" adalah
pertanyaan yang bisa dijawab data, bukan tebakan dari log aplikasi.

Payload disimpan mentah dengan sengaja. Saat Bea Cukai menolak sebuah PIB tiga
minggu kemudian, yang dibutuhkan adalah byte yang benar-benar dikirim, bukan
rekonstruksi dari record yang sejak itu sudah berubah.
"""
from odoo import _, api, fields, models


class LgxIntegrationMessage(models.Model):
    _name = "lgx.integration.message"
    _description = "Pesan Integrasi Eksternal"
    _order = "create_date desc, id desc"

    name = fields.Char("Referensi", compute="_compute_name", store=True)
    channel = fields.Selection(
        [("ceisa", "CEISA 4.0"), ("nle", "NLE / INSW"), ("coretax", "Coretax DJP"), ("other", "Lainnya")],
        string="Kanal", required=True, index=True,
    )
    direction = fields.Selection(
        [("out", "Keluar"), ("in", "Masuk")], string="Arah", required=True, default="out",
    )
    document_model = fields.Char("Model Dokumen", index=True)
    document_id = fields.Integer("ID Dokumen", index=True)
    endpoint = fields.Char("Endpoint")
    request_payload = fields.Text("Payload Permintaan")
    response_payload = fields.Text("Payload Respons")
    http_status = fields.Integer("HTTP Status")
    state = fields.Selection(
        [
            ("pending", "Menunggu kirim"),
            ("sent", "Terkirim"),
            ("acked", "Dijawab"),
            ("failed", "Gagal"),
            ("cancelled", "Dibatalkan"),
        ],
        string="Status", required=True, default="pending", index=True,
    )
    attempt_count = fields.Integer("Percobaan", default=0)
    next_retry_at = fields.Datetime("Coba Lagi Pada", index=True)
    error_message = fields.Text("Pesan Galat")
    company_id = fields.Many2one("res.company", "Perusahaan", default=lambda s: s.env.company)

    @api.depends("channel", "document_model", "document_id")
    def _compute_name(self):
        for rec in self:
            rec.name = "%s/%s/%s" % (
                (rec.channel or "?").upper(),
                rec.document_model or "-",
                rec.document_id or 0,
            )

    def action_retry(self):
        """Kembalikan pesan gagal ke antrian.

        Tidak mengirim apa pun sendiri: pengiriman adalah pekerjaan modul kanal
        (custom_lgx_ceisa / custom_lgx_nle) lewat queue_job. Model ini hanya
        memegang keadaan.
        """
        for rec in self:
            if rec.state not in ("failed", "cancelled"):
                continue
            rec.write({"state": "pending", "next_retry_at": fields.Datetime.now(), "error_message": False})
        return True

    def log_attempt(self, payload=None, response=None, status=None, error=None):
        """Catat satu percobaan. Dipanggil modul kanal, bukan dari UI."""
        self.ensure_one()
        vals = {"attempt_count": self.attempt_count + 1}
        if payload is not None:
            vals["request_payload"] = payload
        if response is not None:
            vals["response_payload"] = response
        if status is not None:
            vals["http_status"] = status
        if error:
            vals["error_message"] = error
            vals["state"] = "failed"
        elif status and 200 <= status < 300:
            vals["state"] = "acked"
        self.write(vals)
        return self
