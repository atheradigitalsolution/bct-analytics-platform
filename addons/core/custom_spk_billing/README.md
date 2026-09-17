# Custom SPK Billing

Billing plans per job, the reminder for work finished but never invoiced, and dunning
that escalates.

| BPD | Here |
|---|---|
| `booth_followup` | `custom_spk_billing` |
| §7.1 tiga skema invoice | `custom.spk.billing.plan.mode` |
| §7.1 termin DP/40/retensi | `custom.spk.billing.milestone` |
| §7.2 A reminder internal | `_cron_warn_uninvoiced` |
| §7.2 B reminder eksternal | `custom.spk.followup.level` + `_cron_spk_followup` |
| §7.2 credit control | `res.partner.spk_credit_warning()` |

## The reminder that recovers the most money

Two reminders are needed and only one usually gets built.

The one everybody builds chases the client. The one that leaks money is internal: the
booth is standing, the crew has moved to the next event, and nobody raised the invoice.
**Unbilled work does not appear in a receivables report** — there is no receivable, the
amount is simply absent. So a daily cron looks for signed handovers with no invoice and
puts it in front of Finance. Three days, long enough to be an omission rather than
paperwork in flight.

## Milestones must add up

A plan whose milestones do not total 100% either leaves money uninvoiced or bills it
twice. Refused, in both directions, with tests for each.

## The down-payment gate returns, not raises

`can_release_to_workshop()` gives back `(bool, reason)`. Buying a client's material
before any money has arrived is financing their event out of working capital — so the
default is to hold — but whether to waive it is the owner's call, and the API lets the
caller decide rather than deciding for them.

## Dunning fires once per threshold

The level is stamped on the invoice, so a client is not emailed twice for crossing the
same line; a client emailed twice stops reading the emails. The first level fires
**before** the due date, which costs nothing and removes a whole class of "we never
received it". The last escalates to the owner, because dunning that emails politely
forever is not dunning.

## Credit control warns

Repeat orders arrive fast in event work and it is easy to take a second job from a
client who has not paid for the first. `spk_credit_warning()` returns text rather than
raising: the exposure is worth naming, and the decision belongs to the owner, who may
well have a reason.

## Status

**Never executed.** 24 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_billing \
  --test-enable --test-tags /custom_spk_billing --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```

Most likely first failures: posting an invoice needs a configured chart of accounts and
a journal, so `_invoice(post=True)` will fail on a database without accounting set up;
and `invoice_origin` is used to match invoices to a job by name, which is a weak link
that should become a real `spk_id` field on `account.move` once the invoicing wizard
exists.
