# -*- coding: utf-8 -*-
"""The signature, checked against the one AWS publishes.

This is the test that justifies writing SigV4 out instead of importing boto3: a
presigner that reproduces a documented signature byte for byte is correct, and no
amount of trust in a library establishes that about the way it was called.

The vector is AWS's own worked example for pre-signed GET, fixed clock and all.
"""

from __future__ import annotations

from datetime import datetime, timezone

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.s3_presign import canonical_query_string, presign, signing_key

# AWS documentation, "Signature Calculations for a Presigned URL".
AWS_ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
AWS_HOST = "examplebucket.s3.amazonaws.com"
AWS_WHEN = datetime(2013, 5, 24, 0, 0, 0, tzinfo=timezone.utc)
AWS_EXPECTED_SIGNATURE = "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"


@tagged("post_install", "-at_install")
class TestS3Presign(TransactionCase):

    def _aws_example(self, **over):
        kwargs = dict(
            method="GET", host=AWS_HOST, key="test.txt",
            access_key=AWS_ACCESS_KEY, secret_key=AWS_SECRET_KEY,
            region="us-east-1", expires=86400, now=AWS_WHEN,
        )
        kwargs.update(over)
        return presign(**kwargs)

    def test_reproduces_the_signature_aws_publishes(self):
        url = self._aws_example()
        self.assertIn("X-Amz-Signature=", url)
        self.assertEqual(url.split("X-Amz-Signature=")[1], AWS_EXPECTED_SIGNATURE)

    def test_the_url_carries_everything_a_bucket_needs(self):
        url = self._aws_example()
        for part in ("X-Amz-Algorithm=AWS4-HMAC-SHA256", "X-Amz-Credential=",
                     "X-Amz-Date=20130524T000000Z", "X-Amz-Expires=86400",
                     "X-Amz-SignedHeaders=host"):
            self.assertIn(part, url)

    def test_a_different_secret_gives_a_different_signature(self):
        """Obvious, and the one property that makes the whole thing worth anything."""
        other = self._aws_example(secret_key=AWS_SECRET_KEY[:-1] + "Z")
        self.assertNotEqual(other.split("X-Amz-Signature=")[1], AWS_EXPECTED_SIGNATURE)

    def test_a_minute_later_is_a_different_signature(self):
        later = self._aws_example(now=AWS_WHEN.replace(minute=1))
        self.assertNotEqual(later.split("X-Amz-Signature=")[1], AWS_EXPECTED_SIGNATURE)

    def test_put_and_get_sign_differently(self):
        """The method is inside the canonical request, so a read URL cannot write."""
        get_sig = self._aws_example(method="GET").split("X-Amz-Signature=")[1]
        put_sig = self._aws_example(method="PUT").split("X-Amz-Signature=")[1]
        self.assertNotEqual(get_sig, put_sig)

    def test_signing_key_derivation_order_is_not_interchangeable(self):
        correct = signing_key(AWS_SECRET_KEY, "20130524", "us-east-1")
        swapped = signing_key(AWS_SECRET_KEY, "us-east-1", "20130524")
        self.assertNotEqual(correct, swapped)

    def test_tilde_is_not_escaped(self):
        """`~` is unreserved. Escaping it produces a signature nothing verifies."""
        url = self._aws_example(key="a~b.jpg")
        self.assertIn("/a~b.jpg?", url)
        self.assertNotIn("%7E", url)

    def test_slashes_in_a_key_stay_slashes(self):
        """Keys are flat strings, but they read as paths and must survive as written."""
        url = self._aws_example(key="spk/SPK-2026-0001/survey/front.jpg")
        self.assertIn("/spk/SPK-2026-0001/survey/front.jpg?", url)

    def test_query_string_is_sorted(self):
        """The sort is part of the signature, not a formatting preference."""
        self.assertEqual(canonical_query_string({"b": "2", "a": "1"}), "a=1&b=2")
