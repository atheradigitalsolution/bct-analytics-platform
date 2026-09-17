# Custom SPK Costing

Estimate versus actual per job, per category, with the margin slip flagged.

| BPD | Here |
|---|---|
| `booth_costing_report` | `custom_spk_costing` |
| §8.2 laporan biaya detail | `custom.spk.cost.summary` |
| §8.1 margin board | the list view, red where margin slipped |

## Why this is not fields on `custom.spk`

`custom.spk` is required to carry no monetary field, and a test asserts the absence
so nobody adds one later. That rule is what makes the SPK safe to show an Account
Executive — and it also rules out putting the cost summary there.

The constraint produced the better architecture. The AE-facing record and the costing
record have different readers, different refresh behaviour, and different lifetimes.
Joining them would have made the price fence depend on remembering to hide fields on
a model that also holds job progress.

## Classification is stamped, not inferred

The first draft of this module worked out what a line was by checking which fields
happened to be populated. That is guesswork, and guesswork in a cost report is worse
than a gap because it produces a number that looks like an answer.

So `account.analytic.line.x_spk_cost_category` is written at creation. Two rules:

- a line carrying a product is material — stock valuation is how material cost reaches
  a job and those lines always have one;
- code in this suite states the category explicitly, and a stated decision is never
  overwritten by the heuristic.

`custom_spk_workforce` stamps its allocation as labour and `custom_spk_material`
stamps its remnant credit as material, both guarded so neither requires this module.
Anything unclassified lands in `other`, which the report **shows**. A figure that
vanishes quietly is worse than one that needs a name.

## Sign convention

Analytic holds cost negative. The report flips it, so a cost reads positive and a
credit — a returned remnant — reduces the bucket it reverses. That last part matters:
a credit landing in the wrong bucket would show the material issue without the
return, and material variance is the number people act on.

## Refresh is explicit

Nothing recomputes on analytic writes. A stored compute depending on analytic lines
would rewrite this table on every material issue and every shift log — thousands of
writes a month for a report nobody is reading at the time. `action_refresh()` per
record, `refresh_all()` for the board.

## The waste line

Material variance says a job cost more than planned. `est_waste` says why. A job that
used its material but twice its waste allowance was not run badly in the workshop; it
was drawn without reference to standard sheet sizes, and the fix is upstream of
everyone who gets blamed for it.

## Status

**Never executed.** 15 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_costing \
  --test-enable --test-tags /custom_spk_costing --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Most likely first failure: `account.analytic.line` requires a company and, in some
configurations, a plan-derived account field; the fixtures create lines with only
`account_id` and `amount`.
