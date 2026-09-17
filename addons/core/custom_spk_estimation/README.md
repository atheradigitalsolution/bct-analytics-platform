# Custom SPK Estimation

Bill of quantity in five categories, waste estimated per line, and a quoted price
derived by margin.

| BPD | Here |
|---|---|
| `booth_estimation` | `custom_spk_estimation` |
| `booth.estimation` | `custom.spk.estimation` |
| `booth.estimation.line` | `custom.spk.estimation.line` |
| `booth.estimation.template` | `custom.spk.estimation.template` |

## Margin, not markup

`price = cost / (1 - margin)`. The markup form (`cost * (1 + margin)`) is the common
error and is always short: 100 marked up 30% is 130, whose margin is 23%. Pinned by
`test_margin_is_not_markup`, which asserts both the right answer and that the wrong
one is not produced.

## Waste is estimated so it can be measured

Each material line carries a waste percentage, and the total is kept as its own
field rather than buried in material cost. That makes the comparison possible later:
a job that used twice its allowance is usually a design drawn without reference to
standard sheet sizes, which is the cheapest saving available and invisible without
this number.

## Who sees what

Cost is visible to `group_spk_cost_viewer` — the estimator prices the work. Target
margin and quoted price are `group_spk_price_viewer` only. That split is why
estimation is its own model rather than fields on the quotation.

## Revisions supersede

`action_revise` copies to a new draft and marks the old one superseded. A
negotiation that overwrites its own history cannot answer what was quoted last week.

## Status

**Never executed.** 12 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_estimation \
  --test-enable --test-tags /custom_spk_estimation --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Most likely first failure: `uom.uom` model name and the `uom` module dependency
changed between recent Odoo versions; if the install fails on dependencies, that is
where to look.
