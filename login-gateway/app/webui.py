"""The gateway's own login page.

WHY THE GATEWAY GREW A PAGE. Until brief 08 the gateway was pure API and every login went through
a portal, which captured the refresh cookie and re-issued it as its own, scoped to the portal's
host. That works for the portal and makes the SSO door unreachable: `/auth/sso/odoo` reads the
gateway's refresh cookie, and a browser that has only ever spoken to `insight.` has no cookie for
`auth.` to send. Measured before this file existed -- the door answered 401 to every human.

So the browser has to talk to `auth.` at least once. This is the smallest surface that lets it:
one form, no JavaScript, no static assets, nothing to cache-bust.

THE PAGE IS NOT A TRUST BOUNDARY. Everything it collects is checked by the same code path the JSON
API uses -- same allow-list, same rate limiter, same identical answer for a bad database and a bad
password. Rendering is all this module does.
"""

from __future__ import annotations

import html

#: Deliberately one file with no external references: `default-src 'self'` is satisfied without a
#: single extra request, and there is no asset that can drift out of step with the markup.
_PAGE = """<!doctype html>
<html lang="id"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Masuk — ATHERA</title>
<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1.5rem;
 font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
 background:#f6f7f9;color:#16181d}
main{width:100%%;max-width:23rem;background:#fff;border:1px solid #e3e6ea;border-radius:12px;
 padding:1.75rem}
h1{margin:0 0 .25rem;font-size:1.15rem;letter-spacing:.01em}
p.sub{margin:0 0 1.25rem;color:#5b616e;font-size:.85rem}
label{display:block;margin:.85rem 0 .3rem;font-size:.8rem;font-weight:600;color:#3b414c}
input{width:100%%;padding:.6rem .7rem;font:inherit;border:1px solid #ccd2da;border-radius:8px;
 background:#fff;color:inherit}
input:focus{outline:2px solid #2f6feb;outline-offset:1px;border-color:#2f6feb}
button{width:100%%;margin-top:1.25rem;padding:.65rem;font:inherit;font-weight:600;cursor:pointer;
 border:0;border-radius:8px;background:#16181d;color:#fff}
.err{margin:0 0 1rem;padding:.6rem .7rem;border-radius:8px;background:#fdecec;color:#8c1c1c;
 border:1px solid #f5c2c2;font-size:.85rem}
.hint{margin:.35rem 0 0;font-size:.75rem;color:#7a808c}
@media (prefers-color-scheme:dark){
 body{background:#0f1115;color:#e8eaee}
 main{background:#171a20;border-color:#272b33}
 input{background:#0f1115;border-color:#333944;color:inherit}
 button{background:#e8eaee;color:#0f1115}
 p.sub,.hint{color:#9aa1ad} label{color:#c3c9d4}
 .err{background:#2a1618;color:#f3b9b9;border-color:#4a2326}
}
</style>
</head><body><main>
<h1>Masuk ke ATHERA</h1>
<p class="sub">Satu akun untuk Insight dan Odoo.</p>
%(error)s
<form method="post" action="/auth/login/form">
<input type="hidden" name="next" value="%(next)s">
<input type="hidden" name="csrf" value="%(csrf)s">
<label for="db">Kode klien</label>
<input id="db" name="db" value="%(db)s" required autocapitalize="none" autocomplete="organization"
 spellcheck="false">
<p class="hint">Kode organisasi Anda di ATHERA.</p>
<label for="login">Email</label>
<input id="login" name="login" type="email" required autocomplete="username" autofocus>
<label for="password">Kata sandi</label>
<input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">Masuk</button>
</form>
<p class="hint" style="margin-top:1rem"><a href="/auth/reset">Lupa kata sandi?</a></p>
</main></body></html>
"""

#: One message for every refusal. Which of database, account or password was wrong is exactly the
#: thing an unauthenticated visitor does not get to learn -- the JSON API has answered this way
#: since it was written, and a page that were chattier would undo that.
INVALID = "Kode klien, email, atau kata sandi tidak cocok."
RATE_LIMITED = "Terlalu banyak percobaan. Coba lagi beberapa menit lagi."
UPSTREAM = "Layanan masuk sedang tidak tersedia. Coba lagi sebentar lagi."
EXPIRED = "Formulir sudah kedaluwarsa. Coba masuk sekali lagi."


def login_page(next_path: str, db: str = "", csrf: str = "", error: str = "") -> str:
    """Every interpolated value is escaped. `next` and `db` arrive from the query string, so the
    page renders attacker-supplied text by design and the escaping is the control, not a habit."""
    return _PAGE % {
        "next": html.escape(next_path, quote=True),
        "db": html.escape(db, quote=True),
        "csrf": html.escape(csrf, quote=True),
        "error": ('<p class="err">%s</p>' % html.escape(error)) if error else "",
    }


# ---------------------------------------------------------------------------
# Reset password
#
# THREE PAGES, ONE SHELL. They share `_PAGE`'s stylesheet by being built from the same string
# with a different body, rather than by importing a template engine into a service whose whole
# UI is four forms. `default-src 'self'` stays satisfiable because nothing here loads anything.
#
# THE MIDDLE PAGE IS THE SECURITY CONTROL. `reset_sent_page` is returned for an address that
# exists, an address that does not, a tenant code that does not, and a mail relay that just
# refused the message. If any of those rendered differently, the form would answer the question
# "does this person have an account with you" for anybody who asks.
# ---------------------------------------------------------------------------

_SHELL = _PAGE.split("<h1>")[0] + "%(body)s</main></body></html>\n"


def _shell(title: str, body: str) -> str:
    return _SHELL.replace("<title>Masuk — ATHERA</title>", "<title>%s — ATHERA</title>" % title) % {
        "body": body,
    }


RESET_INVALID = "Kode klien atau email tidak lengkap."
RESET_EXPIRED_FORM = "Formulir sudah kedaluwarsa. Mulai lagi dari awal."
RESET_RATE_LIMITED = "Terlalu banyak permintaan. Coba lagi beberapa menit lagi."
RESET_DISABLED = "Atur ulang kata sandi belum tersedia. Hubungi admin ATHERA Anda."
RESET_LINK_BAD = "Tautan ini sudah dipakai atau kedaluwarsa. Mintalah tautan baru."
RESET_TOO_SHORT = "Kata sandi baru minimal 8 karakter."
RESET_MISMATCH = "Kedua kata sandi tidak sama."


def reset_request_page(csrf: str = "", db: str = "", error: str = "") -> str:
    """Where a person asks for a link. Same two identifiers the login form already asks for.

    It asks for the client code as well as the email because the gateway has never resolved one
    to the other: `_handle_login_form` takes `db` straight from the form. Adding a lookup here
    would mean the gateway learning which tenants an address belongs to — a new capability, and
    an enumeration oracle — to save a field the person already fills in to log in.
    """
    body = (
        '<h1>Atur ulang kata sandi</h1>'
        '<p class="sub">Kami kirim tautan ke email Anda.</p>'
        + (('<p class="err">%s</p>' % html.escape(error)) if error else "")
        + '<form method="post" action="/auth/reset/form">'
        '<input type="hidden" name="csrf" value="%s">'
        '<label for="db">Kode klien</label>'
        '<input id="db" name="db" value="%s" required autocapitalize="none"'
        ' autocomplete="organization" spellcheck="false">'
        '<label for="login">Email</label>'
        '<input id="login" name="login" type="email" required autocomplete="username" autofocus>'
        '<button type="submit">Kirim tautan</button>'
        '</form>'
        '<p class="hint" style="margin-top:1rem"><a href="/auth/login">Kembali ke halaman masuk</a></p>'
        % (html.escape(csrf, quote=True), html.escape(db, quote=True))
    )
    return _shell("Atur ulang kata sandi", body)


def reset_sent_page() -> str:
    """The one answer. See the note at the top of this section for why it is the only one."""
    body = (
        '<h1>Periksa email Anda</h1>'
        '<p class="sub">Kalau kode klien dan email itu cocok dengan sebuah akun, tautan untuk '
        'mengatur ulang kata sandi sudah dikirim ke sana.</p>'
        '<p class="hint">Tautannya berlaku singkat dan hanya bisa dipakai sekali. Tidak menerima '
        'apa pun setelah beberapa menit? Periksa folder spam, lalu coba lagi.</p>'
        '<p class="hint" style="margin-top:1rem"><a href="/auth/login">Kembali ke halaman masuk</a></p>'
    )
    return _shell("Periksa email Anda", body)


def reset_new_page(db: str, token: str, csrf: str = "", error: str = "") -> str:
    """Where the new password is chosen. The token rides in a hidden field, not the query string.

    It arrives in the URL — an emailed link has nowhere else to put it — but this form POSTs it in
    the body so that the browser's next request, and anything it sends a `Referer` to, does not
    carry a live reset token.
    """
    body = (
        '<h1>Kata sandi baru</h1>'
        '<p class="sub">Pilih kata sandi baru untuk akun Anda.</p>'
        + (('<p class="err">%s</p>' % html.escape(error)) if error else "")
        + '<form method="post" action="/auth/reset/new">'
        '<input type="hidden" name="csrf" value="%s">'
        '<input type="hidden" name="db" value="%s">'
        '<input type="hidden" name="token" value="%s">'
        '<label for="password">Kata sandi baru</label>'
        '<input id="password" name="password" type="password" required minlength="8"'
        ' autocomplete="new-password" autofocus>'
        '<label for="confirm">Ulangi kata sandi</label>'
        '<input id="confirm" name="confirm" type="password" required minlength="8"'
        ' autocomplete="new-password">'
        '<button type="submit">Simpan kata sandi</button>'
        '</form>'
        % (
            html.escape(csrf, quote=True),
            html.escape(db, quote=True),
            html.escape(token, quote=True),
        )
    )
    return _shell("Kata sandi baru", body)
