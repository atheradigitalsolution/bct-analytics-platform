# Custom SPK Material

Material requests with supervisor approval and over-estimate escalation, plus the
offcut policy that decides who pays for the part of a sheet nobody used.

| BPD | Here |
|---|---|
| `booth_material_request` | `custom_spk_material` |
| `booth_offcut` | `custom_spk_material` (same flow: issue → return → classify) |
| `booth.material.request` | `custom.spk.material.request` |
| `booth.material.return` | `custom.spk.material.return` |

Offcut is not a separate module. It is the return half of one flow — material goes
out, some comes back, and something has to decide what the remnant is worth. Two
modules would have put the threshold in one and the issue history in the other.

## The question this answers

Charging a whole sheet to whoever opened it makes the year's profit correct and every
job's margin wrong: the first job pays for material the next three use. So material
carries a class, and the class decides the rule.

- **A — stock item**: charged as used, remnant comes back and is classified.
- **B — consumable**: standard usage, because nobody weighs the thinner. The gap
  between standard and actual is an overhead variance, not a job's problem.
- **C — fixed unit**: per unit, leftovers return whole.
- **D — made to order**: entirely to the job. A banner printed at one size has no
  second life, and crediting it would move real cost off the job that caused it.

## Two details that decide whether this works in practice

**The discount has to be real.** `x_spk_offcut_valuation_pct` at 100% is refused,
because a remnant valued at full price turns the offcut rack into a mechanism for
moving cost off jobs rather than a stock of usable material.
`test_valuing_a_remnant_at_full_price_is_refused` holds that.

**Credit plus waste always equals what came back.** Classification splits value; it
does not create or destroy it. Asserted across four threshold positions, because an
arithmetic slip here would quietly change total cost rather than its distribution.

## Escalation, not blocking

A request that pushes a job's cumulative take past the estimate does not fail — it
requires a reason and rises to the project manager. Production does not stop because
a panel was cut wrong; but the third extra sheet has to be someone's decision on the
record. The comparison is cumulative, not per request:
`test_cumulative_take_is_what_counts_not_this_request_alone` exists because overrun
arrives one sheet at a time and each request on its own looks reasonable.

## Status

**Never executed.** 23 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_material \
  --test-enable --test-tags /custom_spk_material --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Most likely first failures: `stock.picking_type_internal` may not exist without
multi-step routes enabled, and `product.product` `type` values changed in recent
versions (`consu` vs `product`).
