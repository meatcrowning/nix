"""Portable MOSS token maps in a private ancillary PNG chunk (paHm), version 1."""
import json
import struct
import zlib

CHUNK = b'paHm'
LIMIT = 24 * 1024 * 1024


def encode(document, maps):
    header = json.dumps(document, ensure_ascii=False, separators=(',', ':')).encode()
    raw = struct.pack('>I', len(header)) + header + maps
    if len(raw) > LIMIT:
        raise ValueError('Token maps exceed the storage limit')
    return zlib.compress(raw, 6)


def decode(blob):
    try:
        return _decode(blob)
    except (KeyError, TypeError, struct.error, zlib.error, UnicodeError) as exc:
        raise ValueError("Invalid token maps") from exc


def _decode(blob):
    inflater = zlib.decompressobj()
    raw = inflater.decompress(blob, LIMIT + 1)
    if len(raw) > LIMIT or not inflater.eof:
        raise ValueError('Invalid or oversized token maps')
    size, = struct.unpack('>I', raw[:4])
    doc = json.loads(raw[4:4 + size])
    pixels = raw[4 + size:]
    if not isinstance(doc, dict) or not isinstance(doc.get('tokens'), list):
        raise ValueError('Invalid token metadata')
    if type(doc.get('height')) is not int or type(doc.get('width')) is not int:
        raise ValueError('Invalid map dimensions')
    n, h, w = len(doc['tokens']), int(doc['height']), int(doc['width'])
    if doc.get('version') != 1 or not (0 < n <= 4096 and 0 < h <= 64 and 0 < w <= 64):
        raise ValueError('Unsupported token maps')
    if any(not isinstance(t, dict) or t.get('index') != i or not isinstance(t.get('text'), str)
           or not isinstance(t.get('visible'), bool) for i, t in enumerate(doc['tokens'])):
        raise ValueError('Invalid token metadata')
    if len(pixels) != n * h * w:
        raise ValueError('Truncated token maps')
    return doc, pixels


def read(path):
    with open(path, 'rb') as f:
        if f.read(8) != b'\x89PNG\r\n\x1a\n':
            return None
        while True:
            head = f.read(8)
            if len(head) != 8:
                return None
            size, kind = struct.unpack('>I4s', head)
            if kind == CHUNK:
                if size > LIMIT:
                    raise ValueError('Oversized token maps')
                data = f.read(size)
                crc = f.read(4)
                if len(crc) != 4 or struct.unpack('>I', crc)[0] != zlib.crc32(kind + data) & 0xffffffff:
                    raise ValueError('Damaged token maps')
                return decode(data)
            if kind == b'IEND':
                return None
            f.seek(size + 4, 1)
