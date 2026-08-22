"""Read and write MP4 metadata tags, with no dependencies beyond the stdlib.

The sibling of `pngmeta`, for the other half of painter's gallery. A still
carries the job that made it in a PNG `tEXt` chunk; a clip carries it here, as
an `mdta` key in `moov/udta/meta` — the same place ComfyUI's own `prompt` graph
already lands (it is what `ffprobe -show_entries format_tags` prints), so
painter's `painter` key sits beside it rather than in a sidecar file that a
copy, a drag or a move would leave behind.

Pure stdlib on purpose: this runs in the download callback, on the GUI thread,
once per finished clip. An ffmpeg remux would be a subprocess per output and a
second way for a finished generation to fail to reach the disk.

MOOV BEFORE MDAT IS THE NORMAL CASE HERE (ComfyUI's writer emits faststart),
so growing `moov` moves the media data and every chunk offset in the file with
it. `upsert_tags` patches `stco`/`co64` for exactly that; a file whose `moov`
sits after the media is left alone by the same test, since nothing moves.
"""

from __future__ import annotations

import json
import struct

# Boxes we descend into looking for the chunk-offset tables and the metadata.
_CONTAINERS = (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta")


def _boxes(data: bytes, start: int, end: int):
    """(type, box_start, header_len, box_end) for each box in [start, end)."""
    off = start
    while off + 8 <= end:
        (size,) = struct.unpack(">I", data[off:off + 4])
        ctype = data[off + 4:off + 8]
        hdr = 8
        if size == 1:
            if off + 16 > end:
                return
            (size,) = struct.unpack(">Q", data[off + 8:off + 16])
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            return
        yield ctype, off, hdr, off + size
        off += size


def _find(data: bytes, path, start=0, end=None):
    """Walk a box path — _find(d, (b"moov", b"udta")) -> (start, hdr, end)."""
    end = len(data) if end is None else end
    for ctype, off, hdr, stop in _boxes(data, start, end):
        if ctype != path[0]:
            continue
        if len(path) == 1:
            return off, hdr, stop
        inner = off + hdr
        if ctype == b"meta":
            inner += 4          # ISO `meta` is a FullBox; its children follow
        found = _find(data, path[1:], inner, stop)
        if found:
            return found
    return None


def _box(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body) + 8) + ctype + body


# ---------------------------------------------------------------- reading

def _read_meta(data: bytes, meta):
    """The `mdta` key list and the `ilst` values of one `meta` box."""
    m_off, m_hdr, m_end = meta
    inner = m_off + m_hdr + 4
    keys, values = [], {}
    kb = _find(data, (b"keys",), inner, m_end)
    if kb:
        k_off, k_hdr, k_end = kb
        pos = k_off + k_hdr + 8          # version/flags + entry_count
        while pos + 8 <= k_end:
            (size,) = struct.unpack(">I", data[pos:pos + 4])
            if size < 8 or pos + size > k_end:
                break
            keys.append(data[pos + 8:pos + size].decode("utf-8", "replace"))
            pos += size
    ib = _find(data, (b"ilst",), inner, m_end)
    if ib:
        i_off, i_hdr, i_end = ib
        for _t, off, hdr, stop in _boxes(data, i_off + i_hdr, i_end):
            (index,) = struct.unpack(">I", data[off + 4:off + 8])
            db = _find(data, (b"data",), off + hdr, stop)
            if not db or not (1 <= index <= len(keys)):
                continue
            d_off, d_hdr, d_end = db
            payload = data[d_off + d_hdr + 8:d_end]      # type + locale
            values[keys[index - 1]] = payload.decode("utf-8", "replace")
    return keys, values


def read_tags(data: bytes) -> dict:
    """Every `mdta` metadata key/value in the file. Not an MP4 -> {}."""
    meta = _find(data, (b"moov", b"udta", b"meta"))
    if not meta:
        return {}
    try:
        return _read_meta(data, meta)[1]
    except Exception:  # noqa: BLE001 - a malformed box is not an error here
        return {}


def read_tags_path(path, cap: int = 32 * 1024 * 1024) -> dict:
    """The same tags, read from a file. Anything unreadable returns {}.

    Only the `moov` box is read — it is at the front of everything painter
    writes, so the cost is the header rather than the media data behind it, and
    `cap` bounds what is pulled in when a file claims an implausible one.
    """
    try:
        with open(path, "rb") as fh:
            pos = 0
            while True:
                fh.seek(pos)
                head = fh.read(8)
                if len(head) < 8:
                    return {}
                (size,) = struct.unpack(">I", head[:4])
                ctype = head[4:]
                if size == 1:
                    ext = fh.read(8)
                    if len(ext) < 8:
                        return {}
                    (size,) = struct.unpack(">Q", ext)
                if ctype == b"moov":
                    if size > cap:
                        return {}
                    fh.seek(pos)
                    return read_tags(fh.read(size))
                if size < 8:
                    return {}
                pos += size
    except OSError:
        return {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- writing

def _keys_ilst(tags: dict) -> bytes:
    """A fresh `keys` + `ilst` pair holding exactly these tags."""
    entries = [(str(k), v if isinstance(v, str) else json.dumps(v, sort_keys=True))
               for k, v in tags.items()]
    keys_body = struct.pack(">II", 0, len(entries))
    for k, _v in entries:
        keys_body += _box(b"mdta", k.encode("utf-8"))
    ilst_body = b""
    for i, (_k, v) in enumerate(entries, start=1):
        data_box = _box(b"data", struct.pack(">II", 1, 0) + v.encode("utf-8"))
        ilst_body += struct.pack(">I", len(data_box) + 8) + struct.pack(">I", i) + data_box
    return _box(b"keys", keys_body) + _box(b"ilst", ilst_body)


_HDLR = _box(b"hdlr", struct.pack(">II", 0, 0) + b"mdta" + b"\x00" * 12 + b"\x00")


def _meta_box(tags: dict) -> bytes:
    return _box(b"meta", b"\x00\x00\x00\x00" + _HDLR + _keys_ilst(tags))


def _patch_offsets(data: bytearray, moov_start: int, moov_end: int, delta: int) -> None:
    """Add `delta` to every chunk offset pointing past `moov_start`.

    Called only when `moov` grew ahead of the media data, so everything after
    it — the `mdat` the sample tables address — has slid down the file by that
    much. An offset before `moov` (a `moov`-at-the-end file) never moves.
    """
    if not delta:
        return
    for ctype, off, hdr, stop in _boxes(data, moov_start, moov_end):
        if ctype in _CONTAINERS:
            inner = off + hdr
            _patch_offsets(data, inner, stop, delta)
        elif ctype in (b"stco", b"co64"):
            wide = ctype == b"co64"
            step = 8 if wide else 4
            (count,) = struct.unpack(">I", data[off + hdr + 4:off + hdr + 8])
            pos = off + hdr + 8
            for _ in range(count):
                if pos + step > stop:
                    break
                if wide:
                    (val,) = struct.unpack(">Q", data[pos:pos + step])
                    if val >= moov_start:
                        data[pos:pos + step] = struct.pack(">Q", val + delta)
                else:
                    (val,) = struct.unpack(">I", data[pos:pos + step])
                    if val >= moov_start:
                        data[pos:pos + step] = struct.pack(">I", val + delta)
                pos += step


def _resize(data: bytearray, box_start: int, delta: int) -> None:
    (size,) = struct.unpack(">I", data[box_start:box_start + 4])
    if size == 1:
        (size,) = struct.unpack(">Q", data[box_start + 8:box_start + 16])
        data[box_start + 8:box_start + 16] = struct.pack(">Q", size + delta)
    else:
        data[box_start:box_start + 4] = struct.pack(">I", size + delta)


def upsert_tags(data: bytes, values: dict) -> bytes:
    """Return the MP4 with `values` written as `mdta` tags, replacing existing keys.

    The whole `meta` box is rebuilt from the tags already in it plus these, so a
    second write cannot leave two `painter` keys behind. Raises ValueError on
    anything that is not an MP4 with a `moov` — the caller writes the file
    verbatim then, because an output that reaches the disk without its
    parameters beats one that does not reach the disk.
    """
    moov = _find(data, (b"moov",))
    if not moov:
        raise ValueError("no moov box")
    m_start, m_hdr, m_end = moov

    udta = _find(data, (b"moov", b"udta"))
    meta = _find(data, (b"moov", b"udta", b"meta"))
    existing = {}
    if meta:
        try:
            existing = _read_meta(data, meta)[1]
        except Exception:  # noqa: BLE001 - unreadable metadata is replaced, not kept
            existing = {}
    merged = dict(existing)
    for k, v in values.items():
        merged[str(k)] = v if isinstance(v, str) else json.dumps(v, sort_keys=True)

    new_meta = _meta_box(merged)
    if meta:
        cut_start, cut_end = meta[0], meta[2]
    elif udta:
        cut_start = cut_end = udta[0] + udta[1]      # append inside udta
    else:
        cut_start = cut_end = m_end                  # a new udta at moov's end

    out = bytearray(data)
    if udta:
        out[cut_start:cut_end] = new_meta
        delta = len(new_meta) - (cut_end - cut_start)
        _resize(out, udta[0], delta)
    else:
        new_udta = _box(b"udta", new_meta)
        out[cut_start:cut_end] = new_udta
        delta = len(new_udta)
    _resize(out, m_start, delta)
    _patch_offsets(out, m_start, m_end + delta, delta)
    return bytes(out)


# ------------------------------------------------------- painter's own key

def load_params(data: bytes) -> dict | None:
    """The generation painter recorded in this clip, or None."""
    raw = read_tags(data).get("painter")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None
