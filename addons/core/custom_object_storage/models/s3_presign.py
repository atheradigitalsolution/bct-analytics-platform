# -*- coding: utf-8 -*-
"""AWS Signature Version 4 pre-signing, with no dependency on anything.

Why this is written out rather than delegated to boto3
------------------------------------------------------

boto3 would be the obvious answer and was the first recommendation. Two things changed
it. Adding the dependency means rebuilding and restarting the Odoo image on a database
that is already serving a client demo, to gain a library of which exactly one function
would be used. And pre-signing is pure string construction plus HMAC -- it makes no
network call at all -- which means it can be verified offline against the signature AWS
publishes in its own documentation.

That test is worth more than the library. A presigner that reproduces a known-good
signature byte for byte is correct; one that merely imports a trusted package is only
as correct as the way it was called.

Deliberately free of Odoo imports so it can be reasoned about, and tested, on its own.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
# A pre-signed URL is handed to a browser that will upload or download bytes the server
# never sees, so the payload cannot be hashed in advance.
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def signing_key(secret: str, datestamp: str, region: str, service: str = SERVICE) -> bytes:
    """The four-step derivation. Order matters and is not interchangeable."""
    k_date = _sign(("AWS4" + secret).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _uri_encode(value: str, encode_slash: bool = True) -> str:
    """S3's encoding rules, which are not urllib's defaults.

    The unreserved set is fixed by the specification; `~` in particular must NOT be
    escaped, and a canonical request that escapes it produces a signature that verifies
    against nothing.
    """
    safe = "" if encode_slash else "/"
    return quote(value, safe=safe + "-_.~")


def canonical_query_string(params: dict) -> str:
    """Sorted by key, each side encoded. The sort is part of the signature."""
    items = sorted((k, v) for k, v in params.items())
    return "&".join(f"{_uri_encode(k)}={_uri_encode(str(v))}" for k, v in items)


def presign(
    *,
    method: str,
    host: str,
    key: str,
    access_key: str,
    secret_key: str,
    region: str,
    expires: int = 900,
    now: datetime | None = None,
    scheme: str = "https",
    extra_params: dict | None = None,
) -> str:
    """Return a URL that carries its own authorisation and expires on its own.

    ``now`` is injectable because a signature is a function of time, and a test that
    cannot fix the clock cannot check the signature against a published value.
    """
    now = now or datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    credential_scope = f"{datestamp}/{region}/{SERVICE}/aws4_request"

    canonical_uri = "/" + _uri_encode(key.lstrip("/"), encode_slash=False)

    params = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    if extra_params:
        params.update(extra_params)
    canonical_qs = canonical_query_string(params)

    canonical_request = "\n".join([
        method.upper(),
        canonical_uri,
        canonical_qs,
        f"host:{host}\n",
        "host",
        UNSIGNED_PAYLOAD,
    ])
    string_to_sign = "\n".join([
        ALGORITHM,
        amz_date,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signature = hmac.new(
        signing_key(secret_key, datestamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{scheme}://{host}{canonical_uri}?{canonical_qs}&X-Amz-Signature={signature}"


def expiry_of(expires: int, now: datetime | None = None) -> datetime:
    """When a URL signed now stops working. Stored so a queue can check before using."""
    return (now or datetime.now(timezone.utc)) + timedelta(seconds=expires)
