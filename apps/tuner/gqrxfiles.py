"""Read gqrx's settings and share its bookmarks file.

Bookmarks are read from and written back to gqrx's own bookmarks.csv in
gqrx's format, so both programs see the same list. gqrx's default.conf is
only read, once, to seed tuner's first settings.
"""

import configparser
import os
import re
import struct
from pathlib import Path

GQRX_DIR = Path(os.environ.get("TUNER_GQRX_DIR", Path.home() / ".config/gqrx"))


class Bookmark:
    __slots__ = ("freq", "name", "mode", "bandwidth", "tags")

    def __init__(self, freq, name, mode, bandwidth, tags):
        self.freq, self.name, self.mode, self.bandwidth, self.tags = freq, name, mode, bandwidth, tags


class Bookmarks:
    def __init__(self, path=None):
        self.path = Path(path) if path else GQRX_DIR / "bookmarks.csv"
        self.tags = {}  # name -> "#rrggbb"
        self.items = []
        self.load()

    def load(self):
        self.tags, self.items = {}, []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return
        section = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# Tag name"):
                section = "tags"
                continue
            if stripped.startswith("# Frequency"):
                section = "bookmarks"
                continue
            if not stripped or stripped.startswith("#"):
                continue
            fields = [f.strip() for f in line.split(";")]
            if section == "tags" and len(fields) >= 2:
                self.tags[fields[0]] = fields[1]
            elif section == "bookmarks" and len(fields) >= 5:
                try:
                    freq, bandwidth = int(fields[0]), int(fields[3] or 0)
                except ValueError:
                    continue
                tags = [t.strip() for t in fields[4].split(",") if t.strip()]
                self.items.append(Bookmark(freq, fields[1], fields[2], bandwidth, tags))
        self.items.sort(key=lambda b: b.freq)

    def tag_colour(self, bookmark):
        for tag in bookmark.tags:
            if tag in self.tags:
                return self.tags[tag]
        return "#c0c0c0"

    def save(self):
        lines = ["# Tag name          ;  color"]
        for name, colour in self.tags.items():
            lines.append("%-20s; %s" % (name, colour))
        lines += ["", "# Frequency ; Name                     ; Modulation          ;  Bandwidth; Tags"]
        for b in sorted(self.items, key=lambda b: b.freq):
            lines.append("%12d; %-25s; %-20s; %10d; %s"
                         % (b.freq, b.name.replace(";", ","), b.mode, b.bandwidth, ",".join(b.tags)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".csv.tuner-tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def add(self, bookmark):
        for tag in bookmark.tags:
            self.tags.setdefault(tag, "#c0c0c0")
        self.items.append(bookmark)
        self.save()

    def remove(self, bookmark):
        self.items = [b for b in self.items if b is not bookmark]
        self.save()


def _qt_unescape(value):
    """Decode the C-style escapes QSettings writes into an ini value."""
    out = bytearray()
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            n = value[i + 1]
            if n == "x":
                m = re.match(r"[0-9a-fA-F]{1,4}", value[i + 2:])
                if m:
                    out += bytes([int(m.group(0), 16) & 0xFF])
                    i += 2 + len(m.group(0))
                    continue
            if n.isdigit():
                m = re.match(r"[0-7]{1,3}", value[i + 1:])
                out += bytes([int(m.group(0), 8) & 0xFF])
                i += 1 + len(m.group(0))
                continue
            out += {"n": b"\n", "t": b"\t", "r": b"\r"}.get(n, n.encode())
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return bytes(out)


def _parse_gains(value):
    """gains=@Variant(QVariantMap) -> {"LNA": dB}. Best effort."""
    m = re.match(r"@Variant\((.*)\)$", value)
    if not m:
        return {}
    data = _qt_unescape(m.group(1))
    try:
        # QSettings writes variants without QDataStream's null flag here.
        kind, count = struct.unpack(">II", data[:8])
        pos, gains = 8, {}
        for _ in range(count):
            (klen,) = struct.unpack(">I", data[pos:pos + 4])
            key = data[pos + 4:pos + 4 + klen].decode("utf-16-be")
            pos += 4 + klen
            vtype, val = struct.unpack(">Ii", data[pos:pos + 8])
            pos += 8
            if vtype in (2, 3):
                gains[key] = val / 10.0
        return gains
    except (struct.error, UnicodeError):
        return {}


def read_gqrx_settings():
    """The subset of gqrx's default.conf that maps onto tuner's settings."""
    path = GQRX_DIR / "default.conf"
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return {}
    get = lambda section, key: parser.get(section, key, fallback=None)  # noqa: E731
    out = {}
    try:
        if get("input", "frequency"):
            lo = int(get("input", "frequency"))
            out["frequency"] = lo + int(get("receiver", "offset") or 0)
        if get("input", "sample_rate"):
            out["sample_rate"] = int(float(get("input", "sample_rate")))
        if get("input", "corr_freq"):
            out["ppm"] = int(get("input", "corr_freq")) / 1e6
        gains = _parse_gains(get("input", "gains") or "")
        if "LNA" in gains:
            out["gain_db"] = gains["LNA"]
        if get("receiver", "demod"):
            out["mode"] = get("receiver", "demod")
        for key in ("filter_low_cut", "filter_high_cut"):
            if get("receiver", key):
                out["filter_" + key.split("_")[1]] = int(get("receiver", key))
        if get("receiver", "agc_decay"):
            out["agc_decay_ms"] = int(get("receiver", "agc_decay"))
        if get("receiver", "sql_level"):
            out["squelch_db"] = float(get("receiver", "sql_level"))
        if get("audio", "gain"):
            out["volume_db"] = int(get("audio", "gain")) / 10.0  # gqrx stores tenths of a dB
        if get("audio", "udp_host"):
            out["udp_host"] = get("audio", "udp_host")
        if get("audio", "udp_port"):
            out["udp_port"] = int(get("audio", "udp_port"))
        if get("audio", "rec_dir"):
            out["rec_dir"] = get("audio", "rec_dir")
    except ValueError:
        pass
    return out
