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
