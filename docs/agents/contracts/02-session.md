# Frozen contract 2 — session (Security → Backend → Frontend)

Status: **FROZEN at GATE 0.** Producer: `login-gateway`. Consumers: `insight-portal` (server side
only), `semantic-api`.

## Shape

`login-gateway` authenticates the user against Odoo over JSON-RPC (`common.authenticate`), reads the
user's company and Operating Unit assignments, and issues a **RS256** JWT. The gateway holds the
private key; every verifier fetches the public key from the gateway's JWKS endpoint and therefore
never holds signing material.

```json
{
  "iss": "https://login-gateway.local/",
  "aud": "insight-portal",
  "sub": "odoo:<database>:<uid>",
  "tenant_id": "acme",
  "odoo_uid": 7,
  "roles": ["analytics.viewer"],
  "allowed_ou": [1, 4, 9],
  "company_ids": [1],
  "iat": 1756600000,
  "exp": 1756603600
}
```

- `tenant_id` — the Odoo database this session belongs to. **Never** taken from a request header,
  query string, cookie or request body. Only from the verified token.
- `roles` — one of `analytics.viewer`, `analytics.analyst`, `analytics.admin`.
- `allowed_ou` — Operating Unit ids the user may see. Empty array means *all OUs in the tenant*.
- `exp` — 3600 s. Refresh via an httpOnly, `Secure`, `SameSite=Strict` refresh cookie.

## Verification, server-side only

1. Signature verified against JWKS, algorithm **pinned to RS256** — `alg: none` and HS256 confusion
   are rejected outright.
2. `iss` and `aud` checked exactly. `exp`/`nbf` checked with 30 s leeway.
3. `tenant_id` is injected into every warehouse query as a bound parameter **and** set as the
   Postgres session variable that RLS reads. Application-level filtering alone is not sufficient
   (master prompt §3.3).

The browser never receives a token that grants direct database or semantic-api access, never
receives a connection string, and never receives more rows than it renders (§4).

## Scope violation response

A session for tenant A requesting tenant B returns **HTTP 403** with exactly:

```json
{"error": "tenant_scope_violation", "detail": "Session is not scoped to the requested tenant."}
```

No leak of whether tenant B exists. The event is written to the audit log with the subject, the
requested tenant and the timestamp. Proven by test (§6: "Cross-tenant access returns 403").
