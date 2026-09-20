# -*- coding: utf-8 -*-
"""A minimal Redis client speaking RESP over a raw socket.

Why not the `redis` package: the Odoo image is shared by every tenant on this
host, and adding a dependency means rebuilding and redeploying that image for
all of them. The subset needed here — AUTH, SELECT, PUBLISH, SET, GET, PING —
is a few dozen lines of a well-specified protocol, so the module carries it.

Not a general-purpose client. No pipelining, no pub/sub subscription (Next.js
subscribes, Odoo only publishes), no cluster support, no connection pool: one
short-lived connection per publish batch, which is the access pattern here.
"""
import logging
import socket

_logger = logging.getLogger(__name__)

CRLF = b"\r\n"


class RedisError(Exception):
    """Raised for protocol-level errors and refused commands."""


class RespClient:
    def __init__(self, host="redis", port=6379, password=None, db=0, timeout=5.0):
        self.host = host
        self.port = int(port)
        self.password = password or None
        self.db = int(db)
        self.timeout = timeout
        self._sock = None
        self._buf = b""

    # --- connection -------------------------------------------------------
    def connect(self):
        if self._sock is not None:
            return self
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        self._buf = b""
        if self.password:
            self.command("AUTH", self.password)
        if self.db:
            self.command("SELECT", str(self.db))
        return self

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buf = b""

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # --- protocol ---------------------------------------------------------
    @staticmethod
    def _encode(*args):
        """Encode a command as a RESP array of bulk strings."""
        out = [b"*%d" % len(args), CRLF]
        for arg in args:
            if isinstance(arg, str):
                arg = arg.encode("utf-8")
            elif not isinstance(arg, (bytes, bytearray)):
                arg = str(arg).encode("utf-8")
            out += [b"$%d" % len(arg), CRLF, bytes(arg), CRLF]
        return b"".join(out)

    def _read_line(self):
        while CRLF not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise RedisError("Koneksi Redis terputus saat menunggu balasan.")
            self._buf += chunk
        line, _sep, rest = self._buf.partition(CRLF)
        self._buf = rest
        return line

    def _read_exact(self, size):
        while len(self._buf) < size + 2:  # payload plus trailing CRLF
            chunk = self._sock.recv(max(4096, size + 2 - len(self._buf)))
            if not chunk:
                raise RedisError("Koneksi Redis terputus saat membaca data.")
            self._buf += chunk
        data, self._buf = self._buf[:size], self._buf[size + 2:]
        return data

    def _read_reply(self):
        line = self._read_line()
        kind, payload = line[:1], line[1:]
        if kind == b"+":
            return payload.decode("utf-8")
        if kind == b"-":
            raise RedisError(payload.decode("utf-8"))
        if kind == b":":
            return int(payload)
        if kind == b"$":
            size = int(payload)
            if size == -1:
                return None
            return self._read_exact(size)
        if kind == b"*":
            count = int(payload)
            if count == -1:
                return None
            return [self._read_reply() for _ in range(count)]
        raise RedisError("Tipe balasan RESP tidak dikenal: %r" % kind)

    def command(self, *args):
        if self._sock is None:
            self.connect()
        self._sock.sendall(self._encode(*args))
        return self._read_reply()

    # --- the handful of commands this system uses -------------------------
    def publish(self, channel, message):
        return self.command("PUBLISH", channel, message)

    def set(self, key, value, ex=None):
        if ex:
            return self.command("SET", key, value, "EX", str(int(ex)))
        return self.command("SET", key, value)

    def get(self, key):
        return self.command("GET", key)

    def ping(self):
        return self.command("PING")
