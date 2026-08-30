# Frozen contract 1 — PDP field classification (Security → DWH)

Status: **FROZEN at GATE 0.** Producer: `addons/custom_pdp_core`. Consumers: `custom_pdp_masking`,
the CDC loader, dbt. Changing a class or its masking means re-briefing every consumer.

Legal basis: UU 27/2022 (PDP). Art. 4(2) = *data pribadi umum*, Art. 4(3) = *data pribadi spesifik*.

## The taxonomy — exactly five classes, no others

| Class | Meaning | Examples on Odoo models |
|---|---|---|
| `public` | Non-personal, publishable | `product.template.name`, `res.company.name` |
| `internal` | Business data, not personal | `sale.order.amount_total`, `stock.move.product_qty` |
| `personal` | UU PDP Art. 4(2) general personal data | `res.partner.name`, `.email`, `.phone`, `.street`, `.city` |
| `sensitive` | UU PDP Art. 4(3) specific personal data | NIK/KTP, NPWP, health, biometric, religion, bank account |
| `secret` | Credentials and key material | `res.users.password`, API tokens, webhook secrets |

## Masking applied **during load**, before the row lands in the warehouse

Master prompt §3.2 and anti-pattern §7.5: no unmasked personal data ever reaches `raw_`. Masking is
applied by the CDC loader, not by dbt and never by the BI layer.

| Class | Transform at load | Rationale |
|---|---|---|
| `public` | none | — |
| `internal` | none | — |
| `personal` | `hmac_sha256(value, per_tenant_salt)` → 64-char hex, **deterministic** | Preserves joins and distinct-counts; destroys readability. Same partner hashes identically within a tenant, differently across tenants. |
| `sensitive` | `hmac_sha256(value, per_tenant_salt)`; free-text fields dropped to `NULL` | No reveal of any kind. A hash of a NIK is still not a NIK. |
| `secret` | **dropped at extraction** — the column is never selected | Structurally cannot land. Anti-pattern §7.9. |

Per-tenant salt lives in SOPS (`WAREHOUSE_MASK_SALT_<TENANT>`), never in a file, never in git,
`changeme` in `.env.example`. Rotating a salt invalidates historical joins — treat as a migration.

## Declaration surface

`custom_pdp_core` exposes model `pdp.field.classification` with columns
`(model_name, field_name, pdp_class, legal_basis, notes)` and a JSON-RPC-reachable read method.
The CDC loader reads this table at startup and refuses to start if a column it is about to extract
carries **no** classification. Unclassified is a hard failure, never a silent default to `public`.

## Acceptance

- A test asserts `res.partner.name` is unreadable in `raw_res_partner` and in every mart.
- A test asserts a `secret`-class column does not exist as a warehouse column at all.
- A test asserts the loader exits non-zero when a classification row is missing.

## Two different controls — do not confuse them (added at GATE 1)

This contract governs **warehouse masking at load**. `custom_pdp_masking` also implements an
**in-Odoo UI mask**. They are different controls with different reach, and overstating the second is
what makes it dangerous.

| Control | Where | What it stops | What it does NOT stop |
|---|---|---|---|
| Warehouse masking (this contract) | CDC loader, before the row lands in `raw` | Any reader of the warehouse, including the dashboard, exports and a stolen warehouse backup | Nothing downstream — there is no unmasking path, by construction |
| In-Odoo UI mask | `read()` override on the mixin | The list/form/kanban UI and RPC reads for users lacking `group_pdp_data_viewer` | A Settings admin, a `sudo()` server action, direct database access — and **any read funnel that does not route through `read()`** |

**`read()` is not the only funnel.** Confirmed in the pinned image at GATE 1:
`odoo/orm/models.py:806` inside `_export_rows` reads via `value = record[name]`, which is
`__getitem__` → ORM cache → `_read`, so it never calls the public `read()`. The CSV/XLSX export path
therefore bypassed the UI mask entirely until it was closed.

Two consequences that bind every future change:

1. **Adding a new read path is a security change.** Before shipping one, ask whether it routes
   through the overridden funnel. `export_data` did not.
2. **Odoo Settings access is effectively root.** The in-Odoo mask is a surface control, not a
   containment boundary. Tenant isolation and personal-data containment for analytics rest on the
   warehouse side — load-time masking plus RLS — not on the Odoo UI mask.
