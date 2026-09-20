# -*- coding: utf-8 -*-
"""LGX-G01/G02/G03 — isolasi portal, tautan yang kedaluwarsa, dan booking.

Diuji di lapisan ORM DENGAN HAK AKSES PENGGUNA PORTAL SUNGGUHAN
(`with_user`), bukan lewat HTTP. Alasannya: yang melindungi data adalah record
rule, dan record rule hanya benar-benar diuji kalau kueri berjalan sebagai
pengguna yang dibatasi. Tes yang memanggil controller sebagai superuser akan
hijau meski seluruh rule-nya salah.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPortalIsolation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_a = cls.env["res.partner"].create({"name": "PT Pelanggan Portal A"})
        cls.partner_b = cls.env["res.partner"].create({"name": "PT Pelanggan Portal B"})
        portal_group = cls.env.ref("base.group_portal")
        cls.user_a = cls.env["res.users"].create({
            "name": "Kontak A", "login": "portal.a@uji.invalid",
            "partner_id": cls.partner_a.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.user_b = cls.env["res.users"].create({
            "name": "Kontak B", "login": "portal.b@uji.invalid",
            "partner_id": cls.partner_b.id,
            "group_ids": [(6, 0, [portal_group.id])],
        })
        cls.job_a = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": cls.partner_a.id, "etd": "2026-09-01",
        })
        cls.job_b = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": cls.partner_b.id, "etd": "2026-09-01",
        })
        ms_type_public = cls.env.ref("custom_lgx_base.ms_vessel_departed")
        ms_type_internal = cls.env.ref("custom_lgx_base.ms_demurrage_started")
        cls.milestone_public = cls.env["lgx.milestone"].create({
            "job_id": cls.job_a.id, "milestone_type_id": ms_type_public.id,
            "actual_date": "2026-09-02 08:00:00", "is_customer_visible": True,
        })
        cls.milestone_internal = cls.env["lgx.milestone"].create({
            "job_id": cls.job_a.id, "milestone_type_id": ms_type_internal.id,
            "actual_date": "2026-09-05 08:00:00", "is_customer_visible": False,
        })
        doc_type = cls.env.ref("custom_lgx_base.doctype_hbl")
        doc_type_internal = cls.env.ref("custom_lgx_base.doctype_mbl")
        cls.doc_public = cls.env["lgx.document"].create({
            "name": "HBL/UJI/0001", "document_type_id": doc_type.id,
            "job_id": cls.job_a.id, "is_customer_visible": True,
        })
        cls.doc_internal = cls.env["lgx.document"].create({
            "name": "MBL/UJI/0001", "document_type_id": doc_type_internal.id,
            "job_id": cls.job_a.id, "is_customer_visible": False,
        })

    # --- isolasi antar pelanggan -------------------------------------------
    def test_portal_user_sees_only_own_jobs(self):
        visible = self.env["lgx.job"].with_user(self.user_a).search([])
        self.assertIn(self.job_a, visible)
        self.assertNotIn(
            self.job_b, visible,
            "Pengguna portal A tidak boleh melihat job pelanggan B.",
        )

    def test_portal_user_cannot_read_another_customers_job_directly(self):
        """Bahkan dengan id di tangan. Tebakan id adalah hal pertama yang dicoba orang."""
        with self.assertRaises(AccessError):
            self.job_b.with_user(self.user_a).read(["name"])

    def test_internal_milestones_are_invisible_to_portal(self):
        """Milestone internal — 'kontainer kena detensi' — bukan urusan pelanggan."""
        visible = self.env["lgx.milestone"].with_user(self.user_a).search(
            [("job_id", "=", self.job_a.id)])
        self.assertIn(self.milestone_public, visible)
        self.assertNotIn(
            self.milestone_internal, visible,
            "Milestone yang tidak ditandai terlihat pelanggan tidak boleh lolos ke portal.",
        )

    def test_internal_documents_are_invisible_to_portal(self):
        """Master B/L adalah dokumen carrier ke forwarder, bukan ke pemilik barang."""
        visible = self.env["lgx.document"].with_user(self.user_a).search(
            [("job_id", "=", self.job_a.id)])
        self.assertIn(self.doc_public, visible)
        self.assertNotIn(self.doc_internal, visible)

    def test_portal_user_cannot_write(self):
        with self.assertRaises(AccessError):
            self.job_a.with_user(self.user_a).write({"customer_reference": "diubah"})

    # --- tautan pelacakan publik -------------------------------------------
    def test_track_token_is_issued_and_resolves(self):
        token = self.job_a.lgx_issue_track_token()
        self.assertTrue(token)
        resolved = self.env["lgx.job"].lgx_resolve_track_token(self.job_a.id, token)
        self.assertEqual(resolved, self.job_a)

    def test_wrong_token_resolves_to_nothing(self):
        self.job_a.lgx_issue_track_token()
        resolved = self.env["lgx.job"].lgx_resolve_track_token(self.job_a.id, "token-karangan")
        self.assertFalse(resolved)

    def test_expired_token_resolves_to_nothing(self):
        """Inilah perbedaan dari `portal.mixin.access_token`, yang berlaku selamanya.

        Nomor B/L beredar di rantai pasok, dan tautan abadi yang ikut beredar
        bersamanya adalah pintu yang tidak pernah tertutup.
        """
        token = self.job_a.lgx_issue_track_token()
        self.job_a.sudo().lgx_track_token_expiry = fields.Datetime.subtract(
            fields.Datetime.now(), hours=1)
        resolved = self.env["lgx.job"].lgx_resolve_track_token(self.job_a.id, token)
        self.assertFalse(resolved, "Tautan yang sudah lewat masa berlaku harus mati.")

    def test_revoked_token_resolves_to_nothing(self):
        """Mencabut tautan yang terlanjur beredar tidak boleh menunggu kedaluwarsa."""
        token = self.job_a.lgx_issue_track_token()
        self.job_a.action_revoke_track_token()
        self.assertFalse(self.env["lgx.job"].lgx_resolve_track_token(self.job_a.id, token))

    def test_token_of_one_job_does_not_open_another(self):
        token_a = self.job_a.lgx_issue_track_token()
        self.job_b.lgx_issue_track_token()
        self.assertFalse(
            self.env["lgx.job"].lgx_resolve_track_token(self.job_b.id, token_a),
            "Token job A tidak boleh membuka job B.",
        )

    def test_two_absences_do_not_cancel_each_other(self):
        """Token kosong terhadap job yang BELUM PERNAH punya token harus ditolak.

        Bentuk yang dilaporkan sesi SIMRS setelah menemukannya di penjaga token
        mereka: `claims.get("stk") != credential_marker(holder)` — kalau KEDUANYA
        None, `None != None` bernilai False dan keduanya lolos sekaligus.

        Bukan penjaga yang longgar, bukan yang rakus: **cocok karena sama-sama
        kosong**, tepat di jalur yang paling ingin ditutup. Dan ia hanya terlihat
        dari menanyakan "apa yang terjadi kalau KEDUANYA tidak ada" — pertanyaan
        yang tidak pernah muncul dari membaca ekspresinya.

        Enam uji token yang sudah ada semuanya memakai token tidak-kosong
        terhadap job yang PUNYA token. Matriks ketiadaannya tidak pernah
        disentuh; kodenya kebetulan menjaga, dan tidak ada yang membuktikan
        penjaganya bertahan.
        """
        Job = self.env["lgx.job"]
        polos = Job.create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": self.partner_a.id, "etd": "2026-09-01",
        })
        self.assertFalse(polos.lgx_track_token, "Prasyarat: job ini belum punya token.")

        for kosong in ("", None, False):
            self.assertFalse(
                Job.lgx_resolve_track_token(polos.id, kosong),
                "Token %r terhadap job tanpa token harus ditolak; dua ketiadaan "
                "tidak boleh saling membatalkan." % (kosong,),
            )

        # DAN keadaan yang melewati penjaga KEDUA. Versi pertama uji ini hanya
        # memakai job polos di atas, dan kontrol negatifnya LULUS — bentuk
        # rentan `job.lgx_track_token != token` tetap tertolak, bukan oleh
        # perbandingan tokennya melainkan oleh pemeriksaan masa berlaku di
        # belakangnya. Ujinya menegaskan HASIL yang dijaga dua lapis, sambil
        # docstring-nya mengklaim menangkap lapis pertama.
        #
        # Keadaan di bawah memisahkan keduanya: token kosong DENGAN masa
        # berlaku yang masih hidup. Diukur pada bentuk rentan sebelum uji ini
        # ditulis — token='' dan None tetap ditolak, tetapi False LOLOS, karena
        # `False != False` bernilai False dan perbandingannya tidak menolak.
        polos.sudo().write({
            "lgx_track_token": False,
            "lgx_track_token_expiry": fields.Datetime.now() + timedelta(hours=24),
        })
        for kosong in ("", None, False):
            self.assertFalse(
                Job.lgx_resolve_track_token(polos.id, kosong),
                "Token %r lolos pada job tanpa token yang masa berlakunya masih "
                "hidup — dua ketiadaan saling membatalkan." % (kosong,),
            )

    def test_absent_token_against_a_job_that_has_one(self):
        """Satu ketiadaan saja juga ditolak — kontrol untuk uji di atasnya."""
        Job = self.env["lgx.job"]
        self.job_a.lgx_issue_track_token()
        self.assertTrue(self.job_a.lgx_track_token, "Prasyarat: job ini punya token.")
        for kosong in ("", None, False):
            self.assertFalse(Job.lgx_resolve_track_token(self.job_a.id, kosong))

    def test_real_token_against_a_job_that_never_had_one(self):
        """Ketiadaan di sisi SIMPANAN, bukan di sisi masukan."""
        Job = self.env["lgx.job"]
        token_sah = self.job_a.lgx_issue_track_token()
        polos = Job.create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": self.partner_a.id, "etd": "2026-09-01",
        })
        self.assertFalse(Job.lgx_resolve_track_token(polos.id, token_sah))

    def test_reissue_returns_the_same_token_while_valid(self):
        """Menerbitkan ulang tidak boleh mematikan tautan yang sudah dikirim ke pelanggan."""
        first = self.job_a.lgx_issue_track_token()
        second = self.job_a.lgx_issue_track_token()
        self.assertEqual(first, second)
        forced = self.job_a.lgx_issue_track_token(force=True)
        self.assertNotEqual(first, forced)

    # --- pencatatan unduhan ------------------------------------------------
    def test_download_is_logged_with_source_and_partner(self):
        self.doc_public.lgx_log_download(partner=self.partner_a, source="portal",
                                         remote_addr="203.0.113.7")
        self.doc_public.invalidate_recordset()
        self.assertEqual(self.doc_public.download_count, 1)
        log = self.doc_public.download_log_ids
        self.assertEqual(log.partner_id, self.partner_a)
        self.assertEqual(log.source, "portal")
        self.assertEqual(log.remote_addr, "203.0.113.7")
        self.assertTrue(self.doc_public.last_downloaded_at)

    # --- booking -----------------------------------------------------------
    def test_portal_booking_creates_a_draft_job_and_an_activity(self):
        """Tidak ada pekerjaan yang masuk antrian operasi karena seseorang mengisi formulir."""
        job = self.env["lgx.job"].lgx_create_portal_booking(self.partner_a, {
            "job_type": "ff_export", "transport_mode": "air",
            "customer_reference": "PO-PORTAL-9",
            "note": "20 koli sparepart, 480 kg",
        })
        self.assertEqual(job.state, "draft")
        self.assertTrue(job.is_portal_booking)
        self.assertEqual(job.customer_id, self.partner_a)
        self.assertEqual(job.customer_reference, "PO-PORTAL-9")
        self.assertTrue(job.name and job.name != "/",
                        "Pelanggan harus menerima nomor referensi seketika.")
        self.assertTrue(
            job.activity_ids,
            "Booking portal harus menempel pada seseorang sebagai aktivitas terjadwal.",
        )


@tagged("post_install", "-at_install")
class TestPublicBaseUrl(TransactionCase):
    """Tautan pelacakan tidak boleh dibangun di atas alamat yang tidak dapat dibuka.

    `web.base.url` disetel Odoo dari header Host pada login pertama. Di platform
    ini tenant baru sering pertama kali disentuh lewat alias jaringan internal,
    jadi nilainya membeku sebagai alamat yang hanya resolve di dalam jaringan —
    dan tautannya mati di tangan pelanggan tanpa satu galat pun di sisi kami.

    Terukur di stack ini saat uji ini ditulis: acme memakai http://localhost:8069,
    athera_lgx memakai http:// sementara bct dan expomedia memakai https://.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.P = cls.env["ir.config_parameter"].sudo()
        cls.asli = cls.P.get_param("web.base.url")
        partner = cls.env["res.partner"].create({"name": "PT Uji Tautan"})
        cls.job = cls.env["lgx.job"].create({
            "job_type": "ff_import", "transport_mode": "sea",
            "customer_id": partner.id, "etd": "2026-09-01",
        })

    def tearDown(self):
        self.P.set_param("web.base.url", self.asli or "")
        super().tearDown()

    def _tolak(self, nilai, penanda):
        self.P.set_param("web.base.url", nilai)
        with self.assertRaises(UserError) as ctx:
            self.job.action_share_tracking_link()
        self.assertIn(penanda, str(ctx.exception).lower())

    def test_localhost_is_refused(self):
        """Tautan yang hanya bekerja di mesin yang membuatnya."""
        self._tolak("http://localhost:8069", "localhost")

    def test_plain_http_is_refused(self):
        """Token pelacakan tidak boleh melintas tanpa enkripsi."""
        self._tolak("http://athera_lgx.athera-digital.com", "http")

    def test_empty_is_refused(self):
        self._tolak("", "belum disetel")

    def test_the_message_tells_you_to_freeze_it_too(self):
        """Memperbaiki web.base.url tanpa freeze akan dibatalkan login berikutnya.

        Odoo menimpanya dari header Host tiap login backend kecuali
        `web.base.url.freeze` disetel — diverifikasi di sumber Odoo
        (res_users.py, `if not ICP.get_param('web.base.url.freeze')`), bukan
        diterima dari pihak ketiga.

        Tanpa kalimat itu, operator memperbaiki lalu melihat perbaikannya hilang
        tanpa tahu kenapa — dan perbaikan yang dibatalkan diam-diam lebih sulit
        didiagnosis daripada yang tidak pernah dilakukan.
        """
        self.P.set_param("web.base.url", "http://athera_lgx.athera-digital.com")
        with self.assertRaises(UserError) as ctx:
            self.job.action_share_tracking_link()
        self.assertIn("web.base.url.freeze", str(ctx.exception))

    def test_a_proper_public_url_is_accepted(self):
        """Kontrol positif: penjaga tidak boleh menolak alamat yang benar.

        Penjaga yang menolak segalanya lulus ketiga uji di atas dengan gemilang
        dan mematikan fitur berbagi tautan sepenuhnya.
        """
        self.P.set_param("web.base.url", "https://athera_lgx.athera-digital.com/")
        hasil = self.job.action_share_tracking_link()
        self.assertEqual(hasil["type"], "ir.actions.client")
        pesan = hasil["params"]["message"]
        self.assertIn("https://athera_lgx.athera-digital.com/lgx/lacak/", pesan)
        self.assertNotIn("//lgx/lacak", pesan, "Garis miring ganda: rstrip gagal.")
