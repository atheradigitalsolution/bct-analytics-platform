# -*- coding: utf-8 -*-
"""Hibah grup: peran trucking LGX menyiratkan peran Fleet Odoo.

CACAT YANG DIPERBAIKI BERKAS INI
--------------------------------
Modul ini mengirim menu "Dokumen Kendaraan" beserta action-nya pada
`fleet.vehicle`, tetapi tidak satu pun grup trucking LGX punya hak baca model
itu. Akibatnya manajer trucking yang mengeklik menunya mendapat dialog
**Access Error** — menu yang kami kirim sendiri, gagal untuk peran yang justru
dibuat untuk memakainya.

Ditemukan dari tangkapan layar untuk materi presentasi, bukan dari uji: tidak
ada satu pun uji yang membuka menu itu sebagai pengguna non-admin, dan admin
kebetulan juga tidak punya grup Fleet — jadi tidak ada jalur yang pernah
menyentuhnya.

KENAPA NAMA METHOD-NYA BERBEDA DARI MILIK WMS
---------------------------------------------
`custom_lgx_wms` sudah punya `_lgx_apply_group_implications` pada `res.groups`.
Kalau berkas ini memakai nama yang SAMA, definisi modul yang dimuat belakangan
menimpa yang lebih dulu dan hibah WMS berhenti berjalan — tanpa galat, tanpa
peringatan, dan `<function>` milik WMS akan memanggil implementasi fleet dengan
daftar fleet. Gejalanya muncul jauh kemudian sebagai operator gudang yang
mendadak tidak berhak membaca `stock.picking`.

Dua modul yang menghibahkan grup harus memakai nama method yang berbeda, atau
berbagi satu daftar di satu tempat. Yang tidak boleh adalah dua method bernama
sama di model yang sama.

KENAPA <function> DAN BUKAN <record>
------------------------------------
Grup LGX lahir di `custom_lgx_base/security/lgx_groups.xml` di dalam
`<data noupdate="1">`. Flag itu tersimpan pada baris `ir.model.data` MILIK
GRUPNYA, jadi `<record model="res.groups">` dari modul mana pun yang menambah
`implied_ids` akan DILEWATI DIAM-DIAM pada setiap install dan update.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# (grup LGX, grup Fleet yang disiratkan)
LGX_FLEET_IMPLIED_GROUPS = [
    # Dispatcher menugaskan kendaraan ke trip; ia harus dapat MEMBACA armada.
    ("custom_lgx_base.group_lgx_trucking_dispatcher", "fleet.fleet_group_user"),
    # Manajer trucking memelihara master kendaraan: JBI, dimensi tipe, KIR,
    # STNK, Kartu Pengawasan. Itu pekerjaan administrator armada.
    ("custom_lgx_base.group_lgx_trucking_manager", "fleet.fleet_group_manager"),
]

# Pengemudi SENGAJA tidak ada di daftar ini. Ia sudah punya ACL baca yang
# sempit di custom_lgx_tms; memberinya fleet_group_user berarti hak melihat
# seluruh armada perusahaan, yang jauh melebihi kebutuhannya.


class ResGroups(models.Model):
    _inherit = "res.groups"

    # @api.model WAJIB: <function> memanggilnya tanpa recordset, dan method
    # biasa gagal dengan "not enough values to unpack" — pesan yang sama sekali
    # tidak menunjuk ke dekorator yang hilang.
    @api.model
    def _lgx_apply_fleet_group_implications(self):
        """Terapkan LGX_FLEET_IMPLIED_GROUPS secara idempoten."""
        granted = 0
        for group_xmlid, implied_xmlid in LGX_FLEET_IMPLIED_GROUPS:
            group = self.env.ref(group_xmlid, raise_if_not_found=False)
            implied = self.env.ref(implied_xmlid, raise_if_not_found=False)
            if not group or not implied:
                _logger.info("LGX fleet: lewati hibah %s -> %s (grup tidak ada)",
                             group_xmlid, implied_xmlid)
                continue
            if implied in group.implied_ids:
                continue
            group.write({"implied_ids": [(4, implied.id)]})
            granted += 1
            _logger.info("LGX fleet: %s sekarang menyiratkan %s",
                         group_xmlid, implied_xmlid)
        return granted
