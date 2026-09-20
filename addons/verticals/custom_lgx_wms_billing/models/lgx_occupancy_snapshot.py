# -*- coding: utf-8 -*-
"""Potret okupansi harian — model paling sensitif terhadap volume di sistem ini.

Penyimpanan ditagih atas RUANG DIKALI WAKTU. Saldo akhir bulan tidak cukup:
sebuah pallet yang masuk tanggal 3 dan keluar tanggal 27 tidak muncul sama
sekali di saldo akhir bulan, padahal ia menempati rak selama 24 hari.

TIGA KEPUTUSAN YANG DIAMBIL DI DEPAN
------------------------------------
1. **Idempotensi ditegakkan Postgres.** Unique constraint pada
   (date, client, product, location, lot). Cron yang "hati-hati" tidak cukup:
   cron dijalankan ulang manual saat ada yang salah, dan itulah saat baris
   ganda lahir — lalu tagihan bulan itu dua kali lipat.
2. **Indeks pada (date, client_id)** sejak baris pertama. Perkiraan volume:
   SKU aktif × lokasi terisi × 365 per tahun. Menambah indeks setelah tabel
   berisi jutaan baris adalah operasi yang mengunci tabel.
3. **Retensi 13 bulan** detail harian, lalu diringkas bulanan. Tanpa retensi,
   tabel ini tumbuh selamanya dan performa memburuk beberapa bulan SETELAH
   go-live — saat tidak ada lagi yang menghubungkannya dengan keputusan desain.
"""
from odoo import _, api, fields, models


class LgxWmsOccupancySnapshot(models.Model):
    _name = "lgx.wms.occupancy.snapshot"
    _description = "Potret Okupansi Harian Gudang"
    _order = "date desc, client_id, product_id"
    _rec_name = "date"

    date = fields.Date("Tanggal", required=True, index=True)
    client_id = fields.Many2one("lgx.wms.client", "Klien", required=True, index=True,
                                ondelete="cascade")
    owner_id = fields.Many2one("res.partner", "Pemilik Stok", index=True)
    company_id = fields.Many2one(related="client_id.company_id", store=True, index=True)
    location_id = fields.Many2one("stock.location", "Lokasi", index=True)
    product_id = fields.Many2one("product.product", "Produk", required=True, index=True)
    lot_id = fields.Many2one("stock.lot", "Lot / Serial")

    quantity = fields.Float("Kuantitas")
    uom_id = fields.Many2one("uom.uom", "Satuan")
    pallet_count = fields.Float(
        "Jumlah Pallet",
        help="Dihitung dari faktor konversi produk, bukan dari identitas pallet. "
             "Granularitas per produk dipilih karena per pallet menggandakan "
             "volume tabel tanpa menambah apa pun yang ditagihkan — kecuali bila "
             "kontrak memang menuntutnya.",
    )
    volume_cbm = fields.Float("Volume (CBM)")
    weight_kg = fields.Float("Berat (kg)")
    is_free_period = fields.Boolean(
        "Dalam Masa Bebas",
        help="Diisi oleh proses PENAGIHAN, bukan oleh cron potret. Potret merekam "
             "apa yang ada di gudang; penagihan yang memutuskan hari mana yang "
             "ditagihkan. Memutuskannya saat memotret berarti mengubah masa bebas "
             "klien tidak lagi dapat diterapkan surut.",
    )
    billing_run_id = fields.Many2one("lgx.wms.billing.run", "Proses Penagihan", index=True,
                                     ondelete="set null",
                                     help="Terisi setelah hari ini ikut ditagihkan. Inilah yang "
                                          "membuat tagihan dapat ditelusuri kembali ke okupansinya.")

    _snapshot_uniq = models.Constraint(
        "unique(date, client_id, product_id, location_id, lot_id)",
        "Potret okupansi untuk kombinasi tanggal, klien, produk, lokasi dan lot ini sudah ada.",
    )
    _quantity_non_negative = models.Constraint(
        "check(quantity >= 0)", "Kuantitas potret tidak boleh negatif.",
    )
    _date_client_index = models.Index("(date, client_id)")

    @api.model
    def _cron_take_snapshot(self, for_date=None):
        """Ambil potret untuk satu tanggal. Idempoten.

        Dijalankan pada jam sepi. Menjalankan ulang untuk tanggal yang sama
        MEMPERBARUI baris yang ada — dan itu bukan sekadar niat baik cron:
        constraint unik di Postgres membuat penggandaan mustahil.
        """
        target = for_date or fields.Date.context_today(self)
        Client = self.env["lgx.wms.client"]
        Quant = self.env["stock.quant"]
        clients = Client.search([("state", "=", "active")])
        written = 0
        for client in clients:
            quants = Quant.search([
                ("owner_id", "=", client.owner_partner_id.id),
                ("quantity", ">", 0),
                ("location_id.usage", "=", "internal"),
            ])
            for quant in quants:
                product = quant.product_id
                pallets = client._lgx_pallet_equivalent(product, quant.quantity)
                vals = {
                    "date": target,
                    "client_id": client.id,
                    "owner_id": client.owner_partner_id.id,
                    "location_id": quant.location_id.id,
                    "product_id": product.id,
                    "lot_id": quant.lot_id.id or False,
                    "quantity": quant.quantity,
                    "uom_id": product.uom_id.id,
                    "pallet_count": pallets,
                    "volume_cbm": quant.quantity * (product.volume or 0.0),
                    "weight_kg": quant.quantity * (product.weight or 0.0),
                }
                existing = self.search([
                    ("date", "=", target),
                    ("client_id", "=", client.id),
                    ("product_id", "=", product.id),
                    ("location_id", "=", quant.location_id.id),
                    ("lot_id", "=", quant.lot_id.id or False),
                ], limit=1)
                if existing:
                    if not existing.billing_run_id:
                        existing.write(vals)
                else:
                    self.create(vals)
                written += 1
        return written

    @api.model
    def _cron_prune_snapshots(self):
        """Buang detail harian yang lebih tua dari masa retensi.

        Hanya baris yang SUDAH ikut ditagihkan yang dibuang; baris yang belum
        pernah masuk proses penagihan dipertahankan apa pun umurnya, karena
        membuangnya berarti menghapus dasar tagihan yang belum terbit.
        """
        months = self.env["ir.config_parameter"].sudo().lgx_int("lgx.occupancy_retention_months", 13)
        cutoff = fields.Date.subtract(fields.Date.context_today(self), months=months)
        stale = self.search([("date", "<", cutoff), ("billing_run_id", "!=", False)])
        count = len(stale)
        stale.unlink()
        return count
