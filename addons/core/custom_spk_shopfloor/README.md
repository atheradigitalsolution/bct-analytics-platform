# Custom SPK Shopfloor

One round of the workshops, entered in under a minute, and queued when there is no
signal.

| BPD | Here |
|---|---|
| `booth_shopfloor` | `custom_spk_shopfloor` |
| — (new) | `custom.spk.shopfloor.round` |

## The risk this addresses

§12 of the requirements document ends with its sharpest observation: adoption on the
workshop floor, not technology, decides whether any of this works, and if input takes
more than sixty seconds on a phone the supervisor goes back to a notebook and the whole
costing chain collapses. With one supervisor covering every workshop, that risk sits
entirely on one person.

## Why a round is a model

The supervisor's unit of work is a walk of the workshops, not a person. Holding what was
entered together makes a half-finished round visible as one, instead of a scatter of
attendance records that may or may not be complete. `unmapped_count` is the number they
have to clear before the week closes — and it counts only **paid** shifts, because a
permanent worker's unmapped shift is not money already out the door.

## What is reused

`custom_hht_bridge` in `core` already carries the expensive parts: PWA shell with a
service worker, a FIFO queue for events raised offline, device enrolment with HMAC, GPS
capture. This module adds the endpoints those screens post to. Writing a second offline
queue would have been the largest avoidable piece of work in the project.

## The queue-and-presign trap

Photographs are links, and the upload URL is pre-signed with a short life. A URL
requested when a photo enters the offline queue has expired by the time signal returns
two hours later, and the upload fails silently. **Queue the photo; request the URL at
flush time.** The progress endpoint therefore accepts a link and never bytes.

## The round must not become a way around the gate

`action_approve_round` refuses while any paid shift is unmapped, and then approves each
attendance **through its own gate** rather than bulk-writing the state. A faster button
that skipped the control would defeat the control, which is the most likely way this
whole design gets quietly disabled.

Endpoints are thin for the same reason: every rule they touch lives in the models. A
mobile path that reimplements business rules is a second set of rules to drift from the
first.

## Status

**Never executed.** 10 tests, none run. The controllers have no tests at all — they need
HTTP-level cases with a signed device, which needs `custom_hht_bridge` enrolment, and
that is the first thing to write once the suite runs.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_shopfloor \
  --test-enable --test-tags /custom_spk_shopfloor --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Most likely first failure: the import path
`odoo.addons.custom_core.controllers.secure_endpoint`, and whether `secure_endpoint`
composes with `@http.route` in that order on this build.
