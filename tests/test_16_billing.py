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
# NPWP — penjaga yang membuat "lupa mengganti" jadi berisik
# ---------------------------------------------------------------------------------------------


def test_no_real_client_was_invoiced_under_a_placeholder_npwp(evidence):
    """`res_company.vat` tidak divalidasi apa pun (`base_vat` tidak terpasang), jadi sebuah penanda
    bisa bertahan diam-diam sampai muncul di tagihan pertama klien sungguhan.

    Invariannya: selama NPWP belum berbentuk 15/16 digit, satu-satunya tenant yang boleh punya
    faktur terposting adalah yang terdaftar di `athera_billing.pilot_tenants`.
    """
    _has_billing()
    # `vat` bukan kolom di res_company pada Odoo 19 — ia field related ke partner perusahaan.
    vat = _psql(
        "select coalesce(p.vat,'') from res_company c "
        "  join res_partner p on p.id = c.partner_id where c.id = 1"
    )
    digits = "".join(c for c in vat if c.isdigit())
    looks_real = len(digits) in (15, 16) and digits == vat.replace(".", "").replace("-", "")
    pilots = _psql(
        "select coalesce(value,'') from ir_config_parameter "
        "where key = 'athera_billing.pilot_tenants'"
    )
    evidence.add("NPWP / daftar percontohan", "%r looks_real=%s / %r" % (vat, looks_real, pilots))
    if looks_real:
        pytest.skip("NPWP perusahaan sudah terisi sungguhan; penjaga ini tidak berlaku. NOT RUN.")
    allowed = {p.strip() for p in pilots.split(",") if p.strip()}
    invoiced = _psql(
        "select distinct s.tenant_slug from account_move m "
        "  join athera_subscription s on s.id = m.athera_subscription_id "
        " where m.state = 'posted'"
    )
    billed = {line for line in invoiced.splitlines() if line}
    evidence.add("tenant yang punya faktur terposting", str(sorted(billed)))
    assert billed <= allowed, (
        "tenant %s ditagih padahal NPWP perusahaan masih penanda %r"
        % (sorted(billed - allowed), vat)
    )


# ---------------------------------------------------------------------------------------------
# Dunning — penangguhan yang senyap adalah keluhan, bukan penagihan
# ---------------------------------------------------------------------------------------------


def test_outgoing_mail_is_configured(evidence):
    """Tanpa `ir.mail_server`, seluruh tangga penagihan mengantre surat yang tidak pernah pergi.

    `from_filter` ikut diperiksa: tanpa itu Odoo menulis ulang pengirim menjadi default-nya, dan
    surat yang keluar atas nama `noreply@localhost` tidak akan pernah selaras dengan SPF/DKIM.
    """
    _has_billing()
    row = _psql("select smtp_host||' '||smtp_port||' '||coalesce(from_filter,'(kosong)')"
                "||' '||coalesce(smtp_user,'(anonim)') "
                "from ir_mail_server order by sequence limit 1")
    evidence.add("mail server", row or "(belum ada)")
    assert row, "tidak ada ir_mail_server sama sekali"
    assert "(kosong)" not in row, "from_filter kosong; pengirim akan ditulis ulang"
    # Tanpa AUTH, Postfix Mailcow hanya menerima surat untuk penerima LOKAL (mynetworks tidak
    # memuat jaringan stack ini). Artinya seluruh tangga penagihan akan berhenti di gerbang dan
    # tidak satu pun klien nyata diberi tahu — kegagalan yang paling mudah tidak disadari, karena
    # surat ke alamat kita sendiri tetap terkirim dengan mulus.
    assert "(anonim)" not in row, "submission tanpa AUTH; surat ke klien luar tidak akan direlay"

    bounce = _psql("select value from ir_config_parameter where key = 'mail.bounce.alias'")
    sender = _psql("select smtp_user from ir_mail_server order by sequence limit 1")
    evidence.add("bounce alias vs akun pengirim", "%s@ vs %s" % (bounce, sender))
    # Mailcow menolak MAIL FROM yang bukan milik akun yang login (sender-login mismatch), jadi
    # alias bounce yang berbeda dari akun pengirim membuat SETIAP surat ditolak pada MAIL FROM.
    assert bounce and sender.startswith(bounce + "@"), (
        "alias bounce %r bukan milik akun %r — Postfix akan menolak MAIL FROM" % (bounce, sender)
    )


def test_the_dunning_ladder_has_all_three_notices(evidence):
    _has_billing()
    # `name` pada mail_template adalah jsonb ter-translasi; LIKE harus dikenakan pada teksnya.
    names = _psql(
        "select name->>'en_US' from mail_template "
        " where name->>'en_US' like 'ATHERA Billing%' order by 1"
    )
    evidence.add("template", names or "(belum ada)")
    assert len(names.splitlines()) == 3, names


def test_no_invoice_climbed_the_ladder_without_sending_anything(evidence):
    """Tahap penagihan hanya boleh naik kalau suratnya benar-benar diantrikan.

    Menaikkan tahap tanpa mengirim menghasilkan klien yang ditangguhkan tanpa pernah diberi tahu —
    persis keadaan yang kerja ini dimaksudkan untuk mengakhiri.
    """
    _has_billing()
    rows = _psql(
        "select m.name, m.athera_dunning_stage, "
        # `model`/`res_id` hidup di mail_message; mail.mail mewarisinya lewat mail_message_id.
        "       (select count(*) from mail_mail mm "
        "          join mail_message msg on msg.id = mm.mail_message_id "
        "         where msg.model = 'account.move' and msg.res_id = m.id) "
        "  from account_move m "
        " where m.athera_subscription_id is not null and m.athera_dunning_stage <> 'none'"
    )
    evidence.add("tahap vs surat", rows or "(belum ada yang naik tahap)")
    if not rows:
        pytest.skip("belum ada faktur yang menaiki tangga penagihan. NOT RUN.")
    for line in rows.splitlines():
        name, stage, mails = line.split("|")
        assert int(mails) > 0, "%s bertahap %s tapi nol surat pernah diantrikan" % (name, stage)


# ---------------------------------------------------------------------------------------------
# Hub-portal — baca lewat view, bukan lewat grant ke tabel Odoo
# ---------------------------------------------------------------------------------------------


def test_the_portal_role_reads_billing_through_a_view_only(evidence):
    """hub-portal tersambung sebagai `tenant_orchestrator`. Ia harus bisa membaca ringkasan
    penagihan, dan TIDAK boleh bisa membaca tabel Odoo yang menjadi sumbernya."""
    _has_billing()
    allowed = _psql("select has_table_privilege('tenant_orchestrator',"
                    "'billing.subscription_overview','SELECT')")
    evidence.add("SELECT pada view", allowed)
    assert allowed == "t", "role portal tidak bisa membaca view penagihan"

    for table in ("account_move", "athera_subscription", "res_partner"):
        leaked = _psql("select has_table_privilege('tenant_orchestrator','%s','SELECT')" % table)
        evidence.add("SELECT pada %s" % table, leaked)
        assert leaked == "f", (
            "role portal punya SELECT pada %s — hak-minimalnya sudah melebar ke basis data Odoo"
            % table
        )


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
