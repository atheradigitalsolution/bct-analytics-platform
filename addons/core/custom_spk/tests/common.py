# -*- coding: utf-8 -*-
"""Users shaped like the real roles, because the fence is about who you are."""

from __future__ import annotations

from odoo.tests.common import TransactionCase


class SpkCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Spk = cls.env["custom.spk"]
        cls.Shift = cls.env["custom.spk.shift"]
        cls.partner = cls.env["res.partner"].create({"name": "Klien Pameran"})

        # The AE gets the AE group and NOTHING else beyond internal user. That is the
        # whole design: no sales group means no sale.order, and the fence does not
        # depend on remembering to hide a field.
        cls.ae = cls._user("ae", ["custom_spk.group_spk_ae"])
        cls.ae_other = cls._user("ae2", ["custom_spk.group_spk_ae"])
        cls.pm = cls._user("pm", ["custom_spk.group_spk_pm"])
        cls.finance = cls._user("fin", ["custom_spk.group_spk_price_viewer"])

    @classmethod
    def _user(cls, login, group_xmlids):
        groups = [cls.env.ref("base.group_user").id]
        groups += [cls.env.ref(x).id for x in group_xmlids]
        return cls.env["res.users"].create({
            "name": login,
            "login": login,
            "group_ids": [(6, 0, groups)],
        })
