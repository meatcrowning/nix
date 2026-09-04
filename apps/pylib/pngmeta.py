"""Read and write PNG tEXt chunks, with no dependencies beyond the stdlib.

Every image painter saves carries a `painter` chunk holding the exact parameters
that produced it -- including the prompt as actually sent, after any per-family
transform -- so a result can be reproduced or reloaded into the UI later. For
NegPip images it also carries `prompt_boxes`, the positive and negative editor
values from before the graph-time fold, so injection can restore both boxes.

It lives in pylib because it has two callers: painter WRITES those chunks and
filer's metadata filter READS them, along with whatever ComfyUI (`prompt`,
`workflow`) and cte (`cte_*`) wrote into the same place. One parser, not two.
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


TEXT_TYPES = (b"tEXt", b"zTXt", b"iTXt")


def _decode_text(ctype: bytes, body: bytes, out: dict) -> None:
    """Decode one text chunk into `out`. A malformed one is skipped, not raised."""
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
                return
            compressed, method = rest[0], rest[1]
            rest = rest[2:]
            _lang, _, rest = rest.partition(b"\x00")
            _translated, _, text = rest.partition(b"\x00")
            if compressed and method == 0:
                text = zlib.decompress(text)
            out[key.decode("latin-1")] = text.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - a malformed chunk must not stop the rest
        return


def read_text(data: bytes) -> dict:
    """All tEXt / iTXt / zTXt key-value pairs in a PNG."""
    out = {}
    for ctype, body, _crc in _chunks(data):
        _decode_text(ctype, body, out)
    return out


def read_text_path(path, cap: int = 4 * 1024 * 1024) -> dict:
    """The same pairs, read from a file WITHOUT touching the pixels.

    Walks the chunk table by seeking over each body and stops at the first IDAT,
    so the cost is the header plus the text rather than the image. Measured over
    500 of his ComfyUI outputs: 1.34s to read a 4 MiB prefix of each and parse,
    0.18s this way — which is what makes filtering a whole gen directory on its
    metadata affordable. `cap` bounds the text taken from one file so a
    pathological chunk cannot eat the process. Anything that is not a readable
    PNG returns {}.

    A writer is *allowed* to put text chunks after the pixels, and one of his
    (1 file in 595, measured) does — so a file with nothing in front of IDAT
    gets `_tail_text` as well. Seeking the whole chunk table instead would find
    those too and cost 7.4s per 500 files: an IDAT-heavy PNG is thousands of
    8-byte reads, which is slower than reading the image outright.
    """
    out: dict = {}
    try:
        with open(path, "rb") as fh:
            if fh.read(len(SIG)) != SIG:
                return {}
            taken = 0
            while True:
                head = fh.read(8)
                if len(head) < 8:
                    break
                (length,) = struct.unpack(">I", head[:4])
                ctype = head[4:]
                if ctype in (b"IDAT", b"IEND"):
                    break
                if ctype in TEXT_TYPES and taken < cap:
                    body = fh.read(min(length, cap - taken))
                    taken += len(body)
                    _decode_text(ctype, body, out)
                    fh.seek(length - len(body) + 4, 1)  # rest of the body + CRC
                else:
                    fh.seek(length + 4, 1)
            if not out:
                _tail_text(fh, out, cap)
    except OSError:
        return out
    except Exception:  # noqa: BLE001 - a truncated or lying length is not an error here
        return out
    return out


def _tail_text(fh, out: dict, cap: int, window: int = 256 * 1024) -> None:
    """Text chunks appended after the pixels, found by scanning the file's tail.

    The chunk table is not walked to get here (that is the expensive path this
    exists to avoid), so each candidate is validated by its own CRC before it is
    decoded — a byte pattern inside compressed pixel data is not a chunk.
    """
    try:
        fh.seek(0, 2)
        size = fh.tell()
        start = max(0, size - window)
        fh.seek(start)
        buf = fh.read(window)
    except OSError:
        return
    taken = 0
    for ctype in TEXT_TYPES:
        pos = buf.find(ctype)
        while pos >= 4 and taken < cap:
            (length,) = struct.unpack(">I", buf[pos - 4:pos])
            body = buf[pos + 4:pos + 4 + length]
            crc = buf[pos + 4 + length:pos + 8 + length]
            if (len(body) == length and len(crc) == 4
                    and struct.unpack(">I", crc)[0] == zlib.crc32(ctype + body) & 0xFFFFFFFF):
                _decode_text(ctype, body, out)
                taken += length
            pos = buf.find(ctype, pos + 1)


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
