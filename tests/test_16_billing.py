"""Produk 2 — billing, dan seam antara tagihan dan hak akses.

Yang diuji di sini bukan aritmetika faktur. Yang diuji adalah bahwa TAGIHAN MENGGERAKKAN AKSES:
sebuah faktur yang lunas memperpanjang `valid_until`, sebuah faktur yang nunggak melewati masa
tenggang menutup pintu, dan keduanya meninggalkan jejak audit yang tidak bisa disunting.

Faktur yang benar tapi tidak berakibat apa-apa adalah pekerjaan administrasi, bukan produk.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from helpers import env as envh

pytestmark = [pytest.mark.live]

ADMIN_DB = "athera_admin"


def _psql(sql):
    """Kueri langsung ke control plane. Read-only di berkas ini kecuali disebut sebaliknya."""
    out = subprocess.run(
        ["docker", "exec", "odoo19-bct-postgres", "psql", "-U", "odoo", "-d", ADMIN_DB,
         "-tAc", sql],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        pytest.skip("control plane tidak terjangkau: %s. NOT RUN." % out.stderr.strip()[:120])
    return out.stdout.strip()


def _has_billing():
    state = _psql("select state from ir_module_module where name='custom_athera_billing'")
    if state != "installed":
        pytest.skip("custom_athera_billing belum terpasang di %s. NOT RUN." % ADMIN_DB)


# ---------------------------------------------------------------------------------------------
# Fondasi fiskal — angka yang salah di sini menghasilkan tagihan yang salah ke klien nyata
# ---------------------------------------------------------------------------------------------


def test_company_bills_in_rupiah(evidence):
    """Perusahaan pernah ber-mata-uang USD sementara harga paket dalam rupiah.

    Faktur pertama akan berbunyi $1.500.000. Ini kasus yang hanya bisa diperbaiki selagi belum
    ada entri jurnal, jadi ia layak dijaga oleh sebuah uji, bukan oleh ingatan.
    """
    _has_billing()
    row = _psql(
        "select cur.name, c.chart_template from res_company c "
        "join res_currency cur on cur.id = c.currency_id where c.id = 1"
    )
    evidence.add("mata uang + chart", row)
    currency, chart = row.split("|")
    assert currency == "IDR", row
    assert chart == "id_psak", row


def test_ppn_is_the_effective_eleven_percent(evidence):
    """PMK-131/2024: tarif 12% atas DPP Nilai Lain 11/12 = 11% dari harga jual.

    `account.tax` di Odoo CE tidak punya field rasio DPP, jadi yang bisa dimodelkan adalah tarif
    efektifnya. Menyetel 12 atas dasar penuh akan menagih setiap klien lebih ~0,9%.
    """
    _has_billing()
    rows = _psql(
        "select type_tax_use || ' ' || amount || ' ' || (name->>'en_US') "
        "from account_tax order by id"
    )
    evidence.add("pajak", rows)
    assert rows, "tidak ada pajak sama sekali"
    for line in rows.splitlines():
        assert line.split()[1] == "11.0000", line
        assert "DPP Nilai Lain" in line, line


# ---------------------------------------------------------------------------------------------
# Seam — tagihan menggerakkan akses
# ---------------------------------------------------------------------------------------------


def test_a_paid_invoice_extends_access(evidence):
    """Setiap faktur lunas harus punya jejak `billing_payment_applied` dan tenant yang valid_until-nya
    mencapai akhir periode faktur itu."""
    _has_billing()
    rows = _psql(
        "select m.name, m.payment_state, m.athera_access_applied, "
        "       to_char(m.athera_period_end,'YYYY-MM-DD'), s.tenant_slug "
        "  from account_move m join athera_subscription s on s.id = m.athera_subscription_id "
        " where m.payment_state = 'paid' order by m.id"
    )
    evidence.add("faktur lunas", rows or "(belum ada)")
    if not rows:
        pytest.skip("belum ada faktur lunas untuk diperiksa. NOT RUN.")
    for line in rows.splitlines():
        name, _pstate, applied, period_end, slug = line.split("|")
        assert applied == "t", "%s lunas tapi akses tidak pernah diperpanjang" % name
        valid = _psql("select to_char(valid_until,'YYYY-MM-DD') from tenant_registry.tenants "
                      "where slug = '%s'" % slug)
        assert valid >= period_end, "%s: valid_until %s < akhir periode %s" % (name, valid, period_end)


def test_every_access_change_left_an_audit_row(evidence):
    """Tidak ada perubahan hak akses karena billing yang terjadi tanpa jejak."""
    _has_billing()
    applied = int(_psql("select count(*) from account_move where athera_access_applied"))
    logged = int(_psql("select count(*) from tenant_registry.action_log "
                       "where action = 'billing_payment_applied'"))
    evidence.add("faktur diterapkan vs baris audit", "%s / %s" % (applied, logged))
    assert logged >= applied, "%s faktur memperpanjang akses tapi hanya %s tercatat" % (applied, logged)


def test_the_audit_chain_is_unbroken(evidence):
    """Baris billing ditulis lewat INSERT biasa; rantainya dihitung trigger.

    Kalau modul billing pernah mencoba menghitung hash sendiri, di sinilah ia akan ketahuan.
    """
    _has_billing()
    broken = _psql("select count(*) from tenant_registry.verify_action_chain()")
    total = _psql("select count(*) from tenant_registry.action_log")
    evidence.add("mata rantai rusak / total baris", "%s / %s" % (broken, total))
    assert broken == "0", "rantai audit putus di %s baris" % broken


def test_the_audit_log_refuses_to_be_edited(evidence):
    """Sebuah audit yang bisa disunting bukan audit. Diuji dengan mencoba menyuntingnya."""
    _has_billing()
    out = subprocess.run(
        ["docker", "exec", "odoo19-bct-postgres", "psql", "-U", "odoo", "-d", ADMIN_DB, "-tAc",
         "update tenant_registry.action_log set outcome='dipalsukan' "
         "where action like 'billing%' returning id"],
        capture_output=True, text=True, timeout=60,
    )
    evidence.add("percobaan UPDATE", (out.stderr or out.stdout).strip()[:160])
    assert out.returncode != 0, "UPDATE pada action_log BERHASIL — audit bisa disunting"


# ---------------------------------------------------------------------------------------------
# Harga — satu sumber kebenaran
# ---------------------------------------------------------------------------------------------


def test_invoice_amounts_come_from_the_registry(evidence):
    """Harga hidup di `tenant_registry.plans` dan tidak boleh punya salinan kedua di Odoo.

    Faktur diperiksa terhadap registry, bukan terhadap `list_price` produk — kalau keduanya
    menyimpang, yang benar adalah registry dan uji ini yang harus menyalak.
    """
    _has_billing()
    rows = _psql(
        "select m.name, s.plan_code, m.amount_untaxed::numeric(14,2), p.price_month::numeric(14,2) "
        "  from account_move m "
        "  join athera_subscription s on s.id = m.athera_subscription_id "
        "  join tenant_registry.plans p on p.code = s.plan_code "
        " where m.state = 'posted' order by m.id"
    )
    evidence.add("faktur vs harga registry", rows or "(belum ada faktur)")
    if not rows:
        pytest.skip("belum ada faktur terposting. NOT RUN.")
    for line in rows.splitlines():
        name, plan, untaxed, registry_price = line.split("|")
        assert untaxed == registry_price, (
            "%s (%s): DPP %s tidak sama dengan harga registry %s" % (name, plan, untaxed, registry_price)
        )


def test_a_custom_priced_plan_is_never_invoiced_as_zero(evidence):
    """Paket "Hubungi kami" berharga NULL. Menagihnya nol jauh lebih buruk daripada menolak:
    yang pertama terlihat persis seperti klien yang sudah membayar."""
    _has_billing()
    custom = _psql("select code from tenant_registry.plans where price_month is null")
    evidence.add("paket berharga custom", custom or "(tidak ada)")
    if not custom:
        pytest.skip("tidak ada paket berharga NULL. NOT RUN.")
    zero = _psql(
        "select count(*) from account_move m join athera_subscription s "
        "  on s.id = m.athera_subscription_id "
        " where s.plan_code in (%s) and m.state = 'posted' and m.amount_untaxed = 0"
        % ",".join("'%s'" % c for c in custom.splitlines())
    )
    assert zero == "0", "%s faktur nol terbit untuk paket berharga custom" % zero
