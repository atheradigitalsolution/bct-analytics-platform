# -*- coding: utf-8 -*-
"""Mesin waterfall harga jual HJ9 -> HJ1 (requirement NDI pasal 13).

Satu-satunya implementasi rumus di seluruh dua modul NDI. ``product.template``
memakainya untuk mengisi ``ndi_hj1``..``ndi_hj9``; ``ndi.price.matrix`` di
``custom_ndi_pricing`` memakai hasil itu apa adanya lewat field ``related``.
Kalau rumus ini salah, ia salah di satu tempat saja.

Rantainya, harfiah dari pasal 13::

    HJ9 = HPP Dasar
    HJ8 = HJ9 + HJ9 x Profit%
    HJ7 = HJ8 + HJ8 x Risiko%
    HJ6 = HJ7 + HJ7 x Pajak%
    HJ5 = HJ6 + Ongkir (Rp)
    HJ4 = HJ5 + Pembulatan (Rp)
    HJ3 = HJ4 + Insentif Kwartal (Rp)
    HJ2 = HJ3 + Insentif Bulanan (Rp)
    HJ1 = HJ2 + Margin HET (Rp)

Dua hal yang tidak boleh diubah tanpa mengubah data uji:

1. **Pembulatan terjadi di setiap tingkat**, bukan sekali di akhir. HJ8 yang
   dibulatkan ke 2 desimal adalah basis perhitungan HJ7. Menunda pembulatan
   menghasilkan selisih rupiah pada produk dengan tiga persentase berturut-turut.
2. **Aritmetika Decimal ROUND_HALF_UP**, bukan float. ``round()`` Python memakai
   banker's rounding (0.5 dibulatkan ke genap) dan akan meleset pada nilai seperti
   x.xx5. Nilai float dari ORM dikonversi lewat ``repr()`` supaya representasi
   terpendek yang round-trip yang dipakai, bukan ekor biner 0.00000000001.

"Pembulatan (Rp)" di sini adalah **nominal yang ditambahkan**, bukan kelipatan
pembulatan ala ``product.pricelist.item.price_round``. Ini keputusan yang sudah
dikunci di dokumen 02 (D1) dan tercermin di data sampel: HJ4 = HJ5 + nominal.
"""

from decimal import Decimal, ROUND_HALF_UP

#: Urutan komponen sesuai pasal 13. Dipakai juga sebagai daftar field
#: ``ndi_<key>`` pada ``product.template`` agar keduanya tidak bisa berpisah.
COMPONENT_KEYS = (
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

HJ_LEVELS = tuple(range(1, 10))

_CENT = Decimal("0.01")
_HUNDRED = Decimal("100")


def _dec(value):
    """Float ORM -> Decimal tanpa ekor biner."""
    return Decimal(repr(float(value or 0.0)))


def _q2(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def compute_hj_waterfall(components):
    """Hitung HJ1..HJ9 dari dict komponen.

    :param components: mapping berisi kunci di :data:`COMPONENT_KEYS`.
        Kunci yang hilang dianggap 0.
    :return: dict ``{"hj1": float, ..., "hj9": float}``
    """
    get = lambda key: _dec(components.get(key, 0.0))  # noqa: E731

    hj9 = _q2(get("hpp_dasar"))
    hj8 = _q2(hj9 + hj9 * get("profit_pct") / _HUNDRED)
    hj7 = _q2(hj8 + hj8 * get("risiko_pct") / _HUNDRED)
    hj6 = _q2(hj7 + hj7 * get("pajak_pct") / _HUNDRED)
    hj5 = _q2(hj6 + get("ongkir_rp"))
    hj4 = _q2(hj5 + get("pembulatan_rp"))
    hj3 = _q2(hj4 + get("insentif_kwartal_rp"))
    hj2 = _q2(hj3 + get("insentif_bulanan_rp"))
    hj1 = _q2(hj2 + get("margin_het_rp"))

    return {
        "hj1": float(hj1),
        "hj2": float(hj2),
        "hj3": float(hj3),
        "hj4": float(hj4),
        "hj5": float(hj5),
        "hj6": float(hj6),
        "hj7": float(hj7),
        "hj8": float(hj8),
        "hj9": float(hj9),
    }
