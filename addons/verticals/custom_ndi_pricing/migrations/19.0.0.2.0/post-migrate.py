# -*- coding: utf-8 -*-
"""Perbaiki satuan ``ndi_hpp_snapshot`` pada baris penjualan yang sudah ada.

APA YANG SALAH. Sampai 19.0.0.1.0, snapshot diisi ``product.standard_price``
apa adanya. Nilai itu dinyatakan dalam satuan REFERENSI produk, sedangkan
``product_uom_qty`` dan ``price_unit`` pada baris dinyatakan dalam satuan
BARIS. Untuk NDI keduanya berbeda pada hampir setiap baris: pakan berbasis kg
dijual per "SAK 50 KG". Jadi ``qty * ndi_hpp_snapshot`` mengalikan jumlah sak
dengan biaya per kilogram, dan biayanya keluar 50 kali terlalu kecil.

KENAPA PERLU MIGRASI DAN BUKAN SEKADAR HITUNG ULANG. Snapshot itu beku: field
``compute`` tidak menyentuh baris pada order yang sudah dikonfirmasi, yang
memang tujuannya. Jadi memperbaiki kode saja membuat baris baru benar dan
meninggalkan seluruh riwayat salah.

KENAPA MENSKALA DAN BUKAN MEMBACA ULANG ``standard_price``. Membaca ulang akan
menilai penjualan Januari dengan biaya hari ini — persis kesalahan yang
keberadaan snapshot ini dimaksudkan untuk mencegah. Menskala dengan rasio
satuan mempertahankan biaya historisnya dan hanya memperbaiki satuannya.

IDEMPOTENSI. Skrip ini menskala, jadi menjalankannya dua kali akan salah.
Odoo menjalankan direktori migrasi tepat sekali per kenaikan versi, dan itulah
yang membuatnya aman; skrip ini tidak menambahkan penjaganya sendiri karena
penjaga yang menebak-nebak ("nilainya terlihat terlalu kecil") akan gagal justru
pada produk yang biayanya memang kecil.

POS TIDAK DISENTUH. ``pos_order_line`` tidak punya kolom UoM, kuantitasnya
selalu dalam satuan referensi produk, jadi barisnya tidak pernah terkena.
Terukur sebelum perbaikan: margin kotor kanal POS 17,6% melawan kanal sale
98,1% pada gudang data yang sama.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Rasio `factor` absolut kedua satuan. `uom_uom.factor` tersimpan (computed
    # dengan store=True), jadi SQL boleh membacanya langsung dan tidak ada baris
    # yang perlu dimuat ke memori.
    cr.execute(
        """
        UPDATE sale_order_line AS l
           SET ndi_hpp_snapshot = l.ndi_hpp_snapshot * lu.factor / pu.factor
          FROM product_product AS p
          JOIN product_template AS t ON t.id = p.product_tmpl_id
          JOIN uom_uom AS pu ON pu.id = t.uom_id,
               uom_uom AS lu
         WHERE p.id = l.product_id
           AND lu.id = l.product_uom_id
           AND lu.id <> pu.id
           AND pu.factor <> 0
           AND l.ndi_hpp_snapshot IS NOT NULL
           AND l.ndi_hpp_snapshot <> 0
        """
    )
    _logger.info(
        "custom_ndi_pricing: %s baris penjualan disetel ulang ke satuan barisnya "
        "(ndi_hpp_snapshot sebelumnya dalam satuan referensi produk).",
        cr.rowcount,
    )
