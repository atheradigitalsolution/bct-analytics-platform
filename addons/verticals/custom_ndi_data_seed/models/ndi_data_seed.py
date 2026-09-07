# -*- coding: utf-8 -*-
"""Sample data PT Nutrisi Daya Indonesia: master, BOM, dan 12 bulan transaksi.

Modul ini mengisi database ``ndi`` dengan data contoh yang **benar-benar mengalir**:
bahan dibeli, dikonsumsi produksi, produk jadi masuk gudang, dipindahkan ke outlet,
lalu dijual kredit dan tunai. Bukan tabel yang diisi supaya tidak kosong.

Empat sifat yang wajib dimiliki, dan dari mana masing-masing datang — polanya
diambil apa adanya dari ``custom_demo_seed``, yang sudah membayar harga pelajaran
ini:

* **Idempoten.** Setiap record dibuat lewat :meth:`_ensure`, yang mendaftarkan
  external ID ``ir.model.data``. Jalan kedua tidak membuat baris baru. Ini juga
  yang membuat generator **bisa dilanjutkan**: kalau bulan ke-7 gagal, perbaiki
  lalu jalankan ulang — enam bulan pertama dilewati, bukan digandakan.
* **Reproducible.** Seluruh keacakan berasal dari satu ``random.Random(seed)``.
* **Jujur tentang bentuknya.** Aturan otoritas-parameter: bentuk penuh sebuah
  dataset dicatat saat pertama dibuat, dan panggilan berikutnya dengan bentuk
  berbeda **menolak** dan menyebut setiap parameter yang bentrok. Tanpa itu,
  memanggil ``generate(months=3)`` di atas dataset 12 bulan akan mengembalikan 12
  bulan diam-diam, dan pemanggilnya tidak punya cara tahu.
* **Tidak menghasilkan apa pun saat install.** Data muncul hanya ketika
  ``generate()`` dipanggil eksplisit. Modul ini bukan ``auto_install`` dan tidak
  ada modul yang bergantung padanya.

Urutan yang load-bearing
------------------------
**Beli dulu, produksi kemudian, jual terakhir** — di dalam setiap bulan, dan dalam
urutan itu. Odoo tidak menolak konsumsi yang melebihi stok; ia membuat kuant
negatif dan diam. Kalau produksi berjalan sebelum penerimaan, hasilnya bukan galat
melainkan sample data yang setiap laporan persediaannya salah. Karena itu:

1. kebutuhan bahan satu bulan dihitung lebih dulu dari rencana produksi bulan itu;
2. PO bulan itu dibuat dan diterima untuk menutup kebutuhan tersebut plus penyangga;
3. baru MO dijalankan, dan setiap MO **diperiksa** ``reservation_state == 'assigned'``
   sebelum diselesaikan — kalau bahan kurang, generator berhenti dengan galat, bukan
   melanjutkan dan meninggalkan stok minus;
4. baris penjualan dan POS dipotong terhadap ``free_qty`` di lokasi asalnya, jadi
   dokumen yang dibuat selalu bisa dipenuhi.

Kenapa empat ``stock.warehouse`` dan bukan empat ``stock.location``
-------------------------------------------------------------------
Spesifikasi §1.1 meminta empat lokasi: gudang bahan baku, gudang produk jadi, dan
dua outlet retail. Membuatnya sebagai empat lokasi anak di bawah satu gudang
memaksa setiap dokumen menimpa ``location_id``/``location_dest_id`` hasil rute
Odoo satu per satu — pada penerimaan pembelian, pada pengiriman penjualan, dan
pada POS — dan setiap tempat yang terlewat diam-diam memakai WH/Stock. Sebagai
``stock.warehouse``, tiap lokasi membawa tipe operasi dan lokasi stoknya sendiri,
sehingga ``purchase.order.picking_type_id``, ``sale.order.warehouse_id`` dan
``pos.config.picking_type_id`` sudah menunjuk ke tempat yang benar tanpa satu pun
penimpaan manual. Gudang bawaan ``WH`` sengaja tidak dipakai dan dibiarkan kosong.
"""

import csv
import json
import logging
import math
import random
import re
from datetime import date, datetime, time, timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import file_path

_CSV_CACHE = {}

_logger = logging.getLogger(__name__)

MODULE = "custom_ndi_data_seed"
MASTER_MODULE = "custom_ndi_master"

DEFAULT_DATASET = "prod"

#: Sama seperti ``custom_demo_seed``: huruf kecil dan angka, tanpa garis bawah,
#: karena prefix external ID-nya ``<dataset>__`` dan garis bawah membuatnya ambigu.
DATASET_RE = re.compile(r"^[a-z][a-z0-9]{0,19}$")

SHAPE_PARAM = "custom_ndi_data_seed.shape.%s"

#: Parameter yang mendefinisikan bentuk sebuah dataset. Beda satu saja = dataset lain.
SHAPE_KEYS = (
    "seed",
    "start",
    "months",
    "mo_per_month",
    "po_per_month",
    "so_per_month",
    "pos_orders",
    "transfers_per_month",
    "draft_mo",
    "waste_mo",
    "partial_receipts",
    "company_id",
)

# ---------------------------------------------------------------------------
# Pemetaan UoM
# ---------------------------------------------------------------------------

#: Satuan dasar per kode ``satuan_dasar`` di master produk.
BASE_UOM_XMLID = {
    "KG": "uom.product_uom_kgm",
    "PCS": "%s.uom_pcs" % MASTER_MODULE,
    "BTL": "%s.uom_btl" % MASTER_MODULE,
    "JRG": "%s.uom_jrg" % MASTER_MODULE,
    "SCH": "%s.uom_sch" % MASTER_MODULE,
    "CONE": "%s.uom_cone" % MASTER_MODULE,
    "SAK": "%s.uom_sak_hitung" % MASTER_MODULE,
}

#: Satuan kemasan tingkat 2, dikunci pada (nama, faktor, satuan dasar). Nama saja
#: tidak cukup: "SAK" ada tiga (50/30/25 KG) dan "DUS" ada empat isi yang berbeda.
#: Inilah kesalahan yang membuat berat surat jalan meleset 400 kg per ton.
TIER2_UOM_XMLID = {
    ("SAK", 50, "KG"): "%s.uom_sak_50kg" % MASTER_MODULE,
    ("SAK", 30, "KG"): "%s.uom_sak_30kg" % MASTER_MODULE,
    ("SAK", 25, "KG"): "%s.uom_sak_25kg" % MASTER_MODULE,
    ("DRUM", 200, "KG"): "%s.uom_drum_200kg" % MASTER_MODULE,
    ("DRUM", 250, "KG"): "%s.uom_drum_250kg" % MASTER_MODULE,
    ("BAL", 1000, "PCS"): "%s.uom_bal_1000pcs" % MASTER_MODULE,
    ("ROLL", 500, "PCS"): "%s.uom_roll_500pcs" % MASTER_MODULE,
    ("DUS", 100, "PCS"): "%s.uom_dus_100pcs" % MASTER_MODULE,
    ("DUS", 12, "BTL"): "%s.uom_dus_12btl" % MASTER_MODULE,
    ("DUS", 4, "JRG"): "%s.uom_dus_4jrg" % MASTER_MODULE,
    ("DUS", 50, "SCH"): "%s.uom_dus_50sch" % MASTER_MODULE,
    ("DUS", 12, "CONE"): "%s.uom_dus_12cone" % MASTER_MODULE,
    ("TON", 50, "SAK"): "%s.uom_ton_50sak" % MASTER_MODULE,
}

#: Satuan tingkat 3. "TON" NDI berarti 20 sak, bukan tonne metrik, jadi isinya
#: bergantung pada ukuran sak di tingkat 2: 20 x 50 KG = 1.000 kg, 20 x 30 KG = 600 kg.
TIER3_UOM_XMLID = {
    ("TON", 20, 50): "%s.uom_ton_20sak_50kg" % MASTER_MODULE,
    ("TON", 20, 30): "%s.uom_ton_20sak_30kg" % MASTER_MODULE,
}

# ---------------------------------------------------------------------------
# Wilayah, gudang, unit operasi
# ---------------------------------------------------------------------------

#: Kota -> wilayah pemasaran (``res.partner.ndi_sales_region``, addendum K-3).
CITY_REGION = {
    "Sidoarjo": "sidoarjo_raya",
    "Mojokerto": "sidoarjo_raya",
    "Pasuruan": "sidoarjo_raya",
    "Surabaya": "surabaya_raya",
    "Gresik": "surabaya_raya",
    "Malang": "malang_raya",
    "Batu": "malang_raya",
    "Kediri": "kediri_raya",
    "Nganjuk": "kediri_raya",
    "Jombang": "kediri_raya",
    "Tulungagung": "kediri_raya",
    "Blitar": "kediri_raya",
    "Jember": "tapal_kuda",
    "Banyuwangi": "tapal_kuda",
    "Lamongan": "pantura_jatim",
    "Tuban": "pantura_jatim",
    "Jakarta Timur": "luar_jatim",
}

#: (kunci, kode gudang, nama, kota). Kode ``stock.warehouse`` maksimal 5 karakter.
WAREHOUSES = [
    ("gbb", "GBB", "Gudang Bahan Baku Sidoarjo", "Sidoarjo"),
    ("gpj", "GPJ", "Gudang Produk Jadi Sidoarjo", "Sidoarjo"),
    ("osd", "OSD", "Outlet Retail Sidoarjo", "Sidoarjo"),
    ("oml", "OML", "Outlet Retail Malang", "Malang"),
]

#: (kunci, kode, nama). Dimensi ``operating.unit`` yang di-stamp ke sale.order,
#: account.move, stock.picking dan pos.order oleh ``custom_operating_unit``.
OPERATING_UNITS = [
    ("pabrik", "PBR-SDA", "Pabrik dan Gudang Sidoarjo"),
    ("osd", "OUT-SDA", "Outlet Retail Sidoarjo"),
    ("oml", "OUT-MLG", "Outlet Retail Malang"),
]

# ---------------------------------------------------------------------------
# Rencana pembelian
# ---------------------------------------------------------------------------

#: 22 PO per bulan (spesifikasi §6.2), dengan enam PO jagung mingguan dari dua
#: pemasok dan dua PO SBM berkontainer. Setiap entri: (kunci, kode supplier,
#: [(SKU, porsi kebutuhan bulan itu)]).
#:
#: Jagung sengaja dipasok DUA supplier dan dedak juga dua: itu kasus uji G-16,
#: "satu field Supplier pada Master Produk tidak cukup".
PO_PLAN = [
    ("jagung1", "SUP-001", [("RM-JGP-01", 0.20)]),
    ("jagung2", "SUP-002", [("RM-JGP-01", 0.15), ("RM-JGP-02", 1.0)]),
    ("jagung3", "SUP-001", [("RM-JGP-01", 0.20)]),
    ("jagung4", "SUP-002", [("RM-JGP-01", 0.15)]),
    ("jagung5", "SUP-001", [("RM-JGP-01", 0.20)]),
    ("jagung6", "SUP-002", [("RM-JGP-01", 0.10)]),
    ("sbm1", "SUP-003", [("RM-SBM-01", 0.60)]),
    ("sbm2", "SUP-003", [("RM-SBM-01", 0.40), ("RM-SBM-02", 1.0), ("RM-DGS-01", 1.0)]),
    ("nabati1", "SUP-003", [("RM-BKK-01", 1.0)]),
    ("dedak1", "SUP-002", [("RM-DDK-01", 0.50), ("RM-DDK-02", 1.0)]),
    ("dedak2", "SUP-010", [("RM-DDK-01", 0.50)]),
    ("ikan1", "SUP-004", [("RM-TIK-01", 1.0), ("RM-TIK-02", 1.0)]),
    ("mbm1", "SUP-005", [("RM-MBM-01", 1.0)]),
    ("cair1", "SUP-006", [("RM-CPO-01", 1.0), ("RM-MOL-01", 1.0), ("RM-PKM-01", 1.0)]),
    ("mineral1", "SUP-007", [("RM-LMS-01", 1.0), ("RM-LMS-02", 1.0)]),
    ("mineral2", "SUP-007", [("RM-DCP-01", 1.0), ("RM-MCP-01", 1.0), ("RM-GRM-01", 1.0)]),
    ("aditif1", "SUP-008", [("RM-PMX-01", 1.0), ("RM-PMX-02", 1.0), ("RM-TXB-01", 1.0)]),
    ("aditif2", "SUP-008", [("RM-MET-01", 1.0), ("RM-LYS-01", 1.0), ("RM-THR-01", 1.0),
                            ("RM-ENZ-01", 1.0), ("RM-CHL-01", 1.0)]),
    ("kemasan1", "SUP-009", [("PK-KRG-50N", 1.0), ("PK-INN-50", 1.0)]),
    ("kemasan2", "SUP-009", [("PK-KRG-30N", 1.0), ("PK-INN-30", 1.0),
                             ("PK-LBL-01", 1.0), ("PK-BNG-01", 1.0)]),
    ("dagangan1", "SUP-011", [("TR-VIT-01", 1.0), ("TR-DES-01", 1.0), ("TR-OBT-01", 1.0)]),
    ("dagangan2", "SUP-012", [("TR-SKM-01", 1.0), ("TR-EGG-01", 1.0),
                              ("PK-PLT-01", 1.0), ("PK-KRG-50", 1.0)]),
]

#: SKU yang tidak muncul di satu pun BOM tetap harus ada stoknya — barang dagangan
#: dijual di outlet, dan bahan alternatif (jagung KA 18%, SBM lokal, MCP) ada di
#: master justru supaya demo punya lebih dari satu pilihan bahan. Kuantitas per
#: bulan dalam satuan dasar produk.
FIXED_MONTHLY_QTY = {
    "RM-JGP-02": 4000.0,
    "RM-SBM-02": 2000.0,
    "RM-DDK-02": 2000.0,
    "RM-MCP-01": 400.0,
    "PK-KRG-50": 2000.0,
    "PK-PLT-01": 20.0,
    "TR-VIT-01": 120.0,
    "TR-DES-01": 40.0,
    "TR-OBT-01": 300.0,
    "TR-SKM-01": 250.0,
    "TR-EGG-01": 400.0,
}

#: Bahan yang harganya bergerak antar bulan (spesifikasi §8.1). Tanpa ini,
#: skenario 7 (re-costing setelah jagung naik) tidak punya riwayat harga apa pun
#: untuk dibandingkan.
VOLATILE_SKUS = ("RM-JGP-01", "RM-JGP-02", "RM-SBM-01", "RM-DDK-01", "RM-DDK-02")

#: SKU -> kode pemasok, diturunkan dari rencana pembelian supaya pembelian
#: susulan tetap jatuh ke pemasok yang benar dan tidak mengarang pemasok baru.
SKU_SUPPLIER = {}
for _key, _supplier_code, _lines in PO_PLAN:
    for _sku, _share in _lines:
        SKU_SUPPLIER.setdefault(_sku, _supplier_code)

#: Susut normal pabrik pakan: sisa di mixer, debu, dan tumpahan saat pengarungan.
#: Pasal 11 menyerapnya ke hasil produksi aktual -- bahan tetap habis sesuai
#: formula, hasilnya yang kurang. Segitiga (0 - 3,5%, modus 0,8%): mayoritas batch
#: nyaris penuh, ekornya panjang ke bawah. Versi pertama generator ini memakai
#: hasil = target persis, dan akibatnya grafik yield adalah garis datar 100% --
#: metrik benar, kueri benar, tetapi datanya tidak punya apa pun untuk ditunjukkan.
NORMAL_WASTE = (0.0, 0.035, 0.008)

#: Abnormal waste (``R-PRD-09``): 5-9% hilang, jauh di luar sebaran normal, dan
#: dicatat terpisah sebagai ``stock.scrap`` bahan baku. Dibuat benar-benar berbeda
#: supaya klaim "abnormal waste dicatat terpisah" bisa dibuktikan dari data, bukan
#: hanya dari kode.
ABNORMAL_WASTE = (0.05, 0.09)

#: Penyangga pembelian di atas kebutuhan produksi bulan berjalan. Bulan pertama
#: lebih tebal karena ia juga membentuk stok awal.
BUFFER_FIRST_MONTH = 1.45
BUFFER_MONTH = 1.12

# ---------------------------------------------------------------------------
# Rencana produksi dan penjualan
# ---------------------------------------------------------------------------

#: Kebutuhan kemasan per batch (spesifikasi §3.1). Bukan baris formula: kolom
#: persen wajib berjumlah 100 dan kemasan bukan bagian dari formula bahan. Tetap
#: masuk BOM sebagai baris ber-``ndi_persen`` 0, karena tanpa itu produksi tidak
#: mengonsumsi karung dan HPP kehilangan komponen kemasan yang direkonsiliasi
#: UJI 5 spesifikasi.
PACKAGING_FOR_SAK = {
    50: ("PK-KRG-50N", "PK-INN-50"),
    30: ("PK-KRG-30N", "PK-INN-30"),
}
BENANG_CONE_PER_SAK = 0.0005

#: Sebaran ukuran order per tipe pelanggan, dalam SAK per baris.
ORDER_SIZE = {
    "distributor": (40, 120),
    "poultry_shop": (12, 45),
    "peternak": (4, 20),
}

#: Siklus tipe pelanggan untuk order penjualan. Siklus, bukan blok berurutan
#: ("8 distributor lalu 11 poultry shop lalu 11 peternak"): begitu
#: ``so_per_month`` diturunkan di bawah 30, bentuk blok memotong tepat di tengah
#: dan tipe terakhir hilang sama sekali dari data. Persyaratan "keempat tipe
#: pelanggan bertransaksi" tidak boleh bergantung pada nilai satu parameter volume.
SO_CYCLE = [
    "distributor", "poultry_shop", "peternak", "poultry_shop", "peternak",
    "distributor", "peternak", "poultry_shop", "peternak", "poultry_shop",
]




def _read_csv(filename):
    """Baca CSV bawaan modul, sekali saja per proses.

    Di-cache karena ``month_requirement`` memanggil ``_bom_rows`` sekali per bulan
    dan tanpa cache berkas yang sama dibaca dua belas kali untuk jawaban yang tidak
    berubah.
    """
    if filename not in _CSV_CACHE:
        path = file_path("%s/data/%s" % (MODULE, filename))
        with open(path, encoding="utf-8-sig", newline="") as handle:
            _CSV_CACHE[filename] = list(csv.DictReader(handle))
    return _CSV_CACHE[filename]


def _f(row, key):
    """Kolom CSV -> float. Kolom kosong berarti 0, bukan galat."""
    value = (row.get(key) or "").strip()
    return float(value) if value else 0.0


class NdiSeedRun:
    """Satu jalannya generator.

    Objek Python biasa, bukan recordset: ia menyimpan state (peta produk, gudang,
    ledger stok bayangan) selama satu jalan, dan menaruh state seperti itu pada
    recordset Odoo berarti bertabrakan dengan atribut internal ``BaseModel``.
    """

    def __init__(self, env, company, ds, shape, today, commit=True):
        self.env = env
        self.company = company
        self.ds = ds
        self.shape = shape
        self.rng = random.Random(shape["seed"])
        self.today = today
        self.commit = commit
        self.products = {}        # sku -> product.template
        self.variants = {}        # sku -> product.product
        self.rows = {}            # sku -> baris CSV master
        self.customers = {}       # kode -> res.partner
        self.suppliers = {}       # kode -> res.partner
        self.warehouses = {}      # kunci -> stock.warehouse
        self.wh_city = {}         # kunci -> kota gudang
        self.units = {}           # kunci -> operating.unit
        self.boms = {}            # sku -> mrp.bom
        self.pos_configs = {}     # kunci outlet -> pos.config
        self.uom_kg = env.ref("uom.product_uom_kgm")

    # -- idempotensi ----------------------------------------------------

    def ensure(self, xmlid, model, values):
        existing = self.exists(xmlid)
        if existing:
            return existing
        return self.tag(xmlid, self.env[model].create(values))

    def exists(self, xmlid):
        return self.env.ref("%s.%s%s" % (MODULE, self.ds["prefix"], xmlid),
                            raise_if_not_found=False)

    def tag(self, xmlid, record):
        self.env["ir.model.data"].create({
            "module": MODULE,
            "name": self.ds["prefix"] + xmlid,
            "model": record._name,
            "res_id": record.id,
            "noupdate": True,
        })
        return record

    def checkpoint(self, label):
        """Commit di batas fase.

        Satu transaksi untuk 12 bulan berarti satu galat di bulan ke-12 membuang
        semuanya, dan RAM host ini tidak muat menahan seluruh cache ORM selama
        itu. Efek sampingnya justru yang diinginkan: generator jadi bisa
        dilanjutkan setelah gagal, karena setiap record sudah punya external ID.
        """
        if not self.commit:
            return
        self.env.flush_all()
        self.env.cr.commit()
        self.env.invalidate_all()
        _logger.info("custom_ndi_data_seed: checkpoint %s", label)

    def moment(self, day, hour_lo=8, hour_hi=16):
        """Tanggal -> datetime jam kerja, dijepit ke hari ini.

        Dijepit karena jendela 12 bulan spesifikasi (Okt 2025 - Sep 2026) berakhir
        setelah tanggal berjalan. Memposting jurnal bertanggal masa depan bukan
        cuma janggal di layar; ia membuat laporan periode berjalan memuat baris
        yang belum terjadi.
        """
        if day > self.today:
            day = self.today
        return datetime.combine(day, time(
            hour=self.rng.randint(hour_lo, hour_hi),
            minute=self.rng.randint(0, 59),
            second=self.rng.randint(0, 59),
        ))

    # ==================================================================
    # Master: divisi, kategori, produk
    # ==================================================================

    @staticmethod
    def _slug(value):
        return re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")

    def _uom_tree(self, row):
        """(satuan dasar, tingkat 2, tingkat 3) sebagai record ``uom.uom``.

        Dikunci pada nama DAN faktor DAN satuan induknya. "SAK" saja ambigu (50,
        30, 25 KG) dan "TON" saja lebih parah lagi: 20 sak 50 kg = 1.000 kg
        sedangkan 20 sak 30 kg = 600 kg. Salah pilih di sini membuat berat surat
        jalan puyuh dan kambing meleset 400 kg per ton.
        """
        base_code = row["satuan_dasar"].strip()
        base = self.env.ref(BASE_UOM_XMLID[base_code])

        tier2 = None
        name2 = (row.get("satuan2") or "").strip()
        conv2 = int(_f(row, "konversi2")) if name2 else 0
        if name2:
            key = (name2, conv2, base_code)
            if key not in TIER2_UOM_XMLID:
                raise UserError(_(
                    "Satuan tingkat 2 %(name)s isi %(conv)s di atas %(base)s (SKU %(sku)s) "
                    "tidak ada di pohon UoM custom_ndi_master.",
                    name=name2, conv=conv2, base=base_code, sku=row["sku"],
                ))
            tier2 = self.env.ref(TIER2_UOM_XMLID[key])

        tier3 = None
        name3 = (row.get("satuan3") or "").strip()
        conv3 = int(_f(row, "konversi3")) if name3 else 0
        if name3:
            key = (name3, conv3, conv2)
            if key not in TIER3_UOM_XMLID:
                raise UserError(_(
                    "Satuan tingkat 3 %(name)s isi %(conv)s di atas %(name2)s %(conv2)s "
                    "(SKU %(sku)s) tidak ada di pohon UoM custom_ndi_master.",
                    name=name3, conv=conv3, name2=name2, conv2=conv2, sku=row["sku"],
                ))
            tier3 = self.env.ref(TIER3_UOM_XMLID[key])

        return base, tier2, tier3

    def build_divisions(self):
        """Divisi dan kategori dari kolom master.

        Divisi sudah disemai ``custom_ndi_master`` lewat external ID-nya sendiri;
        yang dicari di sini adalah nama, supaya baris CSV yang menyebut divisi
        yang sudah ada tidak membuat duplikat dengan nama sama (dan gagal pada
        constraint UNIQUE-nya).
        """
        Division = self.env["ndi.division"]
        Category = self.env["ndi.product.category"]
        seen_div, seen_cat = {}, {}
        for row in _read_csv("ndi_master_produk.csv"):
            div_name = row["divisi"].strip()
            if div_name not in seen_div:
                division = Division.search([("name", "=", div_name)], limit=1)
                if not division:
                    division = self.ensure(
                        "division_%s" % self._slug(div_name), "ndi.division",
                        {"name": div_name, "code": div_name[:4].upper()},
                    )
                seen_div[div_name] = division
            division = seen_div[div_name]

            cat_name = row["kategori"].strip()
            cat_key = (division.id, cat_name)
            if cat_key not in seen_cat:
                category = Category.search(
                    [("name", "=", cat_name), ("division_id", "=", division.id)], limit=1
                )
                if not category:
                    category = self.ensure(
                        "category_%s_%s" % (self._slug(div_name), self._slug(cat_name)),
                        "ndi.product.category",
                        {"name": cat_name, "division_id": division.id},
                    )
                seen_cat[cat_key] = category
        return seen_div, seen_cat

    def _taxes(self):
        Tax = self.env["account.tax"]
        domain = [("company_id", "=", self.company.id)]
        sale_exempt = Tax.search(domain + [("type_tax_use", "=", "sale"), ("amount", "=", 0.0),
                                           ("name", "like", "EXEMPT")], limit=1)
        sale_12 = Tax.search(domain + [("type_tax_use", "=", "sale"), ("amount", "=", 12.0),
                                       ("name", "=", "12%")], limit=1)
        buy_exempt = Tax.search(domain + [("type_tax_use", "=", "purchase"), ("amount", "=", 0.0),
                                          ("name", "like", "EXEMPT")], limit=1)
        buy_12 = Tax.search(domain + [("type_tax_use", "=", "purchase"), ("amount", "=", 12.0),
                                      ("name", "=", "12%")], limit=1)
        if not (sale_exempt and sale_12):
            raise UserError(_(
                "Pajak jual 0%% EXEMPT dan 12%% dari l10n_id tidak ditemukan. Pakan ternak "
                "dibebaskan PPN sedangkan barang dagangan kena 12%%, dan sample data harus "
                "memperagakan keduanya pada satu faktur (skenario 8)."
            ))
        return sale_exempt, sale_12, buy_exempt, buy_12

    def build_products(self, divisions, categories):
        sale_exempt, sale_12, buy_exempt, buy_12 = self._taxes()
        categ = self.env.ref("product.product_category_goods", raise_if_not_found=False) \
            or self.env["product.category"].search([], limit=1, order="id")

        for row in _read_csv("ndi_master_produk.csv"):
            sku = row["sku"].strip()
            self.rows[sku] = row
            jenis = row["jenis"].strip()
            base, tier2, tier3 = self._uom_tree(row)
            extra_uoms = [uom.id for uom in (tier2, tier3) if uom]

            sellable = jenis in ("produk_jadi", "barang_dagangan")
            taxed = jenis == "barang_dagangan"

            weights = [(base, _f(row, "berat_satuan1_kg"))]
            if tier2:
                weights.append((tier2, _f(row, "berat_satuan2_kg")))
            if tier3:
                weights.append((tier3, _f(row, "berat_satuan3_kg")))

            values = {
                "name": row["nama"].strip(),
                "default_code": sku,
                "type": "consu",
                "is_storable": True,
                "categ_id": categ.id,
                "company_id": False,
                "uom_id": base.id,
                "uom_ids": [(6, 0, extra_uoms)],
                "weight": _f(row, "berat_satuan1_kg"),
                "list_price": _f(row, "hj1"),
                "standard_price": _f(row, "hpp_dasar"),
                "sale_ok": sellable,
                "purchase_ok": jenis != "produk_jadi",
                "available_in_pos": sellable,
                "invoice_policy": "order",
                "purchase_method": "receive",
                "taxes_id": [(6, 0, [(sale_12 if taxed else sale_exempt).id])],
                "supplier_taxes_id": [(6, 0, [t.id for t in [(buy_12 if taxed else buy_exempt)] if t])],
                "ndi_jenis_produk": jenis,
                "ndi_divisi_id": divisions[row["divisi"].strip()].id,
                "ndi_kategori_id": categories[
                    (divisions[row["divisi"].strip()].id, row["kategori"].strip())
                ].id,
                "ndi_stok_min": _f(row, "stok_min"),
                "ndi_stok_maks": _f(row, "stok_maks"),
                "ndi_hpp_dasar": _f(row, "hpp_dasar"),
                "ndi_profit_pct": _f(row, "profit_pct"),
                "ndi_risiko_pct": _f(row, "risiko_pct"),
                "ndi_pajak_pct": _f(row, "pajak_pct"),
                "ndi_ongkir_rp": _f(row, "ongkir_rp"),
                "ndi_pembulatan_rp": _f(row, "pembulatan_rp"),
                "ndi_insentif_kwartal_rp": _f(row, "insentif_kwartal_rp"),
                "ndi_insentif_bulanan_rp": _f(row, "insentif_bulanan_rp"),
                "ndi_margin_het_rp": _f(row, "margin_het_rp"),
                "ndi_uom_weight_ids": [
                    (0, 0, {"uom_id": uom.id, "gross_weight": weight})
                    for uom, weight in weights if weight
                ],
            }
            template = self.ensure("product_%s" % self._slug(sku), "product.template", values)
            self.products[sku] = template
            self.variants[sku] = template.product_variant_id
        _logger.info("custom_ndi_data_seed: %d produk siap", len(self.products))

    def assert_price_gate(self):
        """HJ1..HJ9 tersimpan harus sama persis dengan CSV.

        Pemeriksaan yang sama sudah dipakai uji modul harga, tetapi di sana ia
        berjalan di atas data uji yang di-rollback. Di sini ia berjalan di atas
        baris yang benar-benar tersimpan, dan itu perbedaan yang penting: yang
        dipakai laporan dan dashboard adalah kolom ini, bukan fixture.
        """
        self.env.flush_all()
        problems = []
        for row in _read_csv("ndi_master_produk.csv"):
            sku = row["sku"].strip()
            template = self.products[sku]
            for level in range(1, 10):
                expected = _f(row, "hj%d" % level)
                actual = template["ndi_hj%d" % level]
                if abs(expected - actual) > 0.01:
                    problems.append("%s HJ%d: CSV %.2f, tersimpan %.2f"
                                    % (sku, level, expected, actual))
        if problems:
            raise UserError(_(
                "Gerbang harga gagal untuk %(count)s kombinasi produk/tingkat. Master tidak "
                "boleh dilanjutkan ke transaksi dengan harga yang salah:\n%(rows)s",
                count=len(problems), rows="\n".join(problems[:40]),
            ))
        _logger.info("custom_ndi_data_seed: gerbang harga lolos untuk %d produk",
                     len(self.products))

    # ==================================================================
    # Master: termin, pelanggan, supplier
    # ==================================================================

    def _payment_term(self, days):
        days = int(days)
        xmlid = "term_%02d" % days
        existing = self.exists(xmlid)
        if existing:
            return existing
        if days <= 0:
            values = {"name": "Tunai / Bayar Saat Terima",
                      "line_ids": [(0, 0, {"value": "percent", "value_amount": 100.0,
                                           "nb_days": 0})]}
        else:
            values = {"name": "Termin %d Hari" % days,
                      "line_ids": [(0, 0, {"value": "percent", "value_amount": 100.0,
                                           "nb_days": days})]}
        values["company_id"] = self.company.id
        return self.ensure(xmlid, "account.payment.term", values)

    def build_partners(self):
        country = self.env.ref("base.id", raise_if_not_found=False)
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()

        for index, row in enumerate(_read_csv("ndi_pelanggan.csv"), start=1):
            code = row["kode"].strip()
            city = row["kota"].strip()
            name = row["nama"].strip()
            level = int(row["default_harga"].strip().replace("HJ", ""))
            if level not in levels:
                raise UserError(_("Pricelist untuk Harga %s belum ada.", level))
            is_person = name.startswith(("Bapak ", "Ibu "))
            values = {
                "name": name,
                "ref": code,
                "is_company": not is_person,
                "company_type": "person" if is_person else "company",
                "city": city,
                "street": "Jl. Contoh NDI No. %d" % (index % 180 + 1),
                "zip": "%05d" % (61200 + index),
                "phone": "+62-800-555-%04d" % index,
                "email": "%s@contoh.invalid" % code.lower(),
                "customer_rank": 1,
                "credit_limit": _f(row, "limit_kredit"),
                "property_payment_term_id": self._payment_term(_f(row, "termin_hari")).id,
                "ndi_customer_type": row["tipe"].strip(),
                "ndi_sales_region": CITY_REGION[city],
                "ndi_default_hj_level": level,
                "comment": (
                    "Data contoh NDI. Bukan orang atau usaha sungguhan.\n"
                    "Insentif bulanan: %s | Insentif kwartal: %s"
                    % (row["insentif_bulanan"].strip(), row["insentif_kuartal"].strip())
                ),
            }
            if country:
                values["country_id"] = country.id
            self.customers[code] = self.ensure(
                "cus_%s" % self._slug(code), "res.partner", values
            )

        for index, row in enumerate(_read_csv("ndi_supplier.csv"), start=1):
            code = row["kode"].strip()
            city = row["kota"].strip()
            values = {
                "name": row["nama"].strip(),
                "ref": code,
                "is_company": True,
                "company_type": "company",
                "city": city,
                "street": "Jl. Industri Contoh No. %d" % (index % 90 + 1),
                "zip": "%05d" % (61100 + index),
                "phone": "+62-800-556-%04d" % index,
                "email": "%s@contoh.invalid" % code.lower(),
                "supplier_rank": 1,
                "property_supplier_payment_term_id": self._payment_term(
                    _f(row, "termin_hari")).id,
                "ndi_sales_region": CITY_REGION[city],
                "comment": "Pemasok contoh NDI (%s). Bukan usaha sungguhan."
                           % row["komoditas"].strip(),
            }
            if country:
                values["country_id"] = country.id
            self.suppliers[code] = self.ensure(
                "sup_%s" % self._slug(code), "res.partner", values
            )

    def build_supplierinfo(self):
        """Harga pemasok per produk.

        Jagung dan dedak sengaja punya DUA pemasok masing-masing. Itu kasus uji
        G-16: satu field "Supplier" pada Master Produk tidak cukup untuk pabrik
        pakan, karena komoditas lokal selalu dipasok lebih dari satu penggilingan.
        """
        for entry in PO_PLAN:
            _key, supplier_code, lines = entry
            supplier = self.suppliers[supplier_code]
            for sku, _share in lines:
                template = self.products[sku]
                xmlid = "supinfo_%s_%s" % (self._slug(supplier_code), self._slug(sku))
                self.ensure(xmlid, "product.supplierinfo", {
                    "partner_id": supplier.id,
                    "product_tmpl_id": template.id,
                    "price": template.ndi_hpp_dasar,
                    "min_qty": 0.0,
                    "delay": self.rng.randint(2, 7),
                    "company_id": self.company.id,
                })

    # ==================================================================
    # Master: gudang, unit operasi
    # ==================================================================

    def build_warehouses(self):
        Warehouse = self.env["stock.warehouse"]
        for key, code, name, city in WAREHOUSES:
            xmlid = "wh_%s" % key
            warehouse = self.exists(xmlid)
            if not warehouse:
                warehouse = Warehouse.search(
                    [("code", "=", code), ("company_id", "=", self.company.id)], limit=1
                )
                if warehouse:
                    self.tag(xmlid, warehouse)
                else:
                    warehouse = self.ensure(xmlid, "stock.warehouse", {
                        "name": name,
                        "code": code,
                        "company_id": self.company.id,
                    })
            self.warehouses[key] = warehouse
            self.wh_city[key] = city

        gbb = self.warehouses["gbb"]
        gpj = self.warehouses["gpj"]

        # Tipe operasi disetel eksplisit, bukan dibiarkan default:
        #  * penerimaan 'always' supaya penerimaan sebagian membuat backorder tanpa
        #    wizard konfirmasi -- generator tidak punya UI untuk menjawabnya;
        #  * manufaktur dan pengiriman 'never' supaya MO/pengiriman yang jumlahnya
        #    memang sudah final tidak menawarkan backorder sama sekali.
        for warehouse in self.warehouses.values():
            # 'always' pada SETIAP tipe penerimaan, bukan hanya gudang bahan baku:
            # barang dagangan diterima di gudang produk jadi, dan tipe penerimaan
            # gudang itu yang tertinggal 'ask' pada versi pertama -- gejalanya PO
            # barang dagangan pertama menuntut wizard backorder di tengah jalan.
            warehouse.in_type_id.create_backorder = "always"
            warehouse.out_type_id.create_backorder = "never"
            warehouse.int_type_id.create_backorder = "never"
        gpj.manu_type_id.create_backorder = "never"

        # Tipe operasi manufaktur diarahkan ke gudang bahan baku sebagai sumber.
        # Ini bukan kenyamanan: ``mrp.production.location_src_id`` adalah compute
        # stored yang bergantung pada ``picking_type_id``, jadi nilai yang dikirim
        # lewat ``create()`` ditimpa hasil compute. Gejalanya bukan galat lokasi
        # melainkan MO yang tidak bisa direservasi sama sekali, karena ia mencari
        # bahan di gudang produk jadi yang memang tidak pernah menerima bahan.
        gpj.manu_type_id.default_location_src_id = self.warehouses["gbb"].lot_stock_id
        gpj.manu_type_id.default_location_dest_id = gpj.lot_stock_id

        # Lokasi barang rusak/retur tidak layak jual (temuan G-22). Bukan
        # 'inventory': barangnya masih ada dan masih dihitung, hanya tidak boleh
        # ikut terjual dari gudang produk jadi.
        self.ensure("loc_rusak", "stock.location", {
            "name": "RUSAK-SDA Barang Rusak dan Retur",
            "usage": "internal",
            "location_id": gpj.view_location_id.id,
            "company_id": self.company.id,
        })

    def build_operating_units(self):
        parent = None
        for key, code, name in OPERATING_UNITS:
            values = {"name": name, "code": code, "company_id": self.company.id}
            if parent is not None:
                values["parent_id"] = parent.id
            unit = self.ensure("ou_%s" % key, "operating.unit", values)
            self.units[key] = unit
            if parent is None:
                parent = unit

    # ==================================================================
    # Master: BOM
    # ==================================================================

    def _bom_rows(self):
        by_product = {}
        for row in _read_csv("ndi_bom_formulasi.csv"):
            by_product.setdefault(row["produk_sku"].strip(), []).append(row)
        return by_product

    def _packaging_lines(self, sku, batch_kg):
        """Kebutuhan kemasan per batch, dihitung dari kapasitas sak.

        Spesifikasi §3.1 sengaja TIDAK menaruhnya di file formulasi: kolom persen
        wajib berjumlah 100 dan kemasan bukan bagian dari formula bahan. Tetapi
        BOM Odoo hanya punya satu tabel baris, dan tanpa baris kemasan produksi
        tidak akan mengonsumsi karung sama sekali -- padahal biaya kemasan adalah
        komponen HPP yang direkonsiliasi UJI 5 spesifikasi.
        """
        row = self.rows[sku]
        sak_size = int(_f(row, "konversi2"))
        if sak_size not in PACKAGING_FOR_SAK:
            return []
        n_sak = batch_kg / float(sak_size)
        karung_sku, inner_sku = PACKAGING_FOR_SAK[sak_size]
        pcs = self.env.ref(BASE_UOM_XMLID["PCS"])
        cone = self.env.ref(BASE_UOM_XMLID["CONE"])
        return [
            (karung_sku, n_sak, pcs),
            (inner_sku, n_sak, pcs),
            ("PK-LBL-01", n_sak, pcs),
            ("PK-BNG-01", round(n_sak * BENANG_CONE_PER_SAK, 4), cone),
        ]

    def build_boms(self):
        gpj = self.warehouses["gpj"]
        for sku, rows in sorted(self._bom_rows().items()):
            template = self.products[sku]
            batch_kg = sum(_f(row, "qty_per_batch_kg") for row in rows)
            total_persen = sum(_f(row, "persen") for row in rows)
            if abs(total_persen - 100.0) > 0.01:
                raise UserError(_(
                    "Formula %(sku)s berjumlah %(total).2f%%, bukan 100%%. Sample data tidak "
                    "boleh menyembunyikan formula yang tidak seimbang.",
                    sku=sku, total=total_persen,
                ))
            lines = [
                (0, 0, {
                    "product_id": self.variants[row["bahan_sku"].strip()].id,
                    "product_qty": _f(row, "qty_per_batch_kg"),
                    "product_uom_id": self.uom_kg.id,
                    "ndi_persen": _f(row, "persen"),
                })
                for row in rows
            ]
            for pack_sku, qty, uom in self._packaging_lines(sku, batch_kg):
                lines.append((0, 0, {
                    "product_id": self.variants[pack_sku].id,
                    "product_qty": qty,
                    "product_uom_id": uom.id,
                    "ndi_persen": 0.0,
                }))
            note = "Formula %s, batch standar %.0f KG (total %.2f%%):\n%s" % (
                sku, batch_kg, total_persen,
                "\n".join("  %-12s %7.2f%%  = %9.3f KG" % (
                    row["bahan_sku"].strip(), _f(row, "persen"),
                    _f(row, "qty_per_batch_kg")) for row in rows),
            )
            bom = self.ensure("bom_%s" % self._slug(sku), "mrp.bom", {
                "product_tmpl_id": template.id,
                "product_qty": batch_kg,
                "product_uom_id": self.uom_kg.id,
                "type": "normal",
                # 'flexible': konsumsi nyata pabrik pakan tidak pernah persis sama
                # dengan formula (susut, sisa mixer, abnormal waste). 'strict' akan
                # memunculkan wizard peringatan yang tidak bisa dijawab generator.
                "consumption": "flexible",
                "code": "FORMULA-%s" % sku,
                "company_id": self.company.id,
                "picking_type_id": gpj.manu_type_id.id,
                "ndi_batch_standar_kg": batch_kg,
                "ndi_formula_note": note,
                "bom_line_ids": lines,
            })
            self.boms[sku] = bom

    def apply_price_matrix(self):
        """Isi sembilan pricelist untuk seluruh produk lewat ``ndi.price.matrix``.

        Lewat matriks, bukan dengan menulis ``product.pricelist.item`` sendiri:
        matriks adalah satu-satunya jalur yang mencatat riwayat penerapan
        (``ndi.price.matrix.log``, pasal 21) dan yang idempotensinya sudah diuji.
        """
        self.env["ndi.price.matrix"].action_apply_all()

    # ==================================================================
    # POS
    # ==================================================================

    def build_pos(self):
        Journal = self.env["account.journal"]
        Method = self.env["pos.payment.method"]
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        sale_journal = Journal.search(
            [("type", "=", "sale"), ("company_id", "=", self.company.id)], limit=1)
        bank_journal = Journal.search(
            [("type", "=", "bank"), ("company_id", "=", self.company.id)], limit=1)

        bank_method = self.exists("posmethod_bank")
        if not bank_method:
            bank_method = self.ensure("posmethod_bank", "pos.payment.method", {
                "name": "Transfer Bank",
                "journal_id": bank_journal.id,
                "company_id": self.company.id,
            })

        for key in ("osd", "oml"):
            warehouse = self.warehouses[key]
            # Satu jurnal kas per outlet. Satu ``pos.payment.method`` bertipe kas
            # hanya boleh dipakai satu ``pos.config``; memakai satu jurnal kas
            # bersama membuat outlet kedua gagal dibuat.
            journal = self.ensure("journal_cash_%s" % key, "account.journal", {
                "name": "Kas %s" % warehouse.name,
                "code": ("K%s" % key[:3]).upper()[:5],
                "type": "cash",
                "company_id": self.company.id,
            })
            cash_method = self.ensure("posmethod_cash_%s" % key, "pos.payment.method", {
                "name": "Tunai %s" % warehouse.name,
                "journal_id": journal.id,
                "company_id": self.company.id,
            })
            config = self.ensure("posconfig_%s" % key, "pos.config", {
                "name": "Kasir %s" % warehouse.name,
                "company_id": self.company.id,
                "picking_type_id": warehouse.out_type_id.id,
                "journal_id": sale_journal.id,
                "invoice_journal_id": sale_journal.id,
                "payment_method_ids": [(6, 0, [cash_method.id, bank_method.id])],
                "pricelist_id": levels[1].id,
            })
            self.pos_configs[key] = config

    # ==================================================================
    # Master, keseluruhan
    # ==================================================================

    def build_master(self):
        divisions, categories = self.build_divisions()
        self.build_products(divisions, categories)
        self.assert_price_gate()
        self.build_partners()
        self.build_supplierinfo()
        self.build_warehouses()
        self.build_operating_units()
        self.build_boms()
        self.apply_price_matrix()
        self.build_pos()

    # ==================================================================
    # Rencana produksi dan kebutuhan bahan
    # ==================================================================

    def production_plan(self, months, start_date, mo_per_month):
        """Satu entri per MO, urut waktu.

        Rencana disusun lebih dulu dan utuh, bukan diputuskan sambil jalan, karena
        kebutuhan bahan satu bulan harus sudah diketahui **sebelum** PO bulan itu
        dibuat. Membalik urutan ini adalah cara paling langsung menghasilkan stok
        minus.
        """
        skus = [row["sku"].strip() for row in _read_csv("ndi_master_produk.csv")
                if row["jenis"].strip() == "produk_jadi"]
        skus.sort()
        plan = []
        for month_index in range(months):
            month_start = start_date + relativedelta(months=month_index)
            for slot in range(mo_per_month):
                sku = skus[slot % len(skus)]
                plan.append({
                    "global": len(plan),
                    "month": month_index,
                    "month_start": month_start,
                    "slot": slot,
                    "sku": sku,
                    "batch_kg": self.boms[sku].ndi_batch_standar_kg,
                })
        return plan

    def month_requirement(self, plan, month_index):
        """Kebutuhan bahan (satuan dasar) untuk seluruh MO satu bulan."""
        need = {}
        bom_rows = self._bom_rows()
        for entry in plan:
            if entry["month"] != month_index:
                continue
            sku = entry["sku"]
            for row in bom_rows[sku]:
                bahan = row["bahan_sku"].strip()
                need[bahan] = need.get(bahan, 0.0) + _f(row, "qty_per_batch_kg")
            for pack_sku, qty, _uom in self._packaging_lines(sku, entry["batch_kg"]):
                need[pack_sku] = need.get(pack_sku, 0.0) + qty
        return need

    def pick_waste_slots(self, plan, count):
        """MO yang sengaja mengonsumsi bahan lebih banyak dari formula.

        Abnormal waste (spesifikasi §6.1, ``R-PRD-09``) bukan "produksi kurang":
        bahannya tetap habis, hasilnya yang tidak sesuai. Karena itu yang dinaikkan
        di sini adalah konsumsi, bukan diturunkan hasilnya.
        """
        candidates = [entry["global"] for entry in plan]
        if count <= 0 or not candidates:
            return set()
        step = max(len(candidates) // count, 1)
        return {candidates[i * step] for i in range(count) if i * step < len(candidates)}

    def pick_draft_slots(self, plan, count):
        """MO yang dibiarkan Draft, semuanya di bulan terakhir yang benar-benar diisi.

        Draft ditaruh di akhir dan bukan disebar, karena gunanya adalah menguji
        "Draft tidak memotong stok" (``R-PRD-06``): kalau tersebar, bahannya sudah
        telanjur dipakai MO bulan berikutnya dan buktinya jadi tidak terbaca.
        """
        if count <= 0:
            return set()
        usable = [entry for entry in plan
                  if entry["month_start"] <= self.today]
        return {entry["global"] for entry in usable[-count:]}

    def partial_receipt_slots(self, months, total):
        """(bulan, indeks PO) yang diterima sebagian lalu dilanjutkan backorder.

        Dibatasi kapasitas ``months x len(PO_PLAN)`` secara eksplisit. Versi
        pertama tidak: dengan ``months=1`` dan ``partial_receipts=26`` di atas 22
        PO per bulan, pencarian slot kosong berputar selamanya di dalam bulan yang
        sudah penuh. Gejalanya bukan galat melainkan satu proses Python yang
        memakan 100% CPU tanpa satu pun query -- mode gagal yang paling sulit
        dibaca dari luar.
        """
        slots = set()
        capacity = max(months, 1) * len(PO_PLAN)
        total = min(max(total, 0), capacity)
        for number in range(total):
            month_index = number % max(months, 1)
            plan_index = (number * 5 + month_index) % len(PO_PLAN)
            for _attempt in range(len(PO_PLAN)):
                if (month_index, plan_index) not in slots:
                    break
                plan_index = (plan_index + 1) % len(PO_PLAN)
            else:
                continue  # bulan ini sudah penuh
            slots.add((month_index, plan_index))
        return slots

    # ==================================================================
    # Pembelian
    # ==================================================================

    def _price_factor(self, sku, month_index):
        """Variasi harga bahan antar bulan (spesifikasi §8.1).

        Tanpa riwayat harga yang bergerak, skenario 7 (naikkan harga jagung 10%
        lalu re-costing) tidak punya apa pun untuk dibandingkan.
        """
        if sku not in VOLATILE_SKUS:
            return 1.0
        wave = math.sin((month_index + hash(sku) % 7) / 1.9)
        return 1.0 + 0.08 * wave

    def _purchase_qty(self, sku, share, requirement, buffer_factor):
        if sku in requirement:
            qty = requirement[sku] * share * buffer_factor
        else:
            qty = FIXED_MONTHLY_QTY.get(sku, 0.0) * share
        return max(math.ceil(qty), 1)

    def seed_purchases(self, month_index, month_start, requirement, partial_slots):
        tag = month_start.strftime("%Y%m")
        buffer_factor = BUFFER_FIRST_MONTH if month_index == 0 else BUFFER_MONTH
        gbb = self.warehouses["gbb"]
        gpj = self.warehouses["gpj"]
        unit = self.units["pabrik"]

        for plan_index, (key, supplier_code, lines) in enumerate(PO_PLAN):
            xmlid = "po_%s_%s" % (tag, key)
            if self.exists(xmlid):
                continue
            supplier = self.suppliers[supplier_code]
            # Barang dagangan diterima langsung di gudang produk jadi: ia dijual
            # kembali apa adanya dan tidak pernah masuk mixer.
            merchandise = all(sku.startswith("TR-") for sku, _share in lines)
            warehouse = gpj if merchandise else gbb
            when = self.moment(month_start + timedelta(days=(plan_index % 10)), 8, 11)

            order_lines = []
            for sku, share in lines:
                variant = self.variants[sku]
                qty = self._purchase_qty(sku, share, requirement, buffer_factor)
                price = self.products[sku].ndi_hpp_dasar * self._price_factor(sku, month_index)
                order_lines.append((0, 0, {
                    "product_id": variant.id,
                    # ``product_qty``, BUKAN ``product_uom_qty``. Pada
                    # ``purchase.order.line`` Odoo 19, ``product_uom_qty`` adalah
                    # compute **stored** ("Total Quantity", hasil konversi ke satuan
                    # referensi produk) dan menulisnya tidak berpengaruh apa pun.
                    # ``product_qty`` yang wajib itu lalu jatuh ke default 1,0.
                    # Ini bukan galat: seluruh 22 PO tetap terkonfirmasi, diterima,
                    # dan ditagih -- hanya saja isinya 1 kg jagung untuk MO yang
                    # butuh 2.750 kg. Pada ``sale.order.line`` dan ``stock.move``
                    # nama fieldnya justru terbalik, dan itulah jebakannya.
                    "product_qty": qty,
                    "product_uom_id": variant.uom_id.id,
                    "price_unit": round(price, 2),
                    "date_planned": when,
                    "name": variant.display_name,
                }))
            order = self.env["purchase.order"].create({
                "partner_id": supplier.id,
                "company_id": self.company.id,
                "picking_type_id": warehouse.in_type_id.id,
                "date_order": when,
                "order_line": order_lines,
            })
            self.tag(xmlid, order)
            order.button_confirm()
            order.write({"date_order": when, "date_approve": when})
            partial = (month_index, plan_index) in partial_slots
            self._receive(order, when, partial, unit)
            self._bill(order, when, unit)

    def _validate_picking(self, picking):
        # ``skip_sms``: ``stock_sms`` menyisipkan wizard konfirmasi kirim SMS di
        # depan setiap validasi pengiriman ke pelanggan. Wizard itu tidak bisa
        # dijawab generator, dan mengirim SMS ke nomor contoh bukan sesuatu yang
        # boleh terjadi sama sekali dari sample data.
        result = picking.with_context(skip_sms=True).button_validate()
        if result is not True and isinstance(result, dict):
            raise UserError(_(
                "Validasi picking %(name)s meminta wizard %(model)s yang tidak bisa dijawab "
                "generator. Periksa create_backorder pada tipe operasi.",
                name=picking.name, model=result.get("res_model"),
            ))

    def _receive(self, order, when, partial, unit):
        """Terima PO. ``partial`` menerima 70% lebih dulu, sisanya lewat backorder.

        Backorder-nya diselesaikan di bulan yang sama, bukan digantung: penerimaan
        sebagian yang ingin diperagakan ``R-PUR-03`` adalah dua dokumen penerimaan
        untuk satu PO, dan menggantung sisanya justru membuat bahan bulan itu
        kurang dan produksi gagal.
        """
        rounds = 0
        while rounds < 4:
            rounds += 1
            pickings = order.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))
            if not pickings:
                break
            first = rounds == 1
            for picking in pickings:
                picking.action_assign()
                ratio = 0.7 if (partial and first) else 1.0
                for move in picking.move_ids:
                    move.quantity = move.product_uom_qty * ratio
                    move.picked = True
                self._validate_picking(picking)
                picking.write({"date_done": when, "scheduled_date": when,
                               "operating_unit_id": unit.id})
                picking.move_ids.write({"date": when})
                picking.move_ids.move_line_ids.write({"date": when})
            if not (partial and first):
                break

    def _bill(self, order, when, unit):
        if order.invoice_status != "to invoice":
            return
        order.action_create_invoice()
        bills = order.invoice_ids.filtered(lambda move: move.state == "draft")
        if not bills:
            return
        bills.write({"invoice_date": when.date(), "date": when.date(),
                     "operating_unit_id": unit.id})
        bills.action_post()

    # ==================================================================
    # Produksi
    # ==================================================================

    def seed_productions(self, month_index, month_start, plan, waste_slots, draft_slots):
        tag = month_start.strftime("%Y%m")
        gbb = self.warehouses["gbb"]
        gpj = self.warehouses["gpj"]
        Production = self.env["mrp.production"]
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        span = max((last_day - month_start).days, 1)

        for entry in plan:
            if entry["month"] != month_index:
                continue
            xmlid = "mo_%s_%03d" % (tag, entry["slot"])
            if self.exists(xmlid):
                continue
            sku = entry["sku"]
            variant = self.variants[sku]
            day = month_start + timedelta(days=min(2 + entry["slot"] * span // 48, span))
            when = self.moment(day, 7, 15)
            values = {
                "product_id": variant.id,
                "product_qty": entry["batch_kg"],
                "product_uom_id": self.uom_kg.id,
                "bom_id": self.boms[sku].id,
                "company_id": self.company.id,
                "picking_type_id": gpj.manu_type_id.id,
                "location_src_id": gbb.lot_stock_id.id,
                "location_dest_id": gpj.lot_stock_id.id,
                "date_start": when,
            }
            production = Production.create(values)
            self.tag(xmlid, production)
            if entry["global"] in draft_slots:
                # Sengaja dibiarkan Draft. Buktinya baru berarti kalau bahannya
                # memang belum berkurang, jadi ia tidak dikonfirmasi sama sekali.
                continue
            production.action_confirm()
            production.action_assign()
            if production.reservation_state != "assigned":
                missing = production.move_raw_ids.filtered(
                    lambda move: move.state not in ("assigned", "done")
                )
                source = production.location_src_id
                on_hand = self.available(source, [
                    move.product_id.default_code for move in missing
                    if move.product_id.default_code in self.variants
                ])
                raise UserError(_(
                    "MO %(name)s untuk %(sku)s tidak bisa direservasi penuh dari %(source)s. "
                    "Menyelesaikannya tetap akan membuat kuant negatif, jadi generator "
                    "berhenti di sini.\n%(missing)s",
                    name=production.name, sku=sku, source=source.complete_name,
                    missing="\n".join(
                        "  %-12s butuh %10.3f, tersedia %10.3f"
                        % (move.product_id.default_code, move.product_uom_qty,
                           on_hand.get(move.product_id.default_code, 0.0))
                        for move in missing
                    ) or "  -",
                ))
            abnormal = entry["global"] in waste_slots
            self._produce(production, entry["batch_kg"], when, abnormal=abnormal)

    def _yield_ratio(self, abnormal):
        if abnormal:
            return 1.0 - self.rng.uniform(*ABNORMAL_WASTE)
        return 1.0 - self.rng.triangular(*NORMAL_WASTE)

    def _produce(self, production, planned_kg, when, abnormal=False):
        """Selesaikan MO dengan susut yang diserap ke hasil, bukan ke bahan.

        Pasal 11: susut normal **tidak** dicatat sebagai kerugian tersendiri, ia
        muncul sebagai hasil produksi yang kurang dari target sementara bahannya
        tetap habis sesuai formula. Karena itu ``move_raw_ids.quantity``
        dikembalikan ke jumlah rencana setelah ``_set_qty_producing()``
        menskalakannya turun mengikuti ``qty_producing`` -- kalau tidak, bahan ikut
        berkurang dan susutnya hilang dari data sama sekali.
        """
        ratio = self._yield_ratio(abnormal)
        produced = round(planned_kg * ratio, 2)
        production.qty_producing = produced
        production._set_qty_producing()
        for move in production.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        production.with_context(skip_backorder=True).button_mark_done()
        production.write({"date_finished": when})
        (production.move_raw_ids | production.move_finished_ids).write({"date": when})
        return produced

    def scrap_abnormal(self, production, xmlid, when):
        """Catat abnormal waste sebagai ``stock.scrap`` bahan baku tersendiri.

        ``production_id`` sengaja TIDAK diisi. Scrap yang tertaut MO ikut terbawa
        setiap kueri yang menjumlahkan ``stock_move.production_id``, termasuk kueri
        yield -- dan hasilnya yield tampak melebihi 100% pada MO yang justru paling
        rugi. Tautannya dibuat lewat ``origin``, yang terbaca manusia dan tidak
        mencemari agregat.
        """
        if self.exists(xmlid):
            return None
        heaviest = max(production.move_raw_ids, key=lambda move: move.quantity, default=None)
        if not heaviest or heaviest.quantity <= 0:
            return None
        scrap = self.ensure(xmlid, "stock.scrap", {
            "product_id": heaviest.product_id.id,
            "scrap_qty": round(heaviest.quantity * self.rng.uniform(0.01, 0.025), 3),
            "product_uom_id": heaviest.product_uom.id,
            "location_id": self.warehouses["gbb"].lot_stock_id.id,
            "company_id": self.company.id,
            "origin": "Abnormal waste %s" % production.name,
        })
        if scrap.state != "done":
            scrap.do_scrap()
        scrap.write({"date_done": when})
        return scrap

    def topup_materials(self, needs, when, xmlid_base, unit):
        """Beli kekurangan bahan dari pemasok yang benar sebelum MO dibuat.

        Digerakkan kebutuhan, bukan jadwal: hanya bahan yang benar-benar kurang
        yang dibeli, dan hanya dari pemasok yang memang memasoknya menurut rencana
        pembelian. Jumlah PO yang lahir dari sini karena itu tidak tetap -- ia
        sekecil yang diperlukan.
        """
        gbb = self.warehouses["gbb"]
        free = self.available(gbb.lot_stock_id, list(needs))
        missing = {}
        for sku, qty in needs.items():
            gap = qty - free.get(sku, 0.0)
            if gap > 0:
                missing[sku] = gap
        if not missing:
            return 0
        by_supplier = {}
        for sku, qty in missing.items():
            by_supplier.setdefault(SKU_SUPPLIER[sku], []).append((sku, qty))

        created = 0
        for number, (supplier_code, items) in enumerate(sorted(by_supplier.items())):
            xmlid = "%s_po%02d" % (xmlid_base, number)
            if self.exists(xmlid):
                continue
            order_lines = []
            for sku, qty in sorted(items):
                variant = self.variants[sku]
                order_lines.append((0, 0, {
                    "product_id": variant.id,
                    "product_qty": max(math.ceil(qty * 1.35), 1),
                    "product_uom_id": variant.uom_id.id,
                    "price_unit": round(self.products[sku].ndi_hpp_dasar, 2),
                    "date_planned": when,
                    "name": variant.display_name,
                }))
            order = self.env["purchase.order"].create({
                "partner_id": self.suppliers[supplier_code].id,
                "company_id": self.company.id,
                "picking_type_id": gbb.in_type_id.id,
                "date_order": when,
                "order_line": order_lines,
            })
            self.tag(xmlid, order)
            order.button_confirm()
            order.write({"date_order": when, "date_approve": when})
            self._receive(order, when, False, unit)
            self._bill(order, when, unit)
            created += 1
        return created

    def seed_extra_productions(self, month_start, batches, offset, waste_offsets):
        """Batch produksi tambahan dengan hasil aktual yang bervariasi.

        Pass terpisah, dengan namespace external ID sendiri (``p2``), supaya
        idempotensi dataset utama tidak tersentuh: menjalankan ulang ``generate()``
        tetap tidak membuat apa pun, dan menjalankan ulang pass ini juga tidak.
        """
        tag = month_start.strftime("%Y%m")
        gbb = self.warehouses["gbb"]
        gpj = self.warehouses["gpj"]
        unit = self.units["pabrik"]
        skus = sorted(self.boms)
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        span = max((last_day - month_start).days, 1)
        made = {"mo": 0, "po": 0, "scrap": 0}

        for slot in range(batches):
            xmlid = "p2mo_%s_%02d" % (tag, slot)
            if self.exists(xmlid):
                continue
            sku = skus[(offset + slot) % len(skus)]
            bom = self.boms[sku]
            batch_kg = bom.ndi_batch_standar_kg
            when = self.moment(
                month_start + timedelta(days=min(3 + slot * span // max(batches, 1), span)),
                7, 15)

            needs = {}
            for line in bom.bom_line_ids:
                code = line.product_id.default_code
                qty = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id)
                needs[code] = needs.get(code, 0.0) + qty
            made["po"] += self.topup_materials(
                needs, when, "p2sup_%s_%02d" % (tag, slot), unit)

            production = self.env["mrp.production"].create({
                "product_id": self.variants[sku].id,
                "product_qty": batch_kg,
                "product_uom_id": self.uom_kg.id,
                "bom_id": bom.id,
                "company_id": self.company.id,
                "picking_type_id": gpj.manu_type_id.id,
                "location_src_id": gbb.lot_stock_id.id,
                "location_dest_id": gpj.lot_stock_id.id,
                "date_start": when,
            })
            self.tag(xmlid, production)
            production.action_confirm()
            production.action_assign()
            if production.reservation_state != "assigned":
                missing = production.move_raw_ids.filtered(
                    lambda move: move.state not in ("assigned", "done"))
                on_hand = self.available(production.location_src_id, [
                    move.product_id.default_code for move in missing
                    if move.product_id.default_code in self.variants])
                raise UserError(_(
                    "MO tambahan %(name)s untuk %(sku)s tidak bisa direservasi penuh dari "
                    "%(source)s.\n%(missing)s",
                    name=production.name, sku=sku,
                    source=production.location_src_id.complete_name,
                    missing="\n".join(
                        "  %-12s butuh %10.3f, tersedia %10.3f"
                        % (move.product_id.default_code, move.product_uom_qty,
                           on_hand.get(move.product_id.default_code, 0.0))
                        for move in missing) or "  -",
                ))
            abnormal = slot in waste_offsets
            self._produce(production, batch_kg, when, abnormal=abnormal)
            made["mo"] += 1
            if abnormal and self.scrap_abnormal(
                    production, "p2scrap_%s_%02d" % (tag, slot), when):
                made["scrap"] += 1
        return made

    # ==================================================================
    # Ledger stok bayangan
    # ==================================================================

    def available(self, location, skus):
        """{sku -> kuantitas bebas} di satu lokasi, dalam satuan dasar produk.

        Dibaca sekali per fase lalu dikurangi sendiri saat dialokasikan, bukan
        ditanyakan ulang per baris: 30 order kali 3 baris kali satu query adalah
        90 query yang jawabannya sudah diketahui. Yang penting bukan kecepatannya
        melainkan bahwa alokasinya konsisten -- setiap baris yang dibuat pasti bisa
        dipenuhi, sehingga tidak ada dokumen yang memaksa kuant negatif.
        """
        variants = [self.variants[sku] for sku in skus]
        rows = self.env["stock.quant"]._read_group(
            [("location_id", "child_of", location.id),
             ("product_id", "in", [variant.id for variant in variants])],
            ["product_id"],
            ["quantity:sum", "reserved_quantity:sum"],
        )
        by_id = {product.id: qty - reserved for product, qty, reserved in rows}
        return {sku: by_id.get(self.variants[sku].id, 0.0) for sku in skus}

    def _sak_uom(self, sku):
        """Satuan jual (SAK) produk jadi, beserta isinya dalam kg."""
        row = self.rows[sku]
        size = int(_f(row, "konversi2"))
        _base, tier2, _tier3 = self._uom_tree(row)
        return tier2, size

    # ==================================================================
    # Transfer antar lokasi
    # ==================================================================

    def seed_transfers(self, month_index, month_start, count):
        """Kirim produk jadi dan barang dagangan dari gudang ke dua outlet.

        Ini bukan hiasan: tanpa transfer, kuant di outlet nol dan setiap transaksi
        POS akan memaksa stok minus di lokasi yang tidak pernah menerima apa pun.
        """
        if count <= 0:
            return
        tag = month_start.strftime("%Y%m")
        gpj = self.warehouses["gpj"]
        sellable = [sku for sku, row in self.rows.items()
                    if row["jenis"].strip() in ("produk_jadi", "barang_dagangan")]
        sellable.sort()
        avail = self.available(gpj.lot_stock_id, sellable)

        outlets = ["osd", "oml"]
        for number in range(count):
            key = outlets[number % len(outlets)]
            xmlid = "trf_%s_%s_%02d" % (tag, key, number)
            if self.exists(xmlid):
                continue
            warehouse = self.warehouses[key]
            unit = self.units[key]
            when = self.moment(month_start + timedelta(days=6 + number), 9, 12)

            moves = []
            in_stock = [sku for sku in sellable if avail.get(sku, 0.0) >= 1.0]
            chosen = self.rng.sample(in_stock, min(8, len(in_stock)))
            for sku in chosen:
                row = self.rows[sku]
                variant = self.variants[sku]
                if row["jenis"].strip() == "produk_jadi":
                    size = int(_f(row, "konversi2"))
                    want = self.rng.randint(6, 20) * size
                else:
                    want = float(self.rng.randint(4, 24))
                qty = min(want, math.floor(avail.get(sku, 0.0)))
                if qty <= 0:
                    continue
                avail[sku] -= qty
                moves.append((0, 0, {
                    # Tanpa "name": ``stock.move`` Odoo 19 tidak lagi punya field
                    # itu (deskripsi baris pindah ke ``description_picking``), dan
                    # mengirimnya membuat create() menolak seluruh transfer.
                    "product_id": variant.id,
                    "product_uom_qty": qty,
                    "product_uom": variant.uom_id.id,
                    "location_id": gpj.lot_stock_id.id,
                    "location_dest_id": warehouse.lot_stock_id.id,
                    "date": when,
                }))
            if not moves:
                continue
            picking = self.env["stock.picking"].create({
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": gpj.lot_stock_id.id,
                "location_dest_id": warehouse.lot_stock_id.id,
                "scheduled_date": when,
                "origin": "Kirim ke %s" % warehouse.name,
                "operating_unit_id": unit.id,
                "company_id": self.company.id,
                "move_ids": moves,
            })
            self.tag(xmlid, picking)
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            self._validate_picking(picking)
            picking.write({"date_done": when, "scheduled_date": when})
            picking.move_ids.write({"date": when})
            picking.move_ids.move_line_ids.write({"date": when})

    # ==================================================================
    # Penjualan kredit dan tunai
    # ==================================================================

    def _customers_by_type(self, customer_type):
        return [partner for partner in self.customers.values()
                if partner.ndi_customer_type == customer_type]

    def _sale_mix(self, so_per_month):
        return [SO_CYCLE[index % len(SO_CYCLE)] for index in range(so_per_month)]

    def seed_sales(self, month_index, month_start, so_per_month):
        tag = month_start.strftime("%Y%m")
        gpj = self.warehouses["gpj"]
        unit = self.units["pabrik"]
        fg = sorted(sku for sku, row in self.rows.items()
                    if row["jenis"].strip() == "produk_jadi")
        avail = self.available(gpj.lot_stock_id, fg)
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        span = max((last_day - month_start).days, 1)

        for number, customer_type in enumerate(self._sale_mix(so_per_month)):
            xmlid = "so_%s_%03d" % (tag, number)
            if self.exists(xmlid):
                continue
            pool = self._customers_by_type(customer_type)
            if not pool:
                continue
            partner = pool[self.rng.randrange(len(pool))]
            when = self.moment(month_start + timedelta(days=min(8 + number * span // 40, span)),
                               8, 16)
            low, high = ORDER_SIZE[customer_type]

            lines = []
            for sku in self.rng.sample(fg, self.rng.randint(2, 3)):
                uom, size = self._sak_uom(sku)
                want_sak = self.rng.randint(low, high)
                have_sak = math.floor(avail.get(sku, 0.0) / size)
                qty_sak = min(want_sak, have_sak)
                if qty_sak < 1:
                    continue
                avail[sku] -= qty_sak * size
                lines.append((0, 0, {
                    "product_id": self.variants[sku].id,
                    "product_uom_qty": qty_sak,
                    "product_uom_id": uom.id,
                }))
            if not lines:
                continue

            order = self.env["sale.order"].create({
                "partner_id": partner.id,
                "company_id": self.company.id,
                "warehouse_id": gpj.id,
                "operating_unit_id": unit.id,
                "date_order": when,
                "order_line": lines,
            })
            self.tag(xmlid, order)
            order.action_confirm()
            order.write({"date_order": when})
            self._deliver(order, when)
            invoice = self._invoice(order, when)
            if invoice:
                self._settle(invoice, when, customer_type)

    def _deliver(self, order, when):
        for picking in order.picking_ids:
            if picking.state in ("done", "cancel"):
                continue
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            self._validate_picking(picking)
            picking.write({"date_done": when, "scheduled_date": when})
            picking.move_ids.write({"date": when})
            picking.move_ids.move_line_ids.write({"date": when})

    def _invoice(self, order, when):
        if order.invoice_status != "to invoice" or self.rng.random() > 0.9:
            return None
        moves = order._create_invoices()
        if not moves:
            return None
        moves.write({"invoice_date": when.date(), "date": when.date()})
        moves.action_post()
        return moves

    def _settle(self, invoice, when, customer_type):
        """Bayar penuh, sebagian, atau tidak sama sekali.

        Piutang yang dibayar sebagian adalah yang paling banyak dipakai demo:
        umur piutang, sisa tagihan, dan batas kredit baru punya arti kalau ada
        faktur yang belum lunas dan yang lunas separuh.
        """
        roll = self.rng.random()
        if roll > 0.8:
            return
        total = invoice.amount_total
        if total <= 0:
            return
        # Distributor bertermin 30-45 hari lebih jarang lunas dalam satu kali bayar
        # daripada peternak bertermin 7-14 hari; itu yang membuat umur piutang
        # sample data punya bentuk, bukan sebaran acak seragam.
        full_threshold = 0.25 if customer_type == "distributor" else 0.50
        amount = total if roll < full_threshold else round(
            total * self.rng.uniform(0.35, 0.65), 2)
        journal = self.env["account.journal"].search(
            [("type", "=", "bank"), ("company_id", "=", self.company.id)], limit=1)
        pay_date = min(when.date() + timedelta(days=self.rng.randint(1, 20)), self.today)
        wizard = self.env["account.payment.register"].with_context(
            active_model="account.move", active_ids=invoice.ids,
        ).create({
            "amount": amount,
            "payment_date": pay_date,
            "journal_id": journal.id,
            "payment_difference_handling": "open",
        })
        wizard.action_create_payments()

    # ==================================================================
    # POS
    # ==================================================================

    def _pos_session(self, key, month_start):
        tag = month_start.strftime("%Y%m")
        xmlid = "possess_%s_%s" % (tag, key)
        session = self.exists(xmlid)
        if session:
            return session
        config = self.pos_configs[key]
        open_session = self.env["pos.session"].search(
            [("config_id", "=", config.id), ("state", "!=", "closed")], limit=1)
        if open_session:
            return self.tag(xmlid, open_session)
        session = self.env["pos.session"].create({
            "config_id": config.id,
            "user_id": self.env.uid,
        })
        self.tag(xmlid, session)
        if session.state == "opening_control":
            session.set_opening_control(0, None)
        session.write({"start_at": self.moment(month_start, 7, 8)})
        return session

    def _close_pos_session(self, session, month_start):
        if session.state == "closed":
            return
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        stop_at = self.moment(min(last_day, self.today), 20, 21)
        # Selisih kas dibuat nol dengan sengaja: menutup sesi dengan selisih
        # menuntut akun selisih kas yang tidak disetel l10n_id, dan sample data
        # yang gagal ditutup lebih buruk daripada sample data tanpa selisih kas.
        session.write({"stop_at": stop_at,
                       "cash_register_balance_end_real": session.cash_register_balance_end})
        session.action_pos_session_closing_control()
        session.write({"stop_at": stop_at})

    def seed_pos(self, month_index, month_start, count):
        if count <= 0:
            return
        tag = month_start.strftime("%Y%m")
        sellable = sorted(sku for sku, row in self.rows.items()
                          if row["jenis"].strip() in ("produk_jadi", "barang_dagangan"))
        levels = self.env["product.pricelist"]._ndi_pricelist_by_level()
        pricelist = levels[1]
        last_day = (month_start + relativedelta(months=1)) - timedelta(days=1)
        span = max((last_day - month_start).days, 1)

        for outlet_index, key in enumerate(("osd", "oml")):
            share = count // 2 + (count % 2 if outlet_index == 0 else 0)
            if share <= 0:
                continue
            warehouse = self.warehouses[key]
            unit = self.units[key]
            config = self.pos_configs[key]
            session = self._pos_session(key, month_start)
            avail = self.available(warehouse.lot_stock_id, sellable)
            cash = config.payment_method_ids.filtered("is_cash_count")[:1]
            other = (config.payment_method_ids - cash)[:1]
            retail = [partner for partner in self.customers.values()
                      if partner.ndi_customer_type == "retail"
                      and partner.city == self.wh_city[key]]
            if not retail:
                retail = [partner for partner in self.customers.values()
                          if partner.ndi_customer_type == "retail"]

            for number in range(share):
                xmlid = "pos_%s_%s_%03d" % (tag, key, number)
                if self.exists(xmlid):
                    continue
                when = self.moment(
                    month_start + timedelta(days=min(number * span // max(share, 1), span)),
                    8, 17)
                partner = retail[self.rng.randrange(len(retail))]

                # Hanya produk yang benar-benar ada stoknya di outlet ini yang
                # boleh masuk keranjang. Versi pertama mengambil sampel dari
                # seluruh katalog lalu membuang baris yang stoknya nol, dan
                # transaksi yang seluruh barisnya terbuang hilang sama sekali --
                # jumlah transaksi POS yang lahir jadi lebih kecil dari yang
                # diminta tanpa satu pun tanda bahwa ada yang terbuang.
                in_stock = [sku for sku in sellable if avail.get(sku, 0.0) >= 1.0]
                if not in_stock:
                    continue
                lines, subtotal, tax_total = [], 0.0, 0.0
                for sku in self.rng.sample(in_stock, min(self.rng.randint(1, 3), len(in_stock))):
                    row = self.rows[sku]
                    variant = self.variants[sku]
                    if row["jenis"].strip() == "produk_jadi":
                        size = int(_f(row, "konversi2"))
                        want = self.rng.randint(1, 10) * size
                    else:
                        want = float(self.rng.randint(1, 6))
                    qty = min(want, math.floor(avail.get(sku, 0.0)))
                    if qty <= 0:
                        continue
                    avail[sku] -= qty
                    price = self.products[sku].ndi_hj1
                    line_sub = round(price * qty, 2)
                    taxes = variant.taxes_id
                    line_tax = round(line_sub * sum(taxes.mapped("amount")) / 100.0, 2)
                    subtotal += line_sub
                    tax_total += line_tax
                    lines.append((0, 0, {
                        "product_id": variant.id,
                        "qty": qty,
                        "price_unit": price,
                        "price_subtotal": line_sub,
                        "price_subtotal_incl": line_sub + line_tax,
                        "full_product_name": variant.display_name,
                        "tax_ids": [(6, 0, taxes.ids)],
                    }))
                if not lines:
                    continue

                total = round(subtotal + tax_total, 2)
                order = self.env["pos.order"].create({
                    "session_id": session.id,
                    "company_id": self.company.id,
                    "operating_unit_id": unit.id,
                    "partner_id": partner.id,
                    "pricelist_id": pricelist.id,
                    "date_order": when,
                    "amount_total": total,
                    "amount_tax": round(tax_total, 2),
                    "amount_paid": 0.0,
                    "amount_return": 0.0,
                    "to_invoice": False,
                    "lines": lines,
                })
                self.tag(xmlid, order)
                method = cash if (self.rng.random() < 0.8 or not other) else other
                order.add_payment({
                    "pos_order_id": order.id,
                    "amount": total,
                    "payment_date": fields.Datetime.to_string(when),
                    "payment_method_id": method.id,
                })
                order.action_pos_order_paid()
                order._create_order_picking()
                order.write({"date_order": when})
                for picking in order.picking_ids:
                    picking.write({"date_done": when, "scheduled_date": when,
                                   "operating_unit_id": unit.id})
                    picking.move_ids.write({"date": when})
                    picking.move_ids.move_line_ids.write({"date": when})

            self._close_pos_session(session, month_start)

    # ==================================================================
    # Satu bulan
    # ==================================================================

    def seed_month(self, month_index, month_start, plan, waste_slots, draft_slots,
                   partial_slots, so_per_month, transfers_per_month, pos_per_month):
        """Urutannya load-bearing: beli, produksi, kirim ke outlet, jual."""
        requirement = self.month_requirement(plan, month_index)
        self.seed_purchases(month_index, month_start, requirement, partial_slots)
        self.checkpoint("%s pembelian" % month_start.strftime("%Y-%m"))
        self.seed_productions(month_index, month_start, plan, waste_slots, draft_slots)
        self.checkpoint("%s produksi" % month_start.strftime("%Y-%m"))
        self.seed_transfers(month_index, month_start, transfers_per_month)
        self.seed_sales(month_index, month_start, so_per_month)
        self.seed_pos(month_index, month_start, pos_per_month)
        self.checkpoint("%s penjualan" % month_start.strftime("%Y-%m"))


class NdiDataSeed(models.TransientModel):
    """Fasad ORM di atas :class:`NdiSeedRun`.

    Transient karena tidak menyimpan state antar jalan: seluruh state satu jalan
    hidup di objek ``NdiSeedRun``.
    """

    _name = "ndi.data.seed"
    _description = "NDI Sample Data Generator"

    seed = fields.Integer(default=20251001, required=True)
    start_date = fields.Date(string="Mulai", default="2025-10-01", required=True)
    months = fields.Integer(string="Jumlah Bulan", default=12, required=True)
    mo_per_month = fields.Integer(string="MO per Bulan", default=48, required=True)
    po_per_month = fields.Integer(string="PO per Bulan", default=22, required=True)
    so_per_month = fields.Integer(string="Sales Order per Bulan", default=30, required=True)
    pos_orders = fields.Integer(string="Transaksi POS (total)", default=310, required=True)
    transfers_per_month = fields.Integer(string="Transfer per Bulan", default=2, required=True)
    draft_mo = fields.Integer(string="MO Dibiarkan Draft", default=6, required=True)
    waste_mo = fields.Integer(string="MO Abnormal Waste", default=9, required=True)
    partial_receipts = fields.Integer(string="Penerimaan Sebagian", default=26, required=True)
    dataset = fields.Char(
        default=DEFAULT_DATASET,
        required=True,
        help="Namespace mandiri yang idempoten sendiri. Dua dataset tidak pernah berbagi "
             "record. Pakai nama baru untuk menyemai bentuk berbeda berdampingan.",
    )

    def action_generate(self):
        self.ensure_one()
        summary = self.generate(
            seed=self.seed,
            start=fields.Date.to_string(self.start_date),
            months=self.months,
            mo_per_month=self.mo_per_month,
            po_per_month=self.po_per_month,
            so_per_month=self.so_per_month,
            pos_orders=self.pos_orders,
            transfers_per_month=self.transfers_per_month,
            draft_mo=self.draft_mo,
            waste_mo=self.waste_mo,
            partial_receipts=self.partial_receipts,
            dataset=self.dataset,
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sample data NDI dibuat"),
                "message": "\n".join("%s: %s" % item for item in sorted(summary.items())),
                "sticky": True,
                "type": "success",
            },
        }

    # -- dataset --------------------------------------------------------

    @api.model
    def _dataset_context(self, dataset):
        name = DEFAULT_DATASET if dataset is None else dataset
        if not isinstance(name, str) or not DATASET_RE.match(name):
            raise UserError(_(
                "Nama dataset %(name)r tidak sah. Pakai 1-20 huruf kecil dan angka, diawali "
                "huruf, tanpa garis bawah dan tanpa huruf besar. Nama dicocokkan persis: "
                "'Prod' bukan 'prod'.",
                name=dataset,
            ))
        return {"name": name, "prefix": "%s__" % name}

    @api.model
    def get_shape(self, dataset=DEFAULT_DATASET):
        """Bentuk tercatat dataset, atau ``False`` kalau belum pernah disemai."""
        ds = self._dataset_context(dataset)
        raw = self.env["ir.config_parameter"].sudo().get_param(SHAPE_PARAM % ds["name"])
        return json.loads(raw) if raw else False

    @api.model
    def _assert_shape(self, ds, requested):
        recorded = self.get_shape(ds["name"])
        if not recorded:
            return
        conflicts = [
            (key, recorded.get(key), requested[key])
            for key in SHAPE_KEYS
            if recorded.get(key) != requested[key]
        ]
        if not conflicts:
            return
        raise UserError(_(
            "Dataset '%(dataset)s' sudah ada dengan bentuk berbeda, jadi panggilan ini akan "
            "diam-diam mengembalikan data yang tidak kamu minta.\n\n%(conflicts)s\n\n"
            "Pilih salah satu:\n"
            "  * panggil lagi dengan dataset='<nama baru>' untuk menyemai bentuk ini "
            "berdampingan -- dua dataset tidak pernah berbagi record; atau\n"
            "  * ulangi dengan bentuk di atas kalau memang ingin melanjutkan dataset ini.\n\n"
            "Sengaja tidak ada reset: jurnal yang sudah diposting dan stock move yang sudah "
            "done tidak bisa dihapus tanpa menembus audit trail Odoo.",
            dataset=ds["name"],
            conflicts="\n".join(
                "  - %s: sudah disemai sebagai %r, kamu minta %r" % (key, was, now)
                for key, was, now in conflicts
            ),
        ))

    # -- titik masuk ----------------------------------------------------

    @api.model
    def generate(
        self,
        seed=20251001,
        start="2025-10-01",
        months=12,
        mo_per_month=48,
        po_per_month=22,
        so_per_month=30,
        pos_orders=310,
        transfers_per_month=2,
        draft_mo=6,
        waste_mo=9,
        partial_receipts=26,
        company=None,
        dataset=DEFAULT_DATASET,
        commit=True,
    ):
        """Isi database dengan sample data NDI dan kembalikan hitungan barisnya.

        Memanggilnya dua kali dengan argumen yang sama tidak membuat apa pun pada
        panggilan kedua; ia melanjutkan dari titik terakhir. Memanggilnya dengan
        argumen **berbeda** untuk dataset yang sudah ada akan menolak dan menyebut
        setiap parameter yang bentrok -- ia tidak pernah diam-diam mengembalikan
        bentuk yang tidak kamu minta.
        """
        if not self.env.user._is_admin():
            raise UserError(_("Hanya administrator yang boleh membuat sample data."))
        if not 1 <= months <= 24:
            raise UserError(_("months harus antara 1 dan 24."))
        if po_per_month != len(PO_PLAN):
            raise UserError(_(
                "Rencana pembelian modul ini berisi %(plan)s PO per bulan, kamu minta "
                "%(asked)s. Ubah PO_PLAN, bukan hanya parameternya -- kalau tidak, jumlah PO "
                "yang dilaporkan tidak akan sama dengan yang dibuat.",
                plan=len(PO_PLAN), asked=po_per_month,
            ))
        if mo_per_month % 12:
            raise UserError(_(
                "mo_per_month harus kelipatan 12 supaya kedua belas produk jadi mendapat "
                "jumlah batch yang sama. Kamu minta %(asked)s.", asked=mo_per_month,
            ))

        env = self.env(su=True)
        company = company or env.company
        ds = self._dataset_context(dataset)
        start_date = fields.Date.to_date(start)
        shape = {
            "seed": seed,
            "start": fields.Date.to_string(start_date),
            "months": months,
            "mo_per_month": mo_per_month,
            "po_per_month": po_per_month,
            "so_per_month": so_per_month,
            "pos_orders": pos_orders,
            "transfers_per_month": transfers_per_month,
            "draft_mo": draft_mo,
            "waste_mo": waste_mo,
            "partial_receipts": partial_receipts,
            "company_id": company.id,
        }
        self._assert_shape(ds, shape)

        run = NdiSeedRun(env, company, ds, shape,
                         fields.Date.context_today(self), commit=commit)
        started = datetime.now()
        _logger.info("custom_ndi_data_seed: mulai dataset=%s shape=%s", ds["name"], shape)

        run.build_master()
        run.checkpoint("master")

        plan = run.production_plan(months, start_date, mo_per_month)
        waste_slots = run.pick_waste_slots(plan, waste_mo)
        draft_slots = run.pick_draft_slots(plan, draft_mo)
        partial_slots = run.partial_receipt_slots(months, partial_receipts)

        base_pos = pos_orders // months
        extra_pos = pos_orders % months
        for index in range(months):
            month_start = start_date + relativedelta(months=index)
            if month_start > run.today:
                _logger.warning(
                    "custom_ndi_data_seed: bulan %s belum tiba, dihentikan di sini",
                    month_start.strftime("%Y-%m"))
                break
            run.seed_month(
                index, month_start, plan, waste_slots, draft_slots, partial_slots,
                so_per_month, transfers_per_month,
                base_pos + (1 if index < extra_pos else 0),
            )

        env["ir.config_parameter"].sudo().set_param(
            SHAPE_PARAM % ds["name"], json.dumps(shape, sort_keys=True))
        if commit:
            env.cr.commit()
        summary = self.summary(dataset=ds["name"])
        summary["elapsed_seconds"] = round((datetime.now() - started).total_seconds(), 1)
        _logger.info("custom_ndi_data_seed: selesai %s", summary)
        return summary

    # -- pass produksi tambahan -----------------------------------------

    @api.model
    def generate_extra_production(
        self,
        dataset=DEFAULT_DATASET,
        start="2025-10-01",
        months=12,
        batches_per_month=4,
        waste_mo=9,
        seed=20260901,
        commit=True,
    ):
        """Tambahkan batch produksi bervariasi ke dataset yang sudah ada.

        Pass terpisah, bukan pengulangan ``generate()``. Alasannya bukan kecepatan:
        MO yang sudah ``done`` membawa stock move yang sudah ``done``, dan Odoo
        melarang menghapus keduanya secara desain. Bentuk data yang sudah mendarat
        karena itu tidak bisa diubah -- ia hanya bisa ditambahi. Pass ini punya
        namespace external ID sendiri (``p2``) dan bentuknya dicatat terpisah,
        sehingga menjalankannya dua kali tidak membuat apa pun dan menjalankan
        ulang ``generate()`` tetap tidak tersentuh.

        Yang ditambahkannya: batch dengan **hasil aktual yang bervariasi** di
        sekitar target (susut normal diserap ke hasil, pasal 11), sebagian di
        antaranya abnormal waste yang jauh di luar sebaran normal dan dicatat
        terpisah sebagai ``stock.scrap``. Bahan yang kurang dibeli lebih dulu dari
        pemasok yang benar, jadi tidak ada satu pun MO yang diselesaikan di atas
        stok yang tidak ada.
        """
        if not self.env.user._is_admin():
            raise UserError(_("Hanya administrator yang boleh membuat sample data."))
        env = self.env(su=True)
        ds = self._dataset_context(dataset)
        if not self.get_shape(ds["name"]):
            raise UserError(_(
                "Dataset '%(dataset)s' belum pernah disemai. Pass produksi tambahan berdiri "
                "di atas master, gudang dan BOM milik dataset itu; jalankan generate() dulu.",
                dataset=ds["name"],
            ))
        start_date = fields.Date.to_date(start)
        shape = {
            "seed": seed, "start": fields.Date.to_string(start_date), "months": months,
            "batches_per_month": batches_per_month, "waste_mo": waste_mo,
        }
        param = "custom_ndi_data_seed.pass2.%s" % ds["name"]
        recorded = env["ir.config_parameter"].sudo().get_param(param)
        if recorded and json.loads(recorded) != shape:
            raise UserError(_(
                "Pass produksi tambahan untuk dataset '%(dataset)s' sudah dijalankan dengan "
                "bentuk %(was)s, kamu minta %(now)s. Bentuk yang berbeda adalah pass yang "
                "berbeda, dan memanggilnya diam-diam akan mengembalikan data yang tidak "
                "kamu minta.",
                dataset=ds["name"], was=recorded, now=json.dumps(shape, sort_keys=True),
            ))

        run = NdiSeedRun(env, env.company, ds, {"seed": seed},
                         fields.Date.context_today(self), commit=commit)
        run.build_master()

        total = months * batches_per_month
        step = max(total // max(waste_mo, 1), 1)
        abnormal_global = {index * step for index in range(waste_mo) if index * step < total}

        totals = {"mo": 0, "po": 0, "scrap": 0}
        for index in range(months):
            month_start = start_date + relativedelta(months=index)
            if month_start > run.today:
                break
            offsets = {
                g - index * batches_per_month for g in abnormal_global
                if index * batches_per_month <= g < (index + 1) * batches_per_month
            }
            made = run.seed_extra_productions(
                month_start, batches_per_month, index * batches_per_month, offsets)
            for key, value in made.items():
                totals[key] += value
            run.checkpoint("pass2 %s" % month_start.strftime("%Y-%m"))

        env["ir.config_parameter"].sudo().set_param(param, json.dumps(shape, sort_keys=True))
        if commit:
            env.cr.commit()
        _logger.info("custom_ndi_data_seed: pass produksi tambahan %s", totals)
        return totals

    # -- ringkasan ------------------------------------------------------

    @api.model
    def _tracked(self, ds, model_name, xmlid_prefix=""):
        """Record milik dataset ini, dihitung lewat ``ir.model.data``.

        Bukan lewat pola nama: pola nama adalah heuristik, dan heuristik itulah
        yang dulu mencampur dua dataset dan salah menghitung dokumen turunan.
        """
        rows = self.env["ir.model.data"].sudo().search([
            ("module", "=", MODULE),
            ("model", "=", model_name),
            ("name", "=like", ds["prefix"] + xmlid_prefix + "%"),
        ])
        return self.env[model_name].sudo().browse(rows.mapped("res_id")).exists()

    @api.model
    def summary(self, dataset=DEFAULT_DATASET):
        ds = self._dataset_context(dataset)
        productions = self._tracked(ds, "mrp.production")
        orders = self._tracked(ds, "sale.order")
        return {
            "dataset": ds["name"],
            "produk": len(self._tracked(ds, "product.template", "product_")),
            "pelanggan": len(self._tracked(ds, "res.partner", "cus_")),
            "supplier": len(self._tracked(ds, "res.partner", "sup_")),
            "bom": len(self._tracked(ds, "mrp.bom")),
            "gudang": len(self._tracked(ds, "stock.warehouse")),
            "operating_unit": len(self._tracked(ds, "operating.unit")),
            "purchase_order": len(self._tracked(ds, "purchase.order")),
            "mrp_production": len(productions),
            "mrp_production_done": len(productions.filtered(lambda p: p.state == "done")),
            "mrp_production_draft": len(productions.filtered(lambda p: p.state == "draft")),
            "sale_order": len(orders),
            "pos_order": len(self._tracked(ds, "pos.order")),
            "pos_session": len(self._tracked(ds, "pos.session")),
            "transfer": len(self._tracked(ds, "stock.picking", "trf_")),
        }
