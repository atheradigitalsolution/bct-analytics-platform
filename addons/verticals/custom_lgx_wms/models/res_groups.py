# -*- coding: utf-8 -*-
"""Hibah grup: operator gudang LGX menyiratkan pengguna Inventory Odoo.

KENAPA <function> DAN BUKAN <record>
-----------------------------------
Grup LGX lahir di `custom_lgx_base/security/lgx_groups.xml` di dalam
`<data noupdate="1">`. Flag itu tersimpan pada baris `ir.model.data` MILIK
GRUPNYA, bukan pada modul yang menulisnya — sehingga `<record model="res.groups">`
dari modul mana pun yang mencoba menambah `implied_ids` ke grup tersebut akan
DILEWATI DIAM-DIAM pada setiap install dan update. Tidak ada galat, tidak ada
peringatan; hibahnya sekadar tidak pernah mendarat.

Pola ini disalin dari `custom_hms_base`, yang sudah menabraknya lebih dulu.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (grup LGX, grup yang disiratkan)
LGX_IMPLIED_GROUPS = [
    # Modul ini dibangun DI ATAS stock, bukan menggantikannya — jadi perannya
    # harus mewarisi peran stock, bukan hanya model lgx.*. Tanpa hibah ini
    # operator gudang tidak berhak membaca stock.picking sama sekali, dan
    # aplikasi pemindai menjawab 403 pada daftar tugas.
    ("custom_lgx_base.group_lgx_wh_operator", "stock.group_stock_user"),
    ("custom_lgx_base.group_lgx_wh_manager", "stock.group_stock_manager"),
]


class ResGroups(models.Model):
    _inherit = "res.groups"

    # @api.model WAJIB: <function> memanggilnya tanpa recordset, dan method
    # biasa akan gagal dengan "not enough values to unpack (expected at least
    # 1, got 0)" — pesan yang sama sekali tidak menunjuk ke dekorator yang hilang.
    @api.model
    def _lgx_apply_group_implications(self):
        """Terapkan LGX_IMPLIED_GROUPS secara idempoten.

        Grup yang tidak ada dilewati tanpa galat: basis data tanpa modul yang
        bersangkutan memang tidak punya hak untuk dihibahkan.
        """
        granted = 0
        for group_xmlid, implied_xmlid in LGX_IMPLIED_GROUPS:
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            implied = self.env.ref(implied_xmlid, raise_if_not_found=False)
            if not group or not implied:
                _logger.info("LGX: lewati hibah %s -> %s (grup tidak ada di basis data ini)",
                             group_xmlid, implied_xmlid)
                continue
            if implied in group.implied_ids:
                continue
            group.write({"implied_ids": [(4, implied.id)]})
            granted += 1
            _logger.info("LGX: %s sekarang menyiratkan %s", group_xmlid, implied_xmlid)
        return granted
