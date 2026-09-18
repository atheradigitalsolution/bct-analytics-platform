# Custom SPK

Surat Perintah Kerja as the golden thread, plus the access model around it.

## Why one module and not two

The business process document lists `booth_base` and `booth_security` as separate
P0 items. They are one module here, for two reasons: a record rule has nothing to
attach to before the model exists, and the document itself says both are
dependencies of everything else in the pack — which means they always ship
together. Splitting them would create a seam that nothing ever crosses.

## Name mapping

Every one of the 162 modules in this tree is prefixed `custom_`; there is no
`booth_*` precedent, so the BPD's names are mapped rather than adopted:

| BPD | Here |
|---|---|
| `booth_base` | `custom_spk` (this module) |
| `booth_security` | `custom_spk` (this module) |
| `booth.spk` | `custom.spk` |
| `booth.shift` | `custom.spk.shift` |
| `group_booth_ae` | `group_spk_ae` |
| `group_booth_supervisor` | `group_spk_supervisor` |
| `group_booth_pm` | `group_spk_pm` |
| `group_booth_cost_viewer` | `group_spk_cost_viewer` |
| `group_booth_price_viewer` | `group_spk_price_viewer` |

## Where this diverges from the document, and why

**No per-workshop record rule.** §10 scopes the supervisor to "their" workshop,
assuming five of them. This deployment has one supervisor covering all workshops,
so the rule would fence a set of one — and an unused fence is one somebody
disables later. The supervisor sees every SPK.

**Two leaks in §10 closed.** The matrix grants the AE read on Manufacturing and
Work Order, which reaches `product.*.standard_price` — a field Odoo ships with no
restricting group. From a bill of quantity, cost is most of the way to price. And
`account.analytic.line`, where all job cost lands, is not named in the matrix at
all. Both are covered by `tests/test_price_fence.py`.

**`list_price` is deliberately not fenced.** In engineer-to-order work it is not
the quoted price; the quotation carries that and the AE cannot read `sale.order`.
Gating it would break website and portal flows to close a door already shut.

## The one line most likely to break

`models/product_template.py` re-declares `standard_price` purely to attach
`groups`. This relies on Odoo merging field attributes on inheritance, so that
`compute`, `inverse` and `company_dependent` survive from the base definition.
It is the highest-risk line here. If the suite fails on product cost, look there
first.

## Completion criterion

The document's gate for this phase is proof that the AE cannot reach a price by
any route, including export and API. `tests/test_price_fence.py` asserts at the
ORM, which is what export and JSON-RPC go through. The strongest of those tests is
`test_spk_carries_no_monetary_field`: it fails if anyone adds money to the
AE-facing model later, which a view-level review would pass.

## Status

**Green.** Run against `expomedia` on 2026-09-18 as part of a full-suite run: 177 tests across the ten modules, 0 failed, 0 errors.
session. 22 tests, all unrun. To verify:

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk \
  --test-enable --test-tags /custom_spk --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

`--test-enable` overrides `--no-http` (`odoo/service/server.py:653`), so the
alternate ports are not optional when the container already serves Odoo.
