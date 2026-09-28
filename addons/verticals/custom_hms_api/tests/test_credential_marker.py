# -*- coding: utf-8 -*-
"""Mengganti sandi harus mencabut token yang sudah beredar.

JWT berumur pendek tetapi tidak dapat dicabut. Ganti-sandi adalah tindakan
pertama seseorang yang curiga akunnya diambil orang, dan tanpa penanda ini
tindakan itu tidak melakukan apa pun terhadap penyerangnya sampai tokennya
kedaluwarsa sendiri.

Penandanya bersandar pada API PRIVAT Odoo (`_get_session_token_fields`,
`_compute_session_token`). Kalau kumpulan fieldnya berubah, pembatalan ini
berhenti bekerja tanpa melempar apa pun — token lama hanya tetap berlaku.
`test_session_token_fields_still_cover_credentials` ada supaya kegagalan itu
berisik, bukan diam.
"""
import json

from odoo.tests import HttpCase, tagged

from .common import fixture_password

STAFF_GROUP = "custom_hms_base.group_hms_staff"


@tagged("post_install", "-at_install", "hms")
class CredentialMarkerCase(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.password = fixture_password()
        cls.other_password = fixture_password()
        cls.user = cls.env["res.users"].create({
            "name": "Uji Penanda Kredensial",
            "login": "zt-stk@simrs-demo.invalid",
            "password": cls.password,
            "group_ids": [(4, cls.env.ref(STAFF_GROUP).id)],
        })
        cls.other = cls.env["res.users"].create({
            "name": "Uji Penanda Lain",
            "login": "zt-stk-lain@simrs-demo.invalid",
            "password": cls.other_password,
            "group_ids": [(4, cls.env.ref(STAFF_GROUP).id)],
        })

    def _host(self):
        return "%s.test.invalid" % self.env.cr.dbname

    def _token(self, user, password):
        response = self.url_open(
            "/api/v1/auth/login",
            data=json.dumps({"login": user.login, "password": password}),
            headers={"Content-Type": "application/json", "Host": self._host()},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        return response.json()["access_token"]

    def _me(self, token):
        return self.url_open(
            "/api/v1/me",
            headers={"Host": self._host(), "Authorization": "Bearer %s" % token},
        )

    # --- perilaku Odoo yang kita sandari ----------------------------------
    def test_session_token_internals_still_exist(self):
        Users = self.env["res.users"]
        for name in ("_get_session_token_fields", "_session_token_get_values",
                     "_session_token_hash_compute"):
            self.assertTrue(
                hasattr(Users, name),
                "res.users.%s hilang. Penanda kredensial SIMRS memakai dua "
                "primitif TIDAK ter-cache itu supaya pencabutan tidak "
                "bergantung pada invalidasi cache lintas proses. Tanpa "
                "keduanya, pencabutan berhenti bekerja tanpa melempar apa "
                "pun. Lihat MODULE_KNOWLEDGE.md §10." % name,
            )

    def test_session_token_fields_still_cover_credentials(self):
        fields = self.env["res.users"]._get_session_token_fields()
        for needed in ("password", "login", "active"):
            self.assertIn(
                needed, fields,
                "res.users._get_session_token_fields() tidak lagi memuat %r. "
                "Pencabutan token SIMRS bersandar pada field itu, dan tanpa "
                "kehadirannya pencabutan berhenti bekerja TANPA melempar "
                "apa pun. Perbarui credential_marker() di controllers/base.py "
                "sebelum melanjutkan." % needed,
            )

    # --- pencabutan --------------------------------------------------------
    def test_password_change_rejects_an_existing_token(self):
        token = self._token(self.user, self.password)
        self.assertEqual(self._me(token).status_code, 200)
        self.user.write({"password": fixture_password()})
        response = self._me(token)
        self.assertEqual(response.status_code, 401, response.text[:300])
        self.assertEqual(response.json()["error"]["code"], "unauthenticated")

    def test_deactivating_the_account_rejects_an_existing_token(self):
        # Gratis dari `active` di daftar field — tetapi dibuktikan, bukan
        # diasumsikan ikut hanya karena namanya ada di himpunan.
        token = self._token(self.user, self.password)
        self.assertEqual(self._me(token).status_code, 200)
        self.user.write({"active": False})
        self.assertEqual(self._me(token).status_code, 401)

    def test_a_token_without_the_marker_is_rejected(self):
        # Token yang terbit sebelum fitur ini ada tidak boleh diterima diam-
        # diam: klaim yang hilang harus gagal tertutup.
        import jwt as pyjwt
        from odoo.addons.custom_hms_api.controllers.base import jwt_secret, ALGORITHM
        token = self._token(self.user, self.password)
        claims = pyjwt.decode(token, jwt_secret(), algorithms=[ALGORITHM])
        claims.pop("stk", None)
        forged = pyjwt.encode(claims, jwt_secret(), algorithm=ALGORITHM)
        self.assertEqual(self._me(forged).status_code, 401)

    # --- kontrol positif ---------------------------------------------------
    def test_a_token_issued_after_the_change_still_works(self):
        # Tanpa ini, penanda yang selalu tidak cocok akan lolos setiap uji
        # pencabutan di atas sambil membuat login mustahil.
        new_password = fixture_password()
        self.user.write({"password": new_password})
        token = self._token(self.user, new_password)
        self.assertEqual(self._me(token).status_code, 200)

    def test_another_users_token_survives(self):
        # Pencabutan yang terlalu lebar akan lolos uji "token lama ditolak"
        # sambil melogout seluruh rumah sakit.
        victim = self._token(self.user, self.password)
        bystander = self._token(self.other, self.other_password)
        self.user.write({"password": fixture_password()})
        self.assertEqual(self._me(victim).status_code, 401)
        self.assertEqual(self._me(bystander).status_code, 200,
                         "Token pengguna lain tidak boleh ikut gugur.")

    def test_an_unrelated_edit_does_not_revoke(self):
        # Menyunting nama seorang dokter tidak boleh melogout siapa pun.
        token = self._token(self.user, self.password)
        self.user.write({"name": "Nama Disunting"})
        self.assertEqual(self._me(token).status_code, 200)

    # --- pertanyaan inti: apakah ormcache benar-benar dibersihkan? ---------
    def test_the_marker_changes_without_any_restart_or_manual_cache_clear(self):
        """Inti seluruh rancangan ini, diukur langsung.

        `_compute_session_token` di-cache `@ormcache('sid')`. Kalau cache itu
        TIDAK terbersihkan pada jalur ganti sandi, penanda lama akan terus
        dikembalikan dan pencabutan hanya berlaku setelah restart — yaitu
        tidak berlaku untuk kasus yang mekanisme ini dibangun untuknya.

        Sengaja TIDAK memanggil `env.registry.clear_cache()` di sini:
        membersihkan cache sendiri lalu menyatakan nilainya berubah tidak
        membuktikan apa pun tentang jalur ganti sandi. Probe pertama saya
        melakukan itu dan lolos atas mekanisme yang belum terbukti.

        Komentar di sumber Odoo menyebut `password` ada di daftar field itu
        "untuk mekanisme invalidasi cache" — itu pernyataan NIAT penulisnya,
        bukan pengamatan atas build ini.
        """
        from odoo.addons.custom_hms_api.controllers.base import credential_marker
        before = credential_marker(self.user)
        self.user.write({"password": fixture_password()})
        after = credential_marker(self.user)
        self.assertNotEqual(
            before, after,
            "Penanda tidak berubah setelah ganti sandi dalam proses yang sama. "
            "ormcache tidak dibersihkan pada jalur ini, sehingga pencabutan "
            "token hanya bekerja setelah restart.",
        )

    def test_the_marker_is_stable_when_nothing_changes(self):
        # Pasangan kontrol: penanda yang berubah pada setiap pembacaan akan
        # lolos uji di atas sambil menolak setiap permintaan yang sah.
        from odoo.addons.custom_hms_api.controllers.base import credential_marker
        self.assertEqual(credential_marker(self.user), credential_marker(self.user))

    def test_two_users_do_not_share_one_marker(self):
        # `@ormcache('sid')` menurunkan kunci HANYA dari sid; `self` tidak
        # ikut. sid tetap akan membuat seluruh pengguna berbagi satu entri.
        from odoo.addons.custom_hms_api.controllers.base import credential_marker
        self.assertNotEqual(
            credential_marker(self.user), credential_marker(self.other),
            "Dua pengguna berbagi satu penanda: sid tidak membawa id pengguna.",
        )

    def test_a_change_made_without_any_in_process_notice_is_seen(self):
        """Pengganti uji lintas proses yang tidak bisa dijalankan kerangka ini.

        `HttpCase` hidup di satu proses, jadi "worker lain mengganti sandi"
        tidak dapat dipentaskan langsung. SQL mentah adalah pengamatan yang
        setara: ia melewati `write()`, jadi tidak ada `clear_cache()`, tidak
        ada `signal_changes()`, dan tidak ada pemberitahuan apa pun di dalam
        proses ini — persis keadaan worker HTTP ketika `odoo shell` atau
        sebuah cron mengganti sandi.

        Versi ter-cache GAGAL di sini, dan itulah cacat yang lolos dua belas
        kontrol sebelumnya: penandanya tetap basi sampai restart.

        Ini tetap pengganti. Bukti sesungguhnya adalah pemeriksaan hidup di
        tumpukan berjalan; lihat MODULE_KNOWLEDGE.md §10.
        """
        from odoo.addons.custom_hms_api.controllers.base import credential_marker
        before = credential_marker(self.user)
        self.env.cr.execute(
            "UPDATE res_users SET password = %s WHERE id = %s",
            ("$pbkdf2-sha512$diganti-proses-lain", self.user.id),
        )
        self.assertNotEqual(
            credential_marker(self.user), before,
            "Penanda tidak melihat perubahan yang terjadi tanpa pemberitahuan "
            "dalam proses. Kalau ini merah, penandanya di-cache lagi dan "
            "pencabutan token hanya bekerja setelah restart.",
        )

    def test_the_marker_is_not_memoised_between_calls(self):
        # Pasangan kontrol: kalau nilainya di-cache di mana pun, uji di atas
        # akan merah -- tetapi cache yang hanya hidup satu permintaan juga
        # akan lolos. Ini menegaskan pembacaan berturut-turut benar-benar
        # menyentuh basis data lagi.
        from odoo.addons.custom_hms_api.controllers.base import credential_marker
        first = credential_marker(self.user)
        self.env.cr.execute(
            "UPDATE res_users SET login = %s WHERE id = %s",
            ("zt-stk-berubah@simrs-demo.invalid", self.user.id),
        )
        self.assertNotEqual(credential_marker(self.user), first)
