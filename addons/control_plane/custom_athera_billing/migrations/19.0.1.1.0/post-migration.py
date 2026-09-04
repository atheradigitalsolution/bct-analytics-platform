# -*- coding: utf-8 -*-
"""Memuat ulang tiga surat penagihan sekali, supaya URL portal benar-benar sampai ke instalasi
yang sudah berjalan.

KENAPA SKRIP INI HARUS ADA.
`data/mail_template.xml` berada di dalam `<data noupdate="1">`, dan itu benar: teks yang sudah
disunting operator tidak boleh dikembalikan setiap kali modul di-upgrade. Konsekuensinya, sebuah
PERBAIKAN pada template tidak pernah sampai ke instalasi yang sudah berjalan — `-u` melewatinya
tanpa suara sama sekali.

Dan ia melewatinya lebih awal daripada yang biasa diduga. `odoo/tools/convert.py`:

    # in update mode, the record won't be updated if the data node explicitly
    # opt-out using @noupdate="1". A second check will be performed in
    # model._load_records() using the record's ir.model.data `noupdate` field.
    if self.noupdate and self.mode != 'init':
        ...
        if record := env['ir.model.data']._load_xmlid(xid):
            ...
            return None

`self.noupdate` di situ berasal dari ATRIBUT DI BERKAS, bukan dari kolom `ir_model_data.noupdate`.
Artinya melonggarkan flag di basis data tidak menghasilkan apa pun: record dilewati sebelum flag
itu sempat dibaca. Satu-satunya jalan yang tersisa adalah memuat berkasnya dalam `mode='init'`,
yang persis dilakukan di bawah — dan `_load_records` kemudian memasang kembali `noupdate=True`
dari atribut yang sama, jadi tidak ada keadaan yang perlu dipulihkan setelahnya.

APA YANG DIKORBANKAN, DISEBUT TERANG-TERANGAN.
Memuat ulang berarti menimpa badan ketiga surat dengan teks yang dikirim modul. Instalasi yang
teksnya sudah disunting tangan akan kehilangan suntingan itu. Pertukarannya diambil sadar: surat
penagihan yang tidak menyebut satu pun alamat menyuruh klien mencari sendiri ke mana ia harus
membayar, dan itu kegagalan yang lebih besar daripada satu kali kehilangan penyuntingan kata.

Penjaganya satu, dan sengaja sempit: kalau badan surat SUDAH memuat tautan portal, tidak ada yang
disentuh. Itu membuat skrip ini idempoten, dan membuat instalasi yang sudah menyelesaikan masalah
ini sendiri dibiarkan sendiri.
"""

import logging

from odoo import SUPERUSER_ID, api
from odoo.tools.convert import convert_file

_logger = logging.getLogger(__name__)

MODULE = "custom_athera_billing"
DATA_FILE = "data/mail_template.xml"

TEMPLATES = (
    "mail_template_invoice_issued",
    "mail_template_arrears_reminder",
    "mail_template_suspended",
)

#: Penanda bahwa badan surat sudah memuat tautan portal. `body_html` bertipe jsonb (satu entri
#: per bahasa), jadi pencocokan dilakukan atas teksnya.
MARKER = "athera_portal_url"


def migrate(cr, version):
    if not version:
        return  # instalasi baru: berkas data dimuat utuh, tidak ada yang perlu dipaksa.

    cr.execute(
        """
        SELECT d.name, t.body_html::text
          FROM ir_model_data d
          JOIN mail_template t ON t.id = d.res_id
         WHERE d.module = %s
           AND d.model  = 'mail.template'
           AND d.name   = ANY(%s)
        """,
        (MODULE, list(TEMPLATES)),
    )
    rows = cr.fetchall()
    if not rows:
        return  # belum pernah terpasang; tidak ada yang perlu diperbaiki.

    already = [name for name, body in rows if MARKER in (body or "")]
    if already:
        _logger.info(
            "billing: %s sudah memuat tautan portal; tiga surat dibiarkan apa adanya.",
            ", ".join(already),
        )
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    convert_file(env, MODULE, DATA_FILE, idref=None, mode="init", noupdate=False)
    _logger.info(
        "billing: tiga surat dimuat ulang dari %s; sekarang menyebut URL portal tagihan.",
        DATA_FILE,
    )
