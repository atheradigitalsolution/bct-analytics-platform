# -*- coding: utf-8 -*-
"""The RESP client is hand-written, so its wire format is tested directly."""
import io
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..tools.resp import RedisError, RespClient


class _FakeSocket:
    """Records what was sent and replays a scripted reply stream."""

    def __init__(self, script=b""):
        self.sent = b""
        self._to_read = io.BytesIO(script)

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        return self._to_read.read(size)

    def settimeout(self, _t):
        pass

    def close(self):
        pass


@tagged("post_install", "-at_install", "hms")
class TestRespEncoding(TransactionCase):
    def test_encodes_command_as_resp_array(self):
        wire = RespClient._encode("PUBLISH", "hms:db:queue.called", '{"n": 1}')
        self.assertEqual(
            wire,
            b"*3\r\n$7\r\nPUBLISH\r\n$19\r\nhms:db:queue.called\r\n$8\r\n{\"n\": 1}\r\n",
        )

    def test_encodes_non_string_arguments(self):
        wire = RespClient._encode("SELECT", 3)
        self.assertEqual(wire, b"*2\r\n$6\r\nSELECT\r\n$1\r\n3\r\n")

    def test_utf8_length_is_bytes_not_characters(self):
        """A channel name with non-ASCII must declare its byte length."""
        wire = RespClient._encode("PUBLISH", "poli-anák", "x")
        self.assertIn(b"$10\r\npoli-an\xc3\xa1k\r\n", wire)

    def _client_with(self, script):
        client = RespClient(host="unused")
        client._sock = _FakeSocket(script)
        return client

    def test_parses_integer_reply(self):
        client = self._client_with(b":2\r\n")
        self.assertEqual(client.command("PUBLISH", "c", "m"), 2)

    def test_parses_simple_string_reply(self):
        client = self._client_with(b"+PONG\r\n")
        self.assertEqual(client.command("PING"), "PONG")

    def test_parses_bulk_string_reply(self):
        client = self._client_with(b"$5\r\nhello\r\n")
        self.assertEqual(client.command("GET", "k"), b"hello")

    def test_parses_nil_bulk_reply(self):
        client = self._client_with(b"$-1\r\n")
        self.assertIsNone(client.command("GET", "missing"))

    def test_error_reply_raises(self):
        client = self._client_with(b"-NOAUTH Authentication required.\r\n")
        with self.assertRaises(RedisError):
            client.command("PUBLISH", "c", "m")

    def test_reply_split_across_packets_is_reassembled(self):
        """recv() returning partial data must not corrupt the parse."""
        client = RespClient(host="unused")

        class Choppy(_FakeSocket):
            def recv(self, size):
                return self._to_read.read(1)

        client._sock = Choppy(b"$5\r\nhello\r\n")
        self.assertEqual(client.command("GET", "k"), b"hello")

    def test_truncated_stream_raises_rather_than_hanging(self):
        client = self._client_with(b"$5\r\nhel")
        with self.assertRaises(RedisError):
            client.command("GET", "k")


@tagged("post_install", "-at_install", "hms")
class TestOutboxDegradation(TransactionCase):
    def test_emit_survives_redis_being_unreachable(self):
        """Registration must not fail because a TV screen cannot be updated."""
        Event = self.env["hms.event"]
        # Port 1 is reserved and refuses connections immediately, so this
        # exercises the real socket path rather than a stubbed failure.
        unreachable = {"host": "127.0.0.1", "port": 1, "password": None, "db": 0}
        patcher = patch.object(
            type(Event), "_redis_settings", lambda self: unreachable
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        event = Event.create({"topic": "queue.called", "payload": '{"x": 1}'})
        sent = event._publish_batch()
        self.assertEqual(sent, 0)
        self.assertFalse(event.published)
        self.assertTrue(event.last_error)
        self.assertEqual(event.attempts, 0,
                         "Kegagalan koneksi tidak boleh menghabiskan jatah percobaan.")
