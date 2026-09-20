# -*- coding: utf-8 -*-
"""LGX-G01/G02/G03 — isolasi portal, tautan yang kedaluwarsa, dan booking.

Diuji di lapisan ORM DENGAN HAK AKSES PENGGUNA PORTAL SUNGGUHAN
(`with_user`), bukan lewat HTTP. Alasannya: yang melindungi data adalah record
rule, dan record rule hanya benar-benar diuji kalau kueri berjalan sebagai
pengguna yang dibatasi. Tes yang memanggil controller sebagai superuser akan
hijau meski seluruh rule-nya salah.
"""
from odoo import fields
from odoo.exceptions import AccessError
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
