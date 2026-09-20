# -*- coding: utf-8 -*-
"""Fondasi tes pajak logistik.

Menumpang fixture akuntansi `custom_lgx_billing` dengan sengaja: yang diuji di
sini adalah perlakuan pajak DI ATAS dokumen yang dibentuk jalur penagihan yang
sama dengan produksi. Fixture pajak sendiri akan hijau di atas faktur yang
tidak pernah dibuat siapa pun.
"""
from odoo.addons.custom_lgx_billing.tests.common import LgxAccountingCommon


class LgxTaxCommon(LgxAccountingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # charge_ofr: freight, besaran tertentu. charge_doc: jasa non-freight.
        cls.charge_freight = cls.env.ref("custom_lgx_base.charge_ofr")
        cls.charge_nonfreight = cls.env.ref("custom_lgx_base.charge_doc")
        cls.charge_trucking = cls.env.ref("custom_lgx_base.charge_trk")

        # Tidak ada kode bawaan dengan perlakuan ekspor jasa / angkutan umum
        # dibebaskan; keduanya dibuat di sini supaya cabangnya benar-benar
        # terlewati, bukan diasumsikan tak terjangkau.
        cls.charge_export = cls.charge_nonfreight.copy({
            "code": "EXPSVC", "name": "Jasa ekspor uji",
            "vat_treatment": "export_service_zero",
        })
        cls.charge_exempt = cls.charge_nonfreight.copy({
            "code": "ANGKUM", "name": "Angkutan umum uji",
            "vat_treatment": "exempt_public_transport",
        })

    def _invoice_for(self, job):
        """Faktur pelanggan lewat jalur produksi, bukan account.move mentah."""
        job.action_confirm()
        return job.lgx_create_customer_invoice()

    def _attachment(self, name):
        return self.env["ir.attachment"].create({"name": name, "datas": "SGFsbG8="})
