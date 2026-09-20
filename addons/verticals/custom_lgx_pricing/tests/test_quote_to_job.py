# -*- coding: utf-8 -*-
"""LGX-A01 dan LGX-A02 — penawaran dari rate card, lalu konversinya menjadi job."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQuoteToJob(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env["res.partner"].create({
            "name": "PT Pelanggan Tarif", "company_type": "company",
        })
        cls.carrier = cls.env["res.partner"].create({
            "name": "Evergreen Uji", "company_type": "company", "lgx_is_carrier": True,
        })
        cls.origin = cls.env.ref("custom_lgx_base.loc_cnsha")
        cls.dest = cls.env.ref("custom_lgx_base.loc_idjkt")
        cls.ofr = cls.env.ref("custom_lgx_base.charge_ofr")
        cls.thc = cls.env.ref("custom_lgx_base.charge_thc_d")
        cls.doc = cls.env.ref("custom_lgx_base.charge_doc")
        cls.ctype = cls.env.ref("custom_lgx_base.ctype_20gp")

        cls.sell_card = cls.env["lgx.rate.card"].create({
            "name": "Jual SHA-JKT FCL 2026",
            "direction": "sell",
            "transport_mode": "sea",
            "load_type": "fcl",
            "origin_id": cls.origin.id,
            "destination_id": cls.dest.id,
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "line_ids": [
                (0, 0, {"charge_code_id": cls.ofr.id, "basis": "per_container",
                        "container_type_id": cls.ctype.id, "price": 12_000_000}),
                (0, 0, {"charge_code_id": cls.thc.id, "basis": "per_container", "price": 1_500_000}),
                (0, 0, {"charge_code_id": cls.doc.id, "basis": "per_bl", "price": 750_000}),
            ],
        })
        cls.sell_card.action_activate()
        cls.buy_card = cls.env["lgx.rate.card"].create({
            "name": "Beli SHA-JKT FCL 2026",
            "direction": "buy",
            "partner_id": cls.carrier.id,
            "transport_mode": "sea",
            "load_type": "fcl",
            "origin_id": cls.origin.id,
            "destination_id": cls.dest.id,
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "line_ids": [
                (0, 0, {"charge_code_id": cls.ofr.id, "basis": "per_container",
                        "container_type_id": cls.ctype.id, "price": 9_000_000}),
                (0, 0, {"charge_code_id": cls.thc.id, "basis": "per_container", "price": 1_500_000}),
            ],
        })
        cls.buy_card.action_activate()

    def _quote(self, **kw):
        vals = {
            "customer_id": self.customer.id,
            "date": "2026-06-01",
            "validity_date": "2026-06-30",
            "job_type": "ff_import",
            "transport_mode": "sea",
            "load_type": "fcl",
            "origin_id": self.origin.id,
            "destination_id": self.dest.id,
        }
        vals.update(kw)
        return self.env["lgx.quote"].create(vals)

    def test_load_rates_shows_buy_and_sell_side_by_side(self):
        """LGX-A01 — baris muncul dari rate card berlaku, beli dan jual berdampingan."""
        quote = self._quote()
        quote.action_load_rates()
        self.assertEqual(len(quote.line_ids), 3)
        ofr_line = quote.line_ids.filtered(lambda l: l.charge_code_id == self.ofr)
        self.assertEqual(ofr_line.sell_price, 12_000_000)
        self.assertEqual(ofr_line.buy_price, 9_000_000)
        self.assertEqual(quote.revenue_total, 14_250_000)
        self.assertEqual(quote.cost_total, 10_500_000)
        self.assertAlmostEqual(quote.margin_pct, 26.32, places=1)

    def test_line_without_buy_rate_is_flagged_manual(self):
        """Baris yang tidak punya padanan tarif beli ditandai manual, bukan diam-diam nol.

        Harga beli nol yang tidak ditandai membuat margin tampak 100% — dan itu
        penawaran yang dikirim dengan percaya diri ke pelanggan.
        """
        quote = self._quote()
        quote.action_load_rates()
        doc_line = quote.line_ids.filtered(lambda l: l.charge_code_id == self.doc)
        self.assertTrue(doc_line.manual_price)
        self.assertTrue(quote.has_manual_price)

    def test_expired_rate_card_is_not_selected(self):
        """Rate card yang sudah lewat valid_to tidak ikut terpilih."""
        self.sell_card.write({"valid_to": "2026-03-31"})
        quote = self._quote(date="2026-06-01")
        with self.assertRaises(UserError):
            quote.action_load_rates()

    def test_low_margin_quote_cannot_be_sent_without_approval(self):
        """Penawaran di bawah ambang margin tertahan sampai manajer menyetujui, dengan alasan."""
        self.env["ir.config_parameter"].sudo().set_param("lgx.min_margin_pct", "40.0")
        quote = self._quote()
        quote.action_load_rates()
        with self.assertRaises(UserError) as ctx:
            quote.action_send()
        self.assertIn("ambang", str(ctx.exception).lower())

    def test_conversion_creates_revenue_and_cost_charges(self):
        """LGX-A02 — konversi membuat DUA baris charge per baris penawaran.

        Bila hanya baris pendapatan yang terbentuk, akrual biaya tidak pernah
        ada dan laba job tampak 100% sampai tagihan vendor datang berminggu-minggu
        kemudian.
        """
        quote = self._quote()
        quote.action_load_rates()
        quote.action_send()
        quote.action_accept()
        quote.action_create_job()
        job = quote.job_id

        self.assertTrue(job, "Konversi harus menghasilkan job.")
        revenue = job.charge_ids.filtered(lambda c: c.kind == "revenue")
        cost = job.charge_ids.filtered(lambda c: c.kind == "cost")
        self.assertEqual(len(revenue), 3)
        self.assertEqual(len(cost), 2, "Baris biaya dari rate card beli harus ikut terbentuk.")
        self.assertTrue(all(c.state == "estimated" for c in job.charge_ids))
        self.assertEqual(job.revenue_estimated + job.disbursement_billed, 14_250_000)

    def test_new_job_receives_milestone_series(self):
        """Job baru langsung punya rangkaian milestone sesuai job_type, bertanggal rencana."""
        quote = self._quote()
        quote.action_load_rates()
        quote.action_send()
        quote.action_accept()
        quote.action_create_job()
        job = quote.job_id
        self.assertTrue(job.milestone_ids, "Job baru harus lahir dengan rangkaian milestone.")
        self.assertTrue(
            all(not m.actual_date for m in job.milestone_ids),
            "Tanggal aktual milestone harus kosong pada job baru.",
        )

    def test_quote_cannot_be_converted_twice(self):
        quote = self._quote()
        quote.action_load_rates()
        quote.action_send()
        quote.action_accept()
        quote.action_create_job()
        with self.assertRaises(UserError):
            quote.action_create_job()

    def test_rate_card_version_does_not_disturb_issued_quote(self):
        """LGX-A04 — versi baru tidak mengubah penawaran yang sudah terbit."""
        quote = self._quote()
        quote.action_load_rates()
        quote.action_send()
        total_before = quote.revenue_total
        action = self.sell_card.action_new_version()
        new_card = self.env["lgx.rate.card"].browse(action["res_id"])
        new_card.line_ids.write({"price": 99_000_000})
        new_card.action_activate()
        quote.invalidate_recordset()
        self.assertEqual(
            quote.revenue_total, total_before,
            "Penawaran yang sudah terkirim tidak boleh berubah karena tarif baru terbit.",
        )
        self.assertEqual(quote.sell_rate_card_id, self.sell_card)
