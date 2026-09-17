# Custom SPK Survey

Site survey before the estimate.

| BPD | Here |
|---|---|
| `booth_survey` (P2, usulan baru) | `custom_spk_survey` |
| `booth.site.survey` | `custom.spk.survey` |

## What this is for

Installation overrun rarely comes from the build. It comes from the venue: a ceiling
lower than the drawing, a dock that cannot take the truck, a lift that will not take a
3-metre panel, permitted hours that turn a day job into two nights, and venue charges
for power, permits and security nobody asked about. None of that is visible from a
brief.

## A checklist, not a questionnaire

Every field exists because getting it wrong costs money on the day. There is deliberately
no general "notes" field standing in for the questions that matter — `risk_note` is
explicitly only for what the checklist does not already ask, because notes are where
answers go to be forgotten.

## Two numbers are mandatory

`action_done` refuses without ceiling height and access width. Those are the two that
contradict the drawing: a booth designed at 2.5 m does not fit under a 2.4 m soffit, and
panels are cut to the narrowest access. Everything else can be estimated; these cannot.

## `max_panel_length_m` is the field to hand the designer

It decides how the booth is broken up, and it is the cheapest intervention available —
a design drawn to the access that exists never needs recutting on site.

## Venue cost feeds the estimate

The four venue charges roll into `venue_cost_total`, which belongs in the estimate's
venue category. Without it those costs arrive as an invoice after the event, against a
job whose margin was already reported.

## Status

**Never executed.** 8 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_survey \
  --test-enable --test-tags /custom_spk_survey --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```
