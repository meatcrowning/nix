"""Read and write PNG tEXt chunks, with no dependencies beyond the stdlib.

Every image painter saves carries a `painter` chunk holding the exact parameters
that produced it -- including the prompt as actually sent, after any per-family
transform -- so a result can be reproduced or reloaded into the UI later.
"""

from __future__ import annotations

import json
import struct
import zlib

SIG = b"\x89PNG\r\n\x1a\n"


def _chunks(data: bytes):
    if not data.startswith(SIG):
        raise ValueError("not a PNG")
    pos = len(SIG)
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        crc = data[pos + 8 + length:pos + 12 + length]
        yield ctype, body, crc
        pos += 12 + length
        if ctype == b"IEND":
            break


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return (
        struct.pack(">I", len(body))
        + ctype
        + body
        + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)
    )


def read_text(data: bytes) -> dict:
    """All tEXt / iTXt / zTXt key-value pairs in a PNG."""
    out = {}
    for ctype, body, _crc in _chunks(data):
        try:
            if ctype == b"tEXt":
                key, _, val = body.partition(b"\x00")
                out[key.decode("latin-1")] = val.decode("latin-1")
            elif ctype == b"zTXt":
                key, _, rest = body.partition(b"\x00")
                if rest[:1] == b"\x00":
                    out[key.decode("latin-1")] = zlib.decompress(rest[1:]).decode("latin-1")
            elif ctype == b"iTXt":
                key, _, rest = body.partition(b"\x00")
                if len(rest) < 2:
                    continue
                compressed, method = rest[0], rest[1]
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _translated, _, text = rest.partition(b"\x00")
                if compressed and method == 0:
                    text = zlib.decompress(text)
                out[key.decode("latin-1")] = text.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a malformed chunk must not stop the rest
            continue
    return out


def upsert_text(data: bytes, values: dict) -> bytes:
    """Return the PNG with `values` written as tEXt, replacing existing keys."""
    keys = {str(k) for k in values}
    out = bytearray(SIG)
    inserted = False
    for ctype, body, _crc in _chunks(data):
        if ctype in (b"tEXt", b"zTXt", b"iTXt"):
            existing, _, _ = body.partition(b"\x00")
            if existing.decode("latin-1") in keys:
                continue  # drop; the new value is written below
        if ctype == b"IDAT" and not inserted:
            for k, v in values.items():
                text = v if isinstance(v, str) else json.dumps(v, sort_keys=True)
                out += _chunk(
                    b"tEXt",
                    str(k).encode("latin-1", "replace") + b"\x00"
                    + text.encode("latin-1", "replace"),
                )
            inserted = True
        out += _chunk(ctype, body)
    return bytes(out)


def describe(params: dict, pairing: dict | None = None) -> dict:
    """Flatten a generation into the chunk payload we store."""
    doc = dict(params)
    if pairing:
        doc["model"] = getattr(pairing.get("model"), "name", None)
        doc["family"] = pairing.get("family_id")
        enc, vae = pairing.get("encoder"), pairing.get("vae")
        doc["encoder"] = getattr(enc, "name", None)
        doc["vae"] = getattr(vae, "name", None)
    return {"painter": json.dumps(doc, sort_keys=True, default=str)}


def load_params(data: bytes) -> dict | None:
    raw = read_text(data).get("painter")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
