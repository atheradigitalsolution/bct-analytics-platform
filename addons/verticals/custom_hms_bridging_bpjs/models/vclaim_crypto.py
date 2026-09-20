# -*- coding: utf-8 -*-
"""VClaim request signing and response decoding.

BPJS signs with HMAC-SHA256 over "consId&timestamp" and returns a response
body that is AES-256-CBC encrypted then LZ-String compressed. Both directions
are implemented here with the Python standard library plus the `cryptography`
package that Odoo already ships — no new dependency, which is the house rule.
"""
import base64
import hashlib
import hmac
import time


def timestamp():
    """BPJS expects seconds since epoch as a string, UTC."""
    return str(int(time.time()))


def signature(cons_id, secret_key, ts):
    """Return the base64 HMAC-SHA256 of `consId&timestamp`."""
    message = f"{cons_id}&{ts}".encode("utf-8")
    digest = hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def decrypt_key(cons_id, secret_key, ts):
    """The AES key BPJS uses is SHA-256 of consId + secretKey + timestamp."""
    return hashlib.sha256(f"{cons_id}{secret_key}{ts}".encode("utf-8")).digest()


def aes_decrypt(payload_b64, key):
    """Decrypt a VClaim response body.

    The IV is the first 16 bytes of the key, which is BPJS's own scheme — not
    a choice made here, and not one to copy elsewhere.
    """
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    raw = base64.b64decode(payload_b64)
    iv = key[:16]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def lz_decompress(compressed):
    """Decompress LZ-String `decompressFromEncodedURIComponent` output.

    LZ-String is a JavaScript compression format with no Python package in the
    Odoo image, so the decoder lives here. It is a dictionary coder: the input
    is a stream of variable-width bit codes over a growing dictionary, exactly
    like LZW but with the bit width negotiated in-band.
    """
    if not compressed:
        return ""
    if isinstance(compressed, bytes):
        compressed = compressed.decode("utf-8", "replace")
    key_str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-$"
    base_reverse = {ch: i for i, ch in enumerate(key_str)}
    compressed = compressed.replace(" ", "+")

    def get_bits(state, n):
        result = 0
        power = 1
        for _ in range(n):
            resb = state["val"] & state["position"]
            state["position"] >>= 1
            if state["position"] == 0:
                state["position"] = reset_value
                state["index"] += 1
                ch = compressed[state["index"]] if state["index"] < len(compressed) else "A"
                state["val"] = base_reverse.get(ch, 0)
            result |= (1 if resb > 0 else 0) * power
            power <<= 1
        return result

    # 32 == 1 << 5, because the encoded-URI variant packs SIX bits into every
    # character. The plain decompress() variant uses 32768 for 16-bit chars;
    # using that value here decodes pure zero bytes and looks like a cipher
    # problem rather than a bit-width one.
    reset_value = 32
    state = {
        "val": base_reverse.get(compressed[0], 0),
        "position": reset_value,
        "index": 0,
    }
    # The first two bits say how the first entry is encoded: 8-bit char,
    # 16-bit char, or end-of-stream.
    dictionary = {i: chr(i) for i in range(3)}
    enlarge_in, dict_size, num_bits = 4, 4, 3
    next_code = get_bits(state, 2)
    if next_code == 0:
        entry = chr(get_bits(state, 8))
    elif next_code == 1:
        entry = chr(get_bits(state, 16))
    else:
        return ""
    dictionary[3] = entry
    result = [entry]
    w = entry
    while True:
        if state["index"] > len(compressed):
            return ""
        code = get_bits(state, num_bits)
        if code in (0, 1):
            width = 8 if code == 0 else 16
            dictionary[dict_size] = chr(get_bits(state, width))
            code = dict_size
            dict_size += 1
            enlarge_in -= 1
        elif code == 2:
            return "".join(result)
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1
        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = w + w[0]
        else:
            return ""
        result.append(entry)
        dictionary[dict_size] = w + entry[0]
        dict_size += 1
        enlarge_in -= 1
        w = entry
        if enlarge_in == 0:
            enlarge_in = 1 << num_bits
            num_bits += 1


def decode_response(payload, cons_id, secret_key, ts):
    """Full VClaim response pipeline: base64 → AES → LZ-String → text."""
    key = decrypt_key(cons_id, secret_key, ts)
    plaintext = aes_decrypt(payload, key)
    return lz_decompress(plaintext.decode("utf-8", "replace"))
