# -*- coding: utf-8 -*-
{
    "name": "Custom Object Storage",
    "summary": "S3-compatible object storage (Cloudflare R2) with short-lived pre-signed "
    "URLs, so bytes never pass through Odoo",
    "description": """
Custom Object Storage
=====================

Photographs, design files and scans are held outside the Odoo filestore and referenced
by key. This module issues the URLs that make that work.

Why the bytes do not pass through Odoo
--------------------------------------

The browser or device uploads straight to the bucket using a pre-signed URL, and reads
back the same way. Odoo issues the URL and stores the key. Nothing large ever crosses
the application server, so a site survey with forty photographs costs the VPS no
bandwidth, no memory and no disk.

Why the URL expires
-------------------

A permanent public link is an access-control hole outside every record rule in the
system: a booth photograph at a client's venue, with GPS and a timestamp, is the
client's data. A pre-signed URL carries its own authorisation and stops working on its
own, so the fence around the record is the fence around the file.

The trap this is shaped around
------------------------------

Devices queue work while offline. A URL signed when a photograph enters the queue has
expired by the time signal returns two hours later, and the upload fails silently.
So ``presign_put`` is cheap and expected to be called at flush time, and the expiry it
returns is explicit rather than implied -- a queue can check it before spending an
upload on a dead URL.

Signing
-------

SigV4 is implemented in ``models/s3_presign.py`` rather than delegated to boto3. Pre-
signing makes no network call, so it can be verified offline against the signature AWS
publishes in its own documentation -- which ``tests/test_s3_presign.py`` does, byte for
byte. That is a stronger guarantee than importing a trusted library, and it avoids
rebuilding the Odoo image to gain one function.
""",
    "author": "Custom Platform",
    "website": "https://example.com/custom-platform",
    "category": "Custom Platform/Technical",
    "version": "19.0.0.1.0",
    "license": "LGPL-3",
    "depends": ["custom_core", "custom_adapter_framework"],
    "capability_tags": ["object-storage", "s3", "cloudflare-r2", "presigned-url"],
    "data": [
        "security/ir.model.access.csv",
        "views/object_storage_views.xml",
    ],
    "installable": True,
    "auto_install": False,
    "application": False,
}
