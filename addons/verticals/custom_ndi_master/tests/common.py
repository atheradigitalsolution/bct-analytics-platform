# -*- coding: utf-8 -*-
"""Pemuat data sampel NDI untuk uji.

CSV yang dibaca di sini adalah **salinan byte-identik** dari
``.claude/deliverables/ndi-pos-produksi/30-data/02-master-produk.csv``. Salinan,
bukan symlink, karena container Odoo hanya me-mount ``addons/`` — direktori
deliverable tidak terlihat dari dalam container, jadi uji tidak bisa membacanya
di tempat aslinya.

Karena salinan bisa berpisah dari aslinya diam-diam, isinya dikunci ke sha256
di :data:`FIXTURE_SHA256`. Uji akan menolak jika file berubah, dan siapa pun
yang memperbarui salinan harus ikut memperbarui hash — sehingga perubahan itu
muncul di diff, bukan di keheningan.
"""

import csv
import hashlib
import os

from odoo.tests import TransactionCase

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "02-master-produk.csv")

#: sha256 dari 30-data/02-master-produk.csv yang diverifikasi oleh
#: 30-data/99-verifikasi-aritmetika.py (52 produk, 468 persamaan waterfall).
FIXTURE_SHA256 = "816d1bc9c87a42ee577aacabd9310c59ef847fe4a244ae804cbbb642d2165bf0"

COMPONENT_COLUMNS = (
    "hpp_dasar",
    "profit_pct",
    "risiko_pct",
    "pajak_pct",
    "ongkir_rp",
    "pembulatan_rp",
    "insentif_kwartal_rp",
    "insentif_bulanan_rp",
    "margin_het_rp",
)

JENIS_MAP = {
    "bahan_baku": "bahan_baku",
    "kemasan": "kemasan",
    "produk_jadi": "produk_jadi",
    "barang_dagangan": "barang_dagangan",
}

#: Label satuan pada CSV -> xmlid ``uom.uom``. Kunci tingkat 2 dan 3 memakai
#: (label, konversi, label_induk) karena `uom.uom` global: "SAK" sendirian tidak
#: menentukan record mana yang dimaksud (50 kg? 30 kg? 25 kg?).
BASE_UOM_XMLID = {
    "KG": "uom.product_uom_kgm",
    "PCS": "custom_ndi_master.uom_pcs",
    "BTL": "custom_ndi_master.uom_btl",
    "JRG": "custom_ndi_master.uom_jrg",
    "SCH": "custom_ndi_master.uom_sch",
    "CONE": "custom_ndi_master.uom_cone",
    "SAK": "custom_ndi_master.uom_sak_hitung",
}

DERIVED_UOM_XMLID = {
    ("KG", "SAK", "50"): "custom_ndi_master.uom_sak_50kg",
    ("KG", "SAK", "30"): "custom_ndi_master.uom_sak_30kg",
    ("KG", "SAK", "25"): "custom_ndi_master.uom_sak_25kg",
    ("KG", "DRUM", "200"): "custom_ndi_master.uom_drum_200kg",
    ("KG", "DRUM", "250"): "custom_ndi_master.uom_drum_250kg",
    ("SAK 50 KG", "TON", "20"): "custom_ndi_master.uom_ton_20sak_50kg",
    ("SAK 30 KG", "TON", "20"): "custom_ndi_master.uom_ton_20sak_30kg",
    ("PCS", "BAL", "1000"): "custom_ndi_master.uom_bal_1000pcs",
    ("PCS", "ROLL", "500"): "custom_ndi_master.uom_roll_500pcs",
    ("PCS", "DUS", "100"): "custom_ndi_master.uom_dus_100pcs",
    ("BTL", "DUS", "12"): "custom_ndi_master.uom_dus_12btl",
    ("JRG", "DUS", "4"): "custom_ndi_master.uom_dus_4jrg",
    ("SCH", "DUS", "50"): "custom_ndi_master.uom_dus_50sch",
    ("CONE", "DUS", "12"): "custom_ndi_master.uom_dus_12cone",
    ("SAK", "TON", "50"): "custom_ndi_master.uom_ton_50sak",
}


def read_sample_products():
    """Baca CSV sampel dan pastikan isinya persis yang sudah diverifikasi."""
    with open(FIXTURE_PATH, "rb") as handle:
        payload = handle.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != FIXTURE_SHA256:
        raise AssertionError(
            "Fixture 02-master-produk.csv berubah: sha256 %s, diharapkan %s. "
            "Perbarui FIXTURE_SHA256 hanya bila CSV sumber di 30-data/ memang berubah "
            "dan 99-verifikasi-aritmetika.py masih lulus atasnya." % (digest, FIXTURE_SHA256)
        )
    return list(csv.DictReader(payload.decode("utf-8").splitlines()))


class NdiSampleCase(TransactionCase):
    """Memuat 52 produk sampel beserta komponen harga dan pohon satuannya."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sample_rows = read_sample_products()
        cls.products_by_sku = cls._load_sample_products()

    @classmethod
    def _uom(cls, xmlid):
        return cls.env.ref(xmlid)

    @classmethod
    def _row_uoms(cls, row):
        """(satuan dasar, daftar satuan kemasan) untuk satu baris CSV."""
        base = cls._uom(BASE_UOM_XMLID[row["satuan_dasar"]])
        packagings = cls.env["uom.uom"]
        if row["satuan2"]:
            key = (row["satuan_dasar"], row["satuan2"], row["konversi2"])
            packagings |= cls._uom(DERIVED_UOM_XMLID[key])
        if row["satuan3"]:
            parent_label = packagings[-1:].name if packagings else row["satuan_dasar"]
            key = (parent_label, row["satuan3"], row["konversi3"])
            if key not in DERIVED_UOM_XMLID:
                key = (row["satuan2"], row["satuan3"], row["konversi3"])
            packagings |= cls._uom(DERIVED_UOM_XMLID[key])
        return base, packagings

    @classmethod
    def _load_sample_products(cls):
        divisions = {}
        categories = {}
        products = {}
        template_model = cls.env["product.template"]
        for row in cls.sample_rows:
            division = divisions.get(row["divisi"])
            if not division:
                division = cls.env["ndi.division"].search([("name", "=", row["divisi"])], limit=1)
                if not division:
                    division = cls.env["ndi.division"].create({"name": row["divisi"]})
                divisions[row["divisi"]] = division
            category_key = (row["divisi"], row["kategori"])
            category = categories.get(category_key)
            if not category:
                category = cls.env["ndi.product.category"].search(
                    [("name", "=", row["kategori"]), ("division_id", "=", division.id)], limit=1
                )
                if not category:
                    category = cls.env["ndi.product.category"].create(
                        {"name": row["kategori"], "division_id": division.id}
                    )
                categories[category_key] = category

            base_uom, packagings = cls._row_uoms(row)
            values = {
                "name": row["nama"],
                "default_code": row["sku"],
                "type": "consu",
                "is_storable": True,
                "uom_id": base_uom.id,
                "uom_ids": [(6, 0, packagings.ids)],
                "ndi_jenis_produk": JENIS_MAP[row["jenis"]],
                "ndi_divisi_id": division.id,
                "ndi_kategori_id": category.id,
                "ndi_stok_min": float(row["stok_min"]),
                "ndi_stok_maks": float(row["stok_maks"]),
                "weight": float(row["berat_satuan1_kg"]),
            }
            values.update(
                {"ndi_%s" % column: float(row[column]) for column in COMPONENT_COLUMNS}
            )
            template = template_model.create(values)

            weights = [(base_uom, row["berat_satuan1_kg"])]
            for index, uom in enumerate(packagings, start=2):
                raw = row["berat_satuan%d_kg" % index]
                if raw:
                    weights.append((uom, raw))
            cls.env["ndi.product.uom.weight"].create(
                [
                    {
                        "product_tmpl_id": template.id,
                        "uom_id": uom.id,
                        "gross_weight": float(weight),
                    }
                    for uom, weight in weights
                ]
            )
            products[row["sku"]] = template
        return products
