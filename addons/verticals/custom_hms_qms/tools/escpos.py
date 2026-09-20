# -*- coding: utf-8 -*-
"""ESC/POS command builder for thermal queue-ticket printers.

Written rather than imported: the Odoo image carries no ESC/POS package, and
the subset a queue ticket needs — alignment, double-height text, a barcode, a
cut — is a handful of well-documented escape sequences.

Bytes only. Transport (TCP 9100, USB agent, or a browser fallback) is the
caller's problem, which keeps this testable without hardware.
"""

ESC = b"\x1b"
GS = b"\x1d"

ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
ALIGN_RIGHT = ESC + b"a\x02"

BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"

# GS ! n — the low nibble is width, the high nibble height, each 0-7.
SIZE_NORMAL = GS + b"!\x00"
SIZE_DOUBLE = GS + b"!\x11"
SIZE_TRIPLE = GS + b"!\x22"

INIT = ESC + b"@"
CUT_FULL = GS + b"V\x00"
CUT_PARTIAL = GS + b"V\x01"
FEED = b"\n"


def _encode(text, codepage="cp437"):
    """Encode text for the printer, dropping what it cannot represent.

    Thermal printers speak a single-byte code page, not UTF-8. Indonesian text
    is almost entirely ASCII, so the loss is limited to the occasional dash or
    quotation mark — much better than a printer that jams on an unknown byte.
    """
    try:
        return text.encode(codepage, "replace")
    except LookupError:
        return text.encode("ascii", "replace")


class EscposBuilder:
    def __init__(self, width=32, codepage="cp437"):
        # 32 characters is a 58 mm roll, 48 is 80 mm.
        self.width = width
        self.codepage = codepage
        self._parts = [INIT]

    def text(self, value, align=ALIGN_LEFT, size=SIZE_NORMAL, bold=False):
        self._parts.append(align)
        self._parts.append(size)
        if bold:
            self._parts.append(BOLD_ON)
        self._parts.append(_encode(value, self.codepage))
        self._parts.append(FEED)
        if bold:
            self._parts.append(BOLD_OFF)
        self._parts.append(SIZE_NORMAL)
        return self

    def center(self, value, **kw):
        return self.text(value, align=ALIGN_CENTER, **kw)

    def big(self, value):
        return self.text(value, align=ALIGN_CENTER, size=SIZE_TRIPLE, bold=True)

    def line(self, char="-"):
        self._parts.append(ALIGN_LEFT)
        self._parts.append(_encode(char * self.width, self.codepage))
        self._parts.append(FEED)
        return self

    def columns(self, left, right):
        """Left- and right-justified pair on one line."""
        space = max(self.width - len(left) - len(right), 1)
        return self.text(f"{left}{' ' * space}{right}")

    def feed(self, lines=1):
        self._parts.append(FEED * lines)
        return self

    def barcode(self, data, height=60, width=2):
        """CODE128 barcode. Ignored silently by printers that lack the font."""
        payload = _encode(data, "ascii")
        self._parts.append(ALIGN_CENTER)
        self._parts.append(GS + b"h" + bytes([height]))
        self._parts.append(GS + b"w" + bytes([width]))
        self._parts.append(GS + b"H\x02")  # print HRI below the barcode
        # GS k m n d1..dn, m=73 selects CODE128 with an explicit length byte.
        self._parts.append(GS + b"k\x49" + bytes([len(payload) + 2]) + b"{B" + payload)
        self._parts.append(FEED)
        return self

    def qr(self, data, size=6):
        """QR code via the GS ( k model-2 sequence."""
        payload = _encode(data, "utf-8")
        self._parts.append(ALIGN_CENTER)
        self._parts.append(GS + b"(k\x04\x00\x31\x41\x32\x00")        # model 2
        self._parts.append(GS + b"(k\x03\x00\x31\x43" + bytes([size]))  # module size
        self._parts.append(GS + b"(k\x03\x00\x31\x45\x30")            # error correction L
        length = len(payload) + 3
        self._parts.append(
            GS + b"(k" + bytes([length & 0xFF, (length >> 8) & 0xFF]) + b"\x31\x50\x30" + payload
        )
        self._parts.append(GS + b"(k\x03\x00\x31\x51\x30")            # print
        self._parts.append(FEED)
        return self

    def cut(self, partial=True):
        self._parts.append(FEED * 3)
        self._parts.append(CUT_PARTIAL if partial else CUT_FULL)
        return self

    def build(self):
        return b"".join(self._parts)
