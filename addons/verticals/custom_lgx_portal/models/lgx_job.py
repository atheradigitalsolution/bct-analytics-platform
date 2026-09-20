# -*- coding: utf-8 -*-
"""Job di portal: token pelacakan yang kedaluwarsa, dan pengajuan booking.

KENAPA TOKEN SENDIRI DAN BUKAN `portal.mixin.access_token`
---------------------------------------------------------
`portal.mixin` sudah memberi `access_token`, dan ia dipakai di sini untuk
halaman portal pelanggan yang sudah login. Tetapi untuk PELACAKAN PUBLIK —
tautan yang dikirim ke pihak yang tidak punya akun — token abadi tidak cukup.

Nomor B/L beredar di rantai pasok: di surel, di grup pesan, di berkas Excel yang
diteruskan ke pihak ketiga. Tautan yang ikut beredar bersamanya dan tidak pernah
mati adalah pintu yang tidak pernah tertutup. Masa berlakunya karena itu
dikonfigurasi, dan defaultnya pendek.
"""
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LgxJob(models.Model):
    _name = "lgx.job"
    _inherit = ["lgx.job", "portal.mixin"]

    lgx_track_token = fields.Char("Token Pelacakan Publik", copy=False, readonly=True,
                                  groups="custom_lgx_base.group_lgx_staff")
    lgx_track_token_expiry = fields.Datetime("Token Berlaku Sampai", copy=False, readonly=True,
                                             groups="custom_lgx_base.group_lgx_staff")
    portal_document_ids = fields.One2many(
        "lgx.document", "job_id", "Dokumen Portal",
        domain=[("is_customer_visible", "=", True)],
        help="Hanya dokumen yang ditandai terlihat pelanggan. Dokumen internal "
             "tidak pernah masuk daftar ini.",
    )
    portal_milestone_ids = fields.One2many(
        "lgx.milestone", "job_id", "Milestone Portal",
        domain=[("is_customer_visible", "=", True), ("actual_date", "!=", False)],
    )
    is_portal_booking = fields.Boolean(
        "Berasal dari Booking Portal", readonly=True, copy=False,
        help="Job yang lahir dari pengajuan pelanggan, bukan dari penawaran yang "
             "sudah dinegosiasikan. Ia menunggu konfirmasi operasi.",
    )

    def _compute_access_url(self):
        super()._compute_access_url()
        for job in self:
            job.access_url = "/my/logistik/job/%s" % job.id

    # --- token pelacakan publik --------------------------------------------
    @api.model
    def _track_token_ttl_hours(self):
        return self.env["ir.config_parameter"].sudo().lgx_int("lgx.track_link_ttl_hours", 72)

    def lgx_issue_track_token(self, force=False):
        """Terbitkan token pelacakan baru dengan masa berlaku.

        `secrets.token_urlsafe`, bukan uuid4: yang dibutuhkan di sini adalah
        ketidakterdugaan kriptografis, dan uuid4 memang acak tetapi dirancang
        untuk keunikan, bukan untuk menahan tebakan.
        """
        self.ensure_one()
        now = fields.Datetime.now()
        if (not force and self.sudo().lgx_track_token
                and self.sudo().lgx_track_token_expiry
                and self.sudo().lgx_track_token_expiry > now):
            return self.sudo().lgx_track_token
        token = secrets.token_urlsafe(32)
        self.sudo().write({
            "lgx_track_token": token,
            "lgx_track_token_expiry": fields.Datetime.add(
                now, hours=self._track_token_ttl_hours()),
        })
        return token

    def _lgx_public_base_url(self):
        """Alamat yang BENAR-BENAR dapat dibuka pelanggan, atau menolak.

        `web.base.url` disetel Odoo secara otomatis dari header Host pada login
        pertama. Di platform ini tenant baru pertama kali disentuh lewat ALIAS
        JARINGAN INTERNAL, jadi nilainya membeku sebagai alamat yang hanya
        resolve di dalam jaringan Docker — dan tautan pelacakan yang dibangun
        di atasnya mati di tangan pelanggan tanpa satu galat pun di sisi kami.

        Terukur 2026-09-20 di stack ini:

            bct         https://bct.athera-digital.com
            expomedia   https://expomedia.athera-digital.com
            acme        http://localhost:8069        <- membeku dari laptop
            athera_lgx  http://athera_lgx...         <- http, bukan https

        Dua bentuk yang ditolak di sini, dan keduanya pernah benar-benar
        terjadi di stack ini:

        * localhost / 127.0.0.1 — tautan yang hanya bekerja di mesin yang
          membuatnya;
        * http:// — token pelacakan melintas tanpa enkripsi, dan pelanggan
          yang membuka tautan itu di jaringan publik menyerahkan tokennya.

        Menolak, bukan memperbaiki diam-diam. Menebak https untuk hostname yang
        belum tentu punya sertifikat hanya memindahkan kegagalan ke tempat yang
        lebih sulit dilihat — dan yang harus memutuskan alamat publik sebuah
        tenant adalah orang yang memasangnya, bukan modul ini.
        """
        self.ensure_one()
        base = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").strip()
        buruk = None
        if not base:
            buruk = _("belum disetel sama sekali")
        elif "localhost" in base or "127.0.0.1" in base:
            buruk = _("menunjuk localhost, jadi ia hanya bekerja di mesin ini")
        elif base.startswith("http://"):
            buruk = _("memakai http, jadi token pelacakan melintas tanpa enkripsi")
        if buruk:
            raise UserError(_(
                "Tautan pelacakan tidak dapat dibuat: parameter sistem "
                "'web.base.url' %s.\n\nNilainya sekarang: %s\n\n"
                "Odoo menyetelnya otomatis dari alamat yang dipakai saat login "
                "pertama, dan di platform ini tenant baru sering pertama kali "
                "disentuh lewat alias jaringan internal. Setel ke alamat publik "
                "tenant ini di Pengaturan > Teknis > Parameter Sistem.",
                buruk, base or _("(kosong)"),
            ))
        return base.rstrip("/")

    def action_share_tracking_link(self):
        """Tampilkan tautan pelacakan berikut masa berlakunya, apa adanya."""
        self.ensure_one()
        token = self.lgx_issue_track_token()
        base = self._lgx_public_base_url()
        url = "%s/lgx/lacak/%s/%s" % (base, self.id, token)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "info",
                "title": _("Tautan pelacakan"),
                "message": _("%s\n\nBerlaku sampai %s. Setelah itu tautan mati dan "
                             "harus diterbitkan ulang.", url, self.sudo().lgx_track_token_expiry),
                "sticky": True,
            },
        }

    def action_revoke_track_token(self):
        """Matikan tautan yang sudah terlanjur beredar, tanpa menunggu kedaluwarsa."""
        for job in self:
            job.sudo().write({"lgx_track_token": False, "lgx_track_token_expiry": False})
        return True

    @api.model
    def lgx_resolve_track_token(self, job_id, token):
        """Cari job dari (id, token). Mengembalikan recordset kosong bila tidak sah.

        Tidak membedakan "token salah" dari "token kedaluwarsa" dari "job tidak
        ada" di nilai kembaliannya — pemanggil hanya perlu tahu boleh atau tidak.
        Membedakannya di respons publik berarti memberi tahu penebak bahwa ia
        sudah menemukan job yang benar.
        """
        if not job_id or not token:
            return self.browse()
        job = self.sudo().browse(int(job_id)).exists()
        if not job or not job.lgx_track_token:
            return self.browse()
        if not secrets.compare_digest(job.lgx_track_token, str(token)):
            return self.browse()
        if not job.lgx_track_token_expiry or job.lgx_track_token_expiry < fields.Datetime.now():
            return self.browse()
        return job

    # --- booking dari portal -----------------------------------------------
    @api.model
    def lgx_create_portal_booking(self, partner, values):
        """Buat job `draft` dari pengajuan pelanggan, dan tugaskan tindak lanjutnya.

        Job draf, bukan job berjalan: tidak ada pekerjaan yang masuk antrian
        operasi hanya karena seseorang mengisi formulir.
        """
        job = self.sudo().create({
            "job_type": values.get("job_type") or "ff_import",
            "transport_mode": values.get("transport_mode") or "sea",
            "customer_id": partner.commercial_partner_id.id,
            "origin_location_id": values.get("origin_id") or False,
            "destination_location_id": values.get("destination_id") or False,
            "etd": values.get("etd") or False,
            "customer_reference": values.get("customer_reference") or False,
            "description": values.get("note") or False,
            "is_portal_booking": True,
            "state": "draft",
        })
        responsible = job.salesperson_id or self.env.ref("base.user_admin", raise_if_not_found=False)
        if responsible:
            job.sudo().activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("Booking portal dari %s", partner.display_name),
                note=_("Pelanggan mengajukan booking lewat portal. Job %s menunggu "
                       "konfirmasi: periksa rute, tarif, dan kapasitas sebelum "
                       "dikonfirmasi.", job.name),
                user_id=responsible.id,
            )
        job.sudo().message_post(body=_(
            "Booking diajukan lewat portal oleh %s.", partner.display_name))
        return job
