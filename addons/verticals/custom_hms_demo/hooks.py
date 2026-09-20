# -*- coding: utf-8 -*-
"""Install-time guard and seeding entry point."""
import logging

from odoo import SUPERUSER_ID, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Refuse to seed anything outside a demo database.

    The guard is a hard failure rather than a warning. Demo patients in a
    production database consume real medical record numbers, and those numbers
    can never be reissued — there is no clean recovery, only a permanent gap
    that auditors will ask about.
    """
    dbname = env.cr.dbname
    if not dbname.endswith("_demo"):
        raise UserError(
            _("custom_hms_demo hanya boleh dipasang di database demo. Database "
              "'%s' tidak berakhiran '_demo', sehingga pemasangan dibatalkan.") % dbname
        )
    _logger.info("SIMRS: menyiapkan data demo di %s", dbname)
    # ``seed_all`` memanggil pagar yang sama sekali lagi sebelum menyentuh
    # apa pun. Pemeriksaan ganda itu disengaja: hook dan berkas data adalah
    # dua jalur masuk yang berbeda, dan masing-masing harus berdiri sendiri.
    env["hms.demo.builder"].seed_all()
