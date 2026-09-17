# Custom SPK Change Order

Scope changes after approval: priced, agreed, and only then built.

| BPD | Here |
|---|---|
| `booth_change_order` | `custom_spk_change_order` |
| `booth.change.order` | `custom.spk.change.order` |
| P7 batas revisi design gratis | `custom.spk.design.revision` |

## Why not `custom_project_cr`

`custom_project_cr` in `ee_gap` models this exact shape — change request as its own
record, impact analysis, tiered approval, official numbering — and was the first
candidate. It depends on `custom_project_portfolio`, a client-coupled PMO module whose
stage set and sprint semantics have nothing to do with a booth. Reusing it meant either
dragging that in or decoupling somebody else's tenant module first, and that is a larger
and riskier change than the ~200 lines here.

Worth revisiting if `custom_project_cr` is ever decoupled: the approval-tier machinery
there is better than this.

## The gate

`action_apply` refuses without recorded client approval. That refusal is the entire
point: work done because the client asked verbally is work that gets argued about when
the invoice arrives, and that argument is the largest avoidable loss in this business —
larger than waste or idle time.

## The calendar is checked before the client is asked

`schedule_impact_days` is compared against the SPK's remaining days at **approval**, not
at apply. Refusing a change the client has already been told is fine is a much worse
conversation than refusing it while it is still a question. And because the event date
does not move, a change needing more days than remain is not a price question at all.

## Cause is recorded even when it is ours

`origin` drives billability: a client's change of mind is billable, our own mistake is
not. Both are recorded, because a pattern of internal errors only gets fixed once it is
countable. `is_billable` stays editable — sometimes a technical adjustment is billable
and sometimes goodwill is the right answer.

## Two free revisions

The third revision caused by the client changing their mind is chargeable. Without that
line revisions are unbounded, and they consume margin and the schedule simultaneously.
Internal errors and technical adjustments never become chargeable, however many there
are.

## Status

**Never executed.** 17 tests, none run.

```
docker exec odoo19-bct-odoo odoo -d <db> -i custom_spk_change_order \
  --test-enable --test-tags /custom_spk_change_order --stop-after-init --workers=0 \
  --http-port=8999 --gevent-port=8998 --without-demo=True
```
