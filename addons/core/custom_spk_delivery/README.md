# Custom SPK Delivery

One job, several venues, each with its own loading window, crew and handover.

| BPD | Here |
|---|---|
| `booth_delivery` | `custom_spk_delivery` |
| `booth.delivery.schedule` | `custom.spk.delivery` |
| BAST (§6.1) | linked `custom.bast.document`, not reimplemented |
| usulan #14 bongkar | `dismantle_at` + a daily reminder |

## Why the schedule is not on sale order lines

The BPD puts `delivery_location_id` on `sale.order.line` because Odoo's order carries
one shipping address. That works, but it puts the delivery schedule inside the model
the Account Executive is deliberately locked out of. Here each shipment is its own
record against the SPK, so the AE can follow the job without being given sales access.

Sub-numbers are derived from the SPK (`SPK/2026/0001/D1`) rather than drawn from a
global sequence, because the client quotes "D2 of SPK 0001", not the hundredth
delivery of the year.

## The loading window is required

A venue that permits goods only between 22:00 and 06:00 is a constraint, not a
preference, and a crew arriving outside it waits outside a locked dock. A shipment
with a venue and no `loading_in` is refused.

## Handover reuses BAST

`custom.bast.document` in `core` already does dual signature, GPS, timestamp and an
audit trail, and is linked through its `reference` field. Raising the document is not
signing it: `bast_signed` becomes true only when the client side has actually signed,
and `action_confirm_handover` refuses without it. That gate exists because billing
against an unsigned handover is what a client's finance department declines.

## Cost lands once, on installation

The trip's cost posts when the shipment is marked installed, not when it is scheduled:
a trip that never happened should cost nothing, and posting twice is worse than posting
late. `cost_posted` and a refusal to install twice hold that.

## Photos are links, signatures are not

`photo_url` is a link, matching the decision to hold photographs outside the
filestore. The signature is deliberately **not** a link — it is an attachment on the
BAST, because it is the part that has to survive a dispute months later, and a link
that rots takes the evidence with it.

## Dismantle

No booth here is rented out, so nothing comes back to be re-let. The dismantle still
needs a crew, a truck and a venue slot, and is the line most often missing from the
estimate — so it is scheduled and a daily cron flags installed shipments whose event
has ended without one.

## Status

**Green.** Run against `expomedia` on 2026-09-18 as part of a full-suite run: 177 tests across the ten modules, 0 failed, 0 errors.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_delivery \
  --test-enable --test-tags /custom_spk_delivery --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```
