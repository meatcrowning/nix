"""Portable MOSS token maps in a private ancillary PNG chunk (paHm), versions 1–3."""
import json
import re
import struct
import zlib
from functools import lru_cache

CHUNK = b'paHm'
LIMIT = 24 * 1024 * 1024


def aggregate(document, pixels):
    """Mean of all visible token scores, before thresholds or colour mapping."""
    area = document['width'] * document['height']
    planes = [pixels[t['index']*area:(t['index']+1)*area]
              for t in document['tokens'] if t['visible']]
    count = len(planes)
    if not count:
        return bytes(area)
    totals = list(map(sum, zip(*planes)))
    # One display stretch after aggregation reveals structure without giving
    # already coloured/thresholded masks extra weight. Flat maps stay flat.
    ordered = sorted(totals)
    low, high = ordered[int((area - 1) * .05)], ordered[int((area - 1) * .95)]
    if high == low:
        return bytes(round(value / count) for value in totals)
    return bytes(0 if value <= low else 255 if value >= high else
                 round(255 * ((value - low) / (high - low))) for value in totals)


def descriptive_aggregate(document, pixels):
    """Combine prompt content, excluding compiled layout keys/coordinates."""
    from moss_rank import descriptive_spans
    spans = descriptive_spans(document.get('prompt', ''))
    tokens = [t for t in document['tokens'] if t['visible'] and
              any(a < t.get('end', -1) and b > t.get('start', -1) for a, b in spans)]
    return aggregate(dict(document, tokens=tokens), pixels)


def json_value_span(source, path):
    """Locate a JSON value without losing offsets to escaping or repeated text."""
    decoder = json.JSONDecoder()
    def skip(i):
        while i < len(source) and source[i].isspace(): i += 1
        return i
    def descend(i, keys):
        i = skip(i)
        if not keys:
            _, end = decoder.raw_decode(source, i)
            return i, end
        key, rest = keys[0], keys[1:]
        if source[i] == '{':
            i = skip(i + 1)
            while source[i] != '}':
                name, end = decoder.raw_decode(source, i)
                i = skip(end)
                if source[i] != ':': raise ValueError('Missing colon')
                i = skip(i + 1)
                if name == key: return descend(i, rest)
                _, i = decoder.raw_decode(source, i)
                i = skip(i)
                if source[i] != ',': break
                i = skip(i + 1)
        elif source[i] == '[' and isinstance(key, int) and key >= 0:
            i = skip(i + 1)
            for index in range(key + 1):
                if index == key: return descend(i, rest)
                _, i = decoder.raw_decode(source, i)
                i = skip(i)
                if source[i] != ',': break
                i = skip(i + 1)
        raise ValueError('Missing JSON field')
    return descend(0, path)


@lru_cache(maxsize=16)
def prompt_positions(saved, text, region_index=None):
    """Resolve a caption once, including escaped offsets, for all its characters."""
    caption, offset = saved, 0
    literal = None
    if region_index is not None:
        try:
            offset, end = json_value_span(saved, ('items', region_index, 'caption'))
            literal = saved[offset:end]
            caption = json.loads(literal)
        except (ValueError, IndexError):
            return ()
        # The caller checks the saved region's original caption. Compilation
        # may append typography instructions after that exact caption.
        if not isinstance(caption, str) or not caption.startswith(text.strip()):
            return ()
    elif text.strip() != saved.strip():
        # Layout compilation puts the prompt box in summary.caption. Anchor to
        # that field, never a substring which could also occur in a region.
        match = re.match(r'\s*\{\s*"summary"\s*:\s*\{\s*"caption"\s*:\s*', saved)
        if not match:
            return ()
        offset = match.end()
        try:
            caption, end = json.JSONDecoder().raw_decode(saved[offset:])
        except ValueError:
            return ()
        if not isinstance(caption, str) or text.strip() != caption.strip():
            return ()
        literal = saved[offset:offset + end]
    shift = len(caption) - len(caption.lstrip()) - (len(text) - len(text.lstrip()))
    positions = range(len(caption))
    if literal is not None:
        # The stored offsets address JSON source, including escaped characters.
        for ascii_only in (False, True):
            if json.dumps(caption, ensure_ascii=ascii_only) == literal:
                positions = []
                current = offset + 1
                for character in caption:
                    positions.append(current)
                    current += len(json.dumps(character, ensure_ascii=ascii_only)) - 2
                break
        else:
            return ()
    return tuple(positions[i+shift] if 0 <= i+shift < len(positions) else None for i in range(len(text)))


def prompt_position(saved, text, position, region_index=None):
    """Map an editor character to plain conditioning or a compiled scene caption."""
    positions = prompt_positions(saved, text, region_index)
    return positions[position] if 0 <= position < len(positions) else None


def encode(document, maps):
    if '_word_pixels' in document:
        maps += document['_word_pixels']
    document = {k:v for k,v in document.items() if not k.startswith('_')}
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
    cap = {1: 64, 2: 128, 3: 128}.get(doc.get('version'), 0)
    if not (0 < n <= 4096 and 0 < h <= cap and 0 < w <= cap):
        raise ValueError('Unsupported token maps')
    if any(not isinstance(t, dict) or t.get('index') != i or not isinstance(t.get('text'), str)
           or not isinstance(t.get('visible'), bool) for i, t in enumerate(doc['tokens'])):
        raise ValueError('Invalid token metadata')
    words = doc.get('words', []) if doc.get('version') == 3 else []
    if not isinstance(words, list) or len(words) > n:
        raise ValueError('Invalid word metadata')
    if words:
        from moss_rank import word_groups
        expected, _ = word_groups(doc)
        if words != expected:
            raise ValueError('Word/token alignment changed')
    if len(pixels) != (n + len(words)) * h * w:
        raise ValueError('Truncated token maps')
    if words:
        doc['_word_pixels'] = pixels[n*h*w:]
        pixels = pixels[:n*h*w]
    consistency = doc.get('consistency')
    if consistency is not None:
        import math
        if not isinstance(consistency, list) or len(consistency) != n or any(
                not isinstance(v, (int, float)) or not math.isfinite(v) or not -1 <= v <= 1 for v in consistency):
            raise ValueError('Invalid capture consistency')
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
