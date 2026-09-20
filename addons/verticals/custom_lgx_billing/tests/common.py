# -*- coding: utf-8 -*-
"""Fondasi tes akuntansi logistik.

`post_install` dan bukan `at_install`: tes ini membuat record `res.partner`,
`account.move` dan `product.product`. Di registry parsial yang dilihat tes
`at_install`, default field dari modul yang belum dimuat hilang dan tes gagal
dengan NotNullViolation yang menyamar sebagai kerusakan skema.
"""
from odoo.tests import TransactionCase


class LgxAccountingCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls._ensure_lgx_accounts(cls.company)

        cls.customer = cls.env["res.partner"].create({
            "name": "PT Pelanggan Uji",
            "company_type": "company",
        })
        cls.vendor = cls.env["res.partner"].create({
            "name": "PT Vendor Uji",
            "company_type": "company",
            "supplier_rank": 1,
        })
        cls.charge_service = cls.env.ref("custom_lgx_base.charge_ofr")
        cls.charge_disb = cls.env.ref("custom_lgx_base.charge_bm")
        cls.loc_origin = cls.env.ref("custom_lgx_base.loc_cnsha")
        cls.loc_dest = cls.env.ref("custom_lgx_base.loc_idjkt")

    @classmethod
    def _ensure_lgx_accounts(cls, company):
        """Pakai method produksi, bukan penyiapan khusus tes.

        Tes yang menyiapkan akunnya sendiri akan hijau di atas peta akun yang
        tidak pernah dipakai siapa pun. Memanggil `lgx_setup_default_accounts`
        berarti yang diuji adalah penyiapan yang sama dengan yang dijalankan
        tenant sungguhan.
        """
        company.lgx_setup_default_accounts()

    def _complete_mandatory_milestones(self, job):
        """Penuhi milestone wajib supaya job bisa masuk 'Selesai Operasi'.

        Bukan jalan pintas: penutupan operasional memang menuntut milestone wajib
        tercapai, dan tes yang menguji lapisan KEUANGAN tidak boleh gagal karena
        lapisan operasinya belum dijalankan.
        """
        import datetime
        job.milestone_ids.filtered(lambda m: m.is_mandatory and not m.actual_date).write({
            "actual_date": datetime.datetime(2026, 9, 20, 8, 0, 0),
        })
        return job

    def _make_job(self, **kw):
        vals = {
            "job_type": "ff_import",
            "transport_mode": "sea",
            "customer_id": self.customer.id,
            "origin_location_id": self.loc_origin.id,
            "destination_location_id": self.loc_dest.id,
            "etd": "2026-09-01",
            "eta": "2026-09-20",
        }
        vals.update(kw)
        return self.env["lgx.job"].create(vals)

    def _add_charge(self, job, code, kind, amount, nature=None, partner=None, proof=False):
        charge = self.env["lgx.job.charge"].create({
            "job_id": job.id,
            "charge_code_id": code.id,
            "kind": kind,
            "nature": nature or code.default_nature,
            "is_freight_charge": code.is_freight_charge,
            "quantity": 1.0,
            "unit_price": amount,
            "amount_estimated": amount,
            "partner_id": (partner or (self.vendor if kind == "cost" else False)) and
                          (partner or self.vendor).id,
            "currency_id": job.currency_id.id,
        })
        if proof:
            attachment = self.env["ir.attachment"].create({
                "name": "bukti-pihak-ketiga.pdf",
                "datas": "SGFsbG8=",
                "res_model": "lgx.job.charge",
                "res_id": charge.id,
            })
            charge.third_party_proof_ids = [(4, attachment.id)]
        return charge

    def _balance_of(self, account, job=None):
        domain = [("account_id", "=", account.id), ("parent_state", "=", "posted")]
        if job:
            domain.append(("lgx_job_id", "=", job.id))
        lines = self.env["account.move.line"].search(domain)
        return sum(lines.mapped("balance"))
