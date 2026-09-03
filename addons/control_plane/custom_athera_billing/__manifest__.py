{
    "name": "ATHERA Billing",
    "summary": "Langganan per tenant, faktur berulang, dan seam penagihan ke hak akses.",
    "description": """
ATHERA Billing — produk 2 (SaaS Management)
===========================================

Menutup lubang terakhir produk 2: harga sudah bisa diatur dan akses sudah bisa dicabut,
tetapi tidak ada yang menagih siapa pun.

Satu langganan per tenant. Cron menerbitkan faktur bulanan, dan status pembayaran faktur
itulah yang menggerakkan hak akses:

  faktur lunas   -> tenant_registry.tenants.valid_until diperpanjang ke akhir periode
  nunggak > masa tenggang -> tenant_registry.tenants.state = 'suspended'

Kedua arah menulis tenant_registry.action_log dalam transaksi yang sama.
""",
    "version": "19.0.1.0.0",
    "author": "ATHERA Digital Solution",
    "category": "Accounting/Accounting",
    "license": "LGPL-3",
    "depends": ["base", "mail", "account", "custom_super_admin"],
    "data": [
        "security/billing_security.xml",
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "data/mail_template.xml",
        "data/ir_cron.xml",
        "views/athera_subscription_views.xml",
        "views/account_move_views.xml",
        "views/payment_claim_views.xml",
        "views/menu_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
