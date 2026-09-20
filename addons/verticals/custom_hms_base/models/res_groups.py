# -*- coding: utf-8 -*-
"""Hibah hak antar-modul yang tidak bisa dinyatakan sebagai record XML.

`noupdate` melekat pada baris ``ir.model.data`` milik RECORD, bukan pada modul
yang menulisnya. Semua grup SIMRS lahir di dalam blok ``<data noupdate="1">``
di ``security/hms_groups.xml``, jadi setiap ``<record model="res.groups">``
yang mencoba menambah ``implied_ids`` ke grup itu — **dari modul mana pun,
termasuk custom_hms_base sendiri** — dilewati diam-diam pada setiap install
dan setiap update. Sumbernya terbaca seolah hak sudah diberikan; basis
datanya bilang tidak.

Karena itu hibahnya ditulis imperatif di sini dan dipanggil lewat ``<function>``
pada blok data **tanpa** ``noupdate`` (lihat
``security/hms_group_implications.xml``). Pilihan itu disengaja:

* ``post_init_hook`` hanya berjalan saat **install**. ``custom_hms_base``
  sudah terpasang di setiap basis data SIMRS yang ada, jadi hook tidak akan
  pernah jalan lagi di sana — haknya tidak akan pernah mendarat.
* ``<function>`` di luar ``noupdate`` dijalankan ulang pada setiap ``-u``
  (lihat ``odoo/tools/convert.py::_tag_function``: ia hanya dilewati bila
  ``noupdate`` dan mode bukan ``init``). Jadi hibahnya mendarat pada basis
  data yang sudah ada, **dan** tetap mendarat pada install bersih.
* Penulisannya idempoten dan hanya menambah (``(4, id)``), tidak pernah
  mengganti daftar, sehingga ``-u`` berikutnya tidak bisa menghapusnya.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (grup SIMRS, grup Odoo yang disiratkan). Memakai XML-ID supaya modul yang
# belum terpasang bisa dilewati dengan anggun, tanpa memaksa `depends` baru.
HMS_IMPLIED_GROUPS = [
    # Manajemen membaca laporan P&L per unit, dan laporan itu berdiri di atas
    # account.analytic.line. Tanpa hibah ini `/api/v1/reports/unit-pnl`
    # menjawab 403 untuk SETIAP peran — fitur yang tidak bisa dipakai siapa
    # pun, bukan fitur yang aman.
    ("custom_hms_base.group_hms_manager", "analytic.group_analytic_accounting"),
]


class ResGroups(models.Model):
    _inherit = "res.groups"

    @api.model
    def _hms_apply_group_implications(self):
        """Terapkan HMS_IMPLIED_GROUPS secara idempoten.

        Modul yang tidak ada (mis. `analytic` belum terpasang) dilewati tanpa
        error: basis data tanpa akuntansi analitik memang tidak punya laporan
        P&L untuk diamankan.
        """
        granted = 0
        for group_xmlid, implied_xmlid in HMS_IMPLIED_GROUPS:
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            implied = self.env.ref(implied_xmlid, raise_if_not_found=False)
            if not group or not implied:
                _logger.info(
                    "SIMRS: lewati hibah %s -> %s (grup tidak ada di basis data ini)",
                    group_xmlid, implied_xmlid,
                )
                continue
            if implied in group.implied_ids:
                continue
            group.write({"implied_ids": [(4, implied.id)]})
            granted += 1
            _logger.info("SIMRS: %s sekarang menyiratkan %s", group_xmlid, implied_xmlid)
        return granted
