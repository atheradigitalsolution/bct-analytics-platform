# -*- coding: utf-8 -*-
"""Perangkat lapangan dan kunci API-nya.

KENAPA KUNCI PER PENGGUNA, BUKAN SATU KUNCI LAYANAN
---------------------------------------------------
`auth='bearer'` pada `/json/2` menerima dua hal: API key, atau sesi yang sudah
terautentikasi DITAMBAH header `Sec-Fetch-*` yang hanya dikirim browser pada
navigasi tingkat atas. Server Node tidak bisa memakai jalur kedua tanpa memalsukan
header proteksi CSRF, dan memalsukan proteksi adalah cara mematikannya.

Jadi jalurnya API key. Yang tidak boleh adalah SATU kunci layanan dipakai semua
perangkat: record rule "pengemudi hanya melihat trip miliknya" bekerja dengan
membandingkan `driver_id.user_id` terhadap pemanggil, dan kunci bersama membuat
setiap perangkat menjadi pengguna yang sama. Perangkat yang hilang lalu berarti
seluruh jadwal armada ikut hilang.

Satu pengguna, satu perangkat, satu kunci — dan kunci itu dapat dicabut
sendiri-sendiri tanpa mengganggu perangkat lain.
"""
from odoo import _, api, fields, models


class LgxApiDevice(models.Model):
    _name = "lgx.api.device"
    _description = "Perangkat Lapangan"
    _order = "last_seen desc, id desc"

    name = fields.Char("Nama Perangkat", required=True)
    user_id = fields.Many2one("res.users", "Pengguna", required=True, index=True,
                              ondelete="cascade")
    partner_id = fields.Many2one(related="user_id.partner_id", store=True)
    company_id = fields.Many2one(related="user_id.company_id", store=True, index=True)
    kind = fields.Selection(
        [("driver", "Aplikasi Pengemudi"), ("scanner", "Pemindai Gudang"), ("other", "Lainnya")],
        string="Jenis", required=True, default="driver",
    )
    apikey_id = fields.Many2one("res.users.apikeys", "Kunci API", ondelete="set null",
                                readonly=True)
    key_prefix = fields.Char(
        "Awalan Kunci", readonly=True,
        help="Delapan karakter pertama, untuk mencocokkan perangkat dengan kunci di log. "
             "Kunci penuhnya tidak pernah disimpan — Odoo hanya menyimpan hash-nya.",
    )
    key_expiry = fields.Datetime(
        "Kunci Berlaku Sampai", readonly=True,
        help="Perangkat harus masuk ulang setelah tanggal ini. Kunci abadi di "
             "perangkat lapangan adalah pintu yang tidak pernah tertutup.",
    )
    last_seen = fields.Datetime("Terakhir Aktif", readonly=True)
    last_ip = fields.Char("IP Terakhir", readonly=True)
    state = fields.Selection(
        [("active", "Aktif"), ("revoked", "Dicabut")],
        string="Status", default="active", required=True, index=True,
    )
    note = fields.Char("Catatan")

    _user_kind_name_uniq = models.Constraint(
        "unique(user_id, kind, name)",
        "Perangkat dengan nama itu sudah terdaftar untuk pengguna dan jenis yang sama.",
    )

    def action_revoke(self):
        """Cabut kunci perangkat. Perangkat lain tidak terpengaruh."""
        for device in self:
            if device.apikey_id:
                device.apikey_id.sudo().unlink()
            device.write({"state": "revoked", "apikey_id": False})
        return True

    def lgx_touch(self, remote_addr=None):
        self.ensure_one()
        self.sudo().write({
            "last_seen": fields.Datetime.now(),
            "last_ip": remote_addr or self.last_ip,
        })

    @api.model
    def lgx_issue_key(self, user, kind, device_name, remote_addr=None):
        """Terbitkan kunci untuk perangkat. Mengembalikan (device, kunci_mentah).

        Kunci mentah hanya ada SEKALI, di nilai kembalian ini. Odoo menyimpan
        hash-nya; tidak ada cara membacanya lagi kemudian, dan itu memang
        seharusnya.
        """
        device = self.sudo().search([
            ("user_id", "=", user.id), ("kind", "=", kind), ("name", "=", device_name),
        ], limit=1)
        if device and device.apikey_id:
            # Perangkat yang sama mendaftar ulang: kunci lama dicabut supaya
            # tidak ada dua kunci hidup untuk satu perangkat. Kunci yang
            # tertinggal hidup di perangkat yang sudah dihapus aplikasinya
            # adalah kunci yang tidak ada yang merasa memilikinya.
            device.apikey_id.sudo().unlink()
        # Masa berlaku WAJIB, dan bukan karena Odoo memaksanya.
        #
        # Odoo memang menolak kunci tanpa masa berlaku untuk pengguna non-admin
        # (`_check_expiration_date`), dan pengemudi maupun operator gudang jelas
        # bukan admin — jadi memanggil `_generate(..., None)` seperti versi
        # pertama kode ini akan gagal di perangkat pertama yang mendaftar.
        #
        # Tetapi alasan sesungguhnya bukan constraint itu: perangkat lapangan
        # hilang, dijual, atau dipakai orang lain setelah pengemudi berhenti.
        # Kunci yang tidak pernah mati akan hidup lebih lama daripada hubungan
        # kerjanya. `sudo()` di sini melewati BATAS durasi grup, bukan melewati
        # keharusan punya masa berlaku — tanggalnya tetap diisi.
        days = int(self.env["ir.config_parameter"].sudo().get_param(
            "lgx.device_key_days", 90))
        expiry = fields.Datetime.add(fields.Datetime.now(), days=days)
        raw = self.env["res.users.apikeys"].with_user(user).sudo()._generate(
            "rpc", "LGX %s — %s" % (kind, device_name), expiry)
        apikey = self.env["res.users.apikeys"].sudo().search(
            [("user_id", "=", user.id)], order="id desc", limit=1)
        values = {
            "name": device_name,
            "user_id": user.id,
            "kind": kind,
            "apikey_id": apikey.id,
            "key_prefix": raw[:8],
            "state": "active",
            "key_expiry": expiry,
            "last_seen": fields.Datetime.now(),
            "last_ip": remote_addr,
        }
        if device:
            device.sudo().write(values)
        else:
            device = self.sudo().create(values)
        return device, raw
