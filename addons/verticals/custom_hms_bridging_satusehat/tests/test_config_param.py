# -*- coding: utf-8 -*-
"""A mistyped system parameter must not read as a server fault.

``ir.config_parameter.get_param`` falls back to its default when the key is
absent or empty, but not when it holds text: ``float("lima")`` raises
ValueError, and at the API boundary that becomes a 500 "kesalahan sistem,
hubungi administrator" -- for a value the administrator typed themselves.
The parameter is editable by hand at Pengaturan > Teknis > Parameter Sistem,
so that path is real for ``base.group_system``.

``requests.post`` is stubbed rather than left to the harness: Odoo fails a
test that merely *attempted* an outbound call, even when the exception is
caught, so "it reached the network" cannot be used as an assertion. A stub
also lets each test say precisely whether a refresh was attempted, which is
the actual question.
"""
import json
import time
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

KEY = "hms.satusehat.token_expires"
READER_LOGGER = "odoo.addons.custom_hms_base.tools.config_param"


class _Response:
    status_code = 200
    text = json.dumps({"access_token": "token-baru", "expires_in": 3600})


@tagged("post_install", "-at_install", "hms")
class SatusehatConfigParamCase(TransactionCase):

    def _param(self):
        return self.env["ir.config_parameter"].sudo()

    def _prime_cache(self, expires_value):
        self._param().set_param("hms.satusehat.token", "token-lama")
        self._param().set_param(KEY, expires_value)

    def _token_with_stub(self):
        """Run _token() with the network stubbed; report if refresh happened."""
        with patch(
            "odoo.addons.custom_hms_bridging_satusehat.models"
            ".hms_satusehat_client.requests.post",
            return_value=_Response(),
        ) as posted:
            token = self.env["hms.satusehat.client"]._token()
        return token, posted.called

    # --- tolerates rubbish -------------------------------------------------
    def test_unconvertible_value_does_not_raise_valueerror(self):
        self._prime_cache("lima")
        try:
            self._token_with_stub()
        except ValueError as exc:
            self.fail(
                "Nilai parameter salah ketik menjadi ValueError, yang di batas "
                f"API terbaca sebagai 500 'kesalahan sistem': {exc}"
            )

    def test_unconvertible_value_is_logged_with_key_and_value(self):
        self._prime_cache("lima")
        with self.assertLogs(READER_LOGGER, level="WARNING") as logged:
            self._token_with_stub()
        blob = "\n".join(logged.output)
        self.assertIn(KEY, blob, "Peringatan harus menyebut kunci parameternya.")
        self.assertIn("lima", blob, "Peringatan harus menyebut nilai yang ditemukan.")

    def test_unconvertible_value_is_treated_as_stale_not_as_live(self):
        # Falling back must mean "expired", never "valid far into the future":
        # a default that looked live would keep serving a stale token forever.
        self._prime_cache("lima")
        _token, refreshed = self._token_with_stub()
        self.assertTrue(refreshed, "Nilai tak terbaca harus memicu penyegaran.")

    # --- positive controls -------------------------------------------------
    def test_a_valid_value_is_used_as_given(self):
        # Without this, a reader that always returned the default would pass
        # every test above with flying colours while ignoring real config.
        self._prime_cache(str(time.time() + 3600))
        token, refreshed = self._token_with_stub()
        self.assertFalse(refreshed, "Token yang masih hidup tidak boleh disegarkan.")
        self.assertEqual(token, "token-lama", "Nilai sah harus dipakai apa adanya.")

    def test_a_valid_but_past_value_is_respected_too(self):
        # The mirror: the reader must not round a real number up to "live".
        self._prime_cache(str(time.time() - 3600))
        _token, refreshed = self._token_with_stub()
        self.assertTrue(refreshed, "Token kedaluwarsa wajib disegarkan.")

    def test_no_warning_is_logged_for_a_healthy_value(self):
        # A reader that warned on every read would bury the real typo.
        self._prime_cache(str(time.time() + 3600))
        with self.assertNoLogs(READER_LOGGER, level="WARNING"):
            self._token_with_stub()

    def test_an_absent_key_uses_the_caller_default(self):
        # get_param returns False for a missing key, and float(False) is 0.0 --
        # a wrong answer that raises nothing and logs nothing. Found by probing
        # the reader directly; the tests above all set the parameter first and
        # so could never have seen it.
        from odoo.addons.custom_hms_base.tools.config_param import config_float
        self._param().set_param("hms.lead.absent.probe", False)
        self.assertEqual(
            config_float(self.env, "hms.lead.absent.probe", 99.0), 99.0,
            "Kunci yang tidak ada harus memakai bawaan pemanggil, bukan 0.0.",
        )

    def test_an_empty_value_uses_the_caller_default(self):
        from odoo.addons.custom_hms_base.tools.config_param import config_float
        self._param().set_param("hms.lead.empty.probe", "   ")
        self.assertEqual(
            config_float(self.env, "hms.lead.empty.probe", 99.0), 99.0)
