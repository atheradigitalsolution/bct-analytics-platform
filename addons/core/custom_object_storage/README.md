# Custom Object Storage

S3-compatible object storage — Cloudflare R2 — with short-lived pre-signed URLs.

## What it does

Odoo issues a URL. The browser or device uploads straight to the bucket and reads back
the same way. **The bytes never cross the application server**, so a site survey with
forty photographs costs this VPS no bandwidth, no memory and no disk.

The record keeps an object **key**, never a URL. `storage_url` is computed, non-stored,
and signed on read. There is no field to paste an external link into, and that is
deliberate: a pasted link is exactly what rots, and it rots at the moment a dispute
needs it.

## Why SigV4 is written out rather than imported

boto3 was the first recommendation and this replaced it, for two reasons.

Adding the dependency means rebuilding and restarting the Odoo image on a database
already serving a client demo, to gain a library of which one function would be used.
And pre-signing makes **no network call at all** — it is string construction plus HMAC —
so it can be verified offline against the signature AWS publishes in its own
documentation.

`test_reproduces_the_signature_aws_publishes` does exactly that, byte for byte, against
AWS's worked example with a fixed clock. That is a stronger guarantee than importing a
trusted package: a presigner that reproduces a known-good signature is correct, whereas
an import is only as correct as the way it was called.

## Configuration

One `custom.adapter.config` row with `adapter_type = s3_compatible`:

| Field | Value for R2 |
|---|---|
| `base_url` | `https://<account-id>.r2.cloudflarestorage.com` |
| `x_s3_bucket` | your bucket |
| `x_s3_region` | `auto` — R2 signs with that literal |
| `x_s3_access_key_id` | R2 token access key id |
| `credential_ref` | the `ir.config_parameter` key holding the **secret** |
| `x_s3_default_expiry_s` | 900 |

The access key id is **not** a secret — it appears in every signed URL in plain sight —
which is why it sits on the config while only the secret half goes through
`ir.config_parameter`. R2 addresses the bucket in the path; the adapter derives that
from the endpoint rather than assuming, because getting it wrong signs a URL nobody
serves.

## The trap this is shaped around

Devices queue work offline. **A URL signed when a photograph enters the queue has expired
by the time signal returns two hours later, and the upload fails silently.**

So `action_request_upload` is cheap and meant to be called at flush time, the shopfloor
endpoint `/api/spk/shopfloor/presign` exists for exactly that moment, and `expires_at`
is returned explicitly so a queue can ask whether a URL is still worth spending an
upload on.

## What is NOT stored here

The BAST signature. It stays an attachment on the handover document, because it is the
part that has to survive a dispute months after the event, and a reference that can rot
takes the evidence with it. Photographs are corroboration; the signature is the
agreement.

## Still to do outside Odoo

1. Create the R2 bucket and an API token scoped to it.
2. `ir.config_parameter`: store the secret under the key named in `credential_ref`.
3. **Put the bucket in the backup story.** `athera-backup` takes a database dump and the
   filestore; evidence held in a bucket is outside both.
4. Consider a lifecycle rule. `action_clear_storage` forgets a reference and deliberately
   does not delete the object — a record being tidied is not a reason to destroy
   evidence — so deletion should be a deliberate policy rather than a side effect.

## Status: built, verified, and currently dormant

**Green.** 12 tests covering the signer, against `expomedia` on 2026-09-18.

**Nothing uses it right now.** Cloudflare R2 requires a card on file, and the client chose
to keep photographs in the Odoo filestore instead and carry the disk cost. So the SPK
documents hold `ir.attachment` records, and this module sits installed and idle.

It is kept rather than deleted because it works and is proved: the day a bucket exists --
R2, Garage, SeaweedFS, anything S3-compatible -- a document adopts
`custom.object.storage.mixin`, one `custom.adapter.config` row is filled in, and nothing
else has to be written.

One honest gap while dormant: the mixin's own behaviour has no tests, because no model
inherits it and a test-only model would be clutter in a production tree. The signer is
what needed proving and it has it. Whoever adopts the mixin should bring those tests with
them.
