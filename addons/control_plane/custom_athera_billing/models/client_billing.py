# -*- coding: utf-8 -*-
"""Permukaan penagihan SISI KLIEN — dua view yang menyaring dirinya sendiri, dan satu antrean klaim.

BEDANYA DENGAN `billing_overview.py`. Berkas itu melayani OPERATOR: satu baris per tenant, semua
tenant sekaligus, dibaca hub-portal di balik gerbang `is_super_admin`. Berkas ini melayani KLIEN:
faktur miliknya sendiri, dan tidak boleh ada satu pun baris tenant lain yang bisa keluar dari sini.

KENAPA VIEW MENYARING DIRINYA SENDIRI, BUKAN SEKADAR MENGANDALKAN `WHERE` DI APLIKASI.
`current_setting('athera.tenant_slug', true)` mengembalikan NULL saat GUC tidak diset, dan
`s.tenant_slug = NULL` tidak pernah benar — jadi kueri tanpa konteks tenant menghasilkan NOL baris,
bukan SEMUA baris. Itu kebalikan dari jalur fail-open di `login-gateway/app/registry.py`, dan itu
memang disengaja: portal penagihan tidak boleh mewarisi default "kalau tidak terkonfigurasi, izinkan".
Aplikasi TETAP menulis `WHERE tenant_slug = $1` dari klaim JWT. Dua pagar, dan masing-masing bisa
dilepas satu per satu dalam uji untuk membuktikan uji itu benar-benar bisa merah.

BATAS KEJUJURAN PAGAR INI. GUC bisa disetel oleh siapa pun yang memegang koneksi, jadi ia BUKAN
pertahanan terhadap proses portal yang jahat — ia pertahanan terhadap kueri portal yang KELIRU,
dan terhadap kredensial yang bocor tanpa disertai kode yang tahu harus menyetel apa. Batas yang
sesungguhnya tetap sama seperti di contract 05: hanya proses portal yang memegang kredensial, dan
proses itu mengambil tenant HANYA dari JWT terverifikasi.

VIEW INI TIDAK PERNAH MEMUAT FAKTUR DRAF. `state='posted'` bukan kosmetik: draf adalah pekerjaan
akuntansi yang belum jadi, dan menagihkan angka yang masih bisa berubah kepada klien adalah cara
tercepat kehilangan kepercayaan yang menagih itu sendiri butuhkan.
"""

import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

#: Role yang dipakai insight-portal untuk permukaan klien. Hak-minimal: SELECT pada dua view,
#: INSERT pada satu tabel. Tidak ada grant apa pun pada tabel Odoo lain.
PORTAL_ROLE = "billing_portal"

#: Role operator (hub-portal). Sudah ada; di sini ia hanya menerima hak atas antrean klaim.
OPERATOR_ROLE = "tenant_orchestrator"

#: Nama GUC yang membawa tenant ke dalam sesi database. Sejajar dengan `app.tenant_id` di warehouse.
TENANT_GUC = "athera.tenant_slug"


class AtheraPaymentClaim(models.Model):
    """Klien menyatakan "saya sudah bayar". Operator yang memutuskan apakah itu benar.

    TIDAK ADA JALUR APA PUN dari baris di tabel ini menuju `account_move.payment_state`. Klaim
    adalah pesan, bukan pembayaran. Rekonsiliasi tetap perbuatan operator di Odoo, dengan jurnal
    dan jejak auditnya — persis alasan `billing_overview.py` menolak menyalin tombol Odoo ke portal.

    Klien mengisi data terstruktur, bukan mengunggah berkas. Menerima unggahan di permukaan yang
    menghadap klien menambah penyimpanan dan pemindaian malware untuk proses yang tetap manual:
    operator akan mencocokkan ke rekening koran, bukan membaca lampiran.
    """

    _name = "athera.payment.claim"
    _description = "Klaim pembayaran dari klien"
    _order = "create_date desc, id desc"
    _rec_name = "invoice_number"

    tenant_slug = fields.Char(required=True, index=True, readonly=True)
    invoice_id = fields.Integer(string="ID faktur", readonly=True)
    invoice_number = fields.Char(readonly=True)
    amount = fields.Float(string="Jumlah diklaim", readonly=True)
    paid_on = fields.Date(string="Tanggal transfer", readonly=True)
    bank_name = fields.Char(string="Bank pengirim", readonly=True)
    reference = fields.Char(string="Nomor referensi", readonly=True)
    note = fields.Text(readonly=True)
    claimed_by_uid = fields.Integer(string="Odoo uid pengklaim", readonly=True)
    state = fields.Selection(
        [("new", "Baru"), ("verified", "Terverifikasi"), ("rejected", "Ditolak")],
        default="new", required=True, index=True,
    )
    handled_note = fields.Text(string="Catatan operator")

    def init(self):
        """DDL untuk seluruh permukaan klien.

        KENAPA DI SINI DAN BUKAN DI `post_init_hook`. Hook hanya berjalan saat INSTALL; `init()`
        dipanggil Odoo pada SETIAP upgrade modul. View yang lahir sekali lalu tidak pernah menyusul
        perubahan kolomnya adalah view yang diam-diam menyajikan bentuk lama. Alasan yang sama
        sudah ditulis di `billing_overview.py`; ini mengikutinya, bukan menemukannya ulang.
        """
        cr = self.env.cr
        cr.execute("CREATE SCHEMA IF NOT EXISTS billing")

        # --- pagar tulis: tenant_slug DIPAKSA dari GUC, tidak pernah dari yang menulis ---------
        # Tanpa ini, INSERT grant pada tabel ini berarti portal bisa mencatat klaim atas nama
        # tenant mana pun. Trigger membuat kolom itu tidak bisa dipilih oleh pemanggil.
        cr.execute("""
            CREATE OR REPLACE FUNCTION billing.force_claim_tenant() RETURNS trigger AS $fn$
            DECLARE t text := current_setting(%s, true);
            BEGIN
                IF t IS NULL OR t = '' THEN
                    RAISE EXCEPTION 'athera.tenant_slug tidak diset: klaim ditolak (fail-closed)';
                END IF;
                NEW.tenant_slug := t;
                RETURN NEW;
            END $fn$ LANGUAGE plpgsql;
        """, (TENANT_GUC,))
        cr.execute("DROP TRIGGER IF EXISTS force_claim_tenant ON athera_payment_claim")
        cr.execute("""
            CREATE TRIGGER force_claim_tenant BEFORE INSERT ON athera_payment_claim
            FOR EACH ROW EXECUTE FUNCTION billing.force_claim_tenant()
        """)

        # --- view faktur klien -----------------------------------------------------------------
        cr.execute("""
            CREATE OR REPLACE VIEW billing.tenant_invoice AS
            SELECT m.id, s.tenant_slug,
                   m.name AS invoice_number, m.invoice_date, m.invoice_date_due,
                   m.amount_untaxed, m.amount_tax, m.amount_total, m.amount_residual,
                   cur.name AS currency, m.payment_state,
                   CASE WHEN m.payment_state IN ('paid', 'in_payment', 'reversed') THEN 'paid'
                        WHEN m.invoice_date_due < CURRENT_DATE                     THEN 'overdue'
                        ELSE 'posted' END AS client_status
              FROM account_move m
              JOIN athera_subscription s ON s.id = m.athera_subscription_id
              LEFT JOIN res_currency cur ON cur.id = m.currency_id
             WHERE m.move_type = 'out_invoice'
               AND m.state = 'posted'
               AND COALESCE(current_setting('%s', true), '') <> ''
               AND s.tenant_slug = current_setting('%s', true)
        """ % (TENANT_GUC, TENANT_GUC))

        # --- view langganan berjalan -------------------------------------------------------------
        # `sisa_hari` dihitung di database, bukan di portal: satu tempat yang tahu jamnya, dan
        # zona waktu server adalah satu-satunya jam yang juga dipakai gerbang saat menutup akses.
        cr.execute("""
            CREATE OR REPLACE VIEW billing.tenant_subscription AS
            SELECT s.tenant_slug, t.display_name, s.plan_code, s.state AS subscription_state,
                   t.state AS tenant_state, t.valid_until, s.next_invoice_date,
                   p.price_month, p.currency,
                   CASE WHEN t.valid_until IS NULL THEN NULL
                        ELSE GREATEST(0, (t.valid_until::date - CURRENT_DATE)) END AS sisa_hari
              FROM athera_subscription s
              LEFT JOIN tenant_registry.tenants t ON t.slug = s.tenant_slug
              LEFT JOIN tenant_registry.plans   p ON p.code = s.plan_code
             WHERE COALESCE(current_setting('%s', true), '') <> ''
               AND s.tenant_slug = current_setting('%s', true)
        """ % (TENANT_GUC, TENANT_GUC))

        # --- view klaim milik klien sendiri ------------------------------------------------------
        cr.execute("""
            CREATE OR REPLACE VIEW billing.tenant_payment_claim AS
            SELECT id, tenant_slug, invoice_id, invoice_number, amount, paid_on,
                   bank_name, reference, state, create_date
              FROM athera_payment_claim
             WHERE COALESCE(current_setting('%s', true), '') <> ''
               AND tenant_slug = current_setting('%s', true)
        """ % (TENANT_GUC, TENANT_GUC))

        self._grant(PORTAL_ROLE, portal=True)
        self._grant(OPERATOR_ROLE, portal=False)

    def _grant(self, role, portal):
        """Grant kalau role ada; kalau tidak, lewati dan katakan begitu di log.

        Instalasi tanpa control plane tidak punya role ini, dan modul tetap harus bisa dipasang —
        pola yang sama dipakai `billing_overview.py`.
        """
        cr = self.env.cr
        cr.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if not cr.fetchone():
            _logger.warning("role %s tidak ada; grant penagihan klien dilewati", role)
            return
        # Nama role tidak bisa diparameterkan di GRANT, jadi ia konstanta modul dan bukan masukan.
        cr.execute('GRANT USAGE ON SCHEMA billing TO "%s"' % role)
        if portal:
            cr.execute(
                'GRANT SELECT ON billing.tenant_invoice, billing.tenant_subscription,'
                ' billing.tenant_payment_claim TO "%s"' % role)
            # INSERT saja. Tanpa SELECT/UPDATE/DELETE pada tabelnya: portal boleh menyampaikan
            # klaim, tidak boleh membaca klaim tenant lain maupun mengubah putusan operator.
            cr.execute('GRANT INSERT ON athera_payment_claim TO "%s"' % role)
            cr.execute('GRANT USAGE ON SEQUENCE athera_payment_claim_id_seq TO "%s"' % role)
        else:
            cr.execute('GRANT SELECT, UPDATE ON athera_payment_claim TO "%s"' % role)
        _logger.info("hak penagihan klien diberikan ke %s", role)
