#!/usr/bin/env python3
"""clipfile — put FILES on the Wayland clipboard, as files.

    python3 clipfile.py FILE [FILE...]      # exit 0 once the selection is ours

Why this exists instead of `wl-copy --type text/uri-list`, which is what
painter used until it turned out that pasting the copy gave TEXT rather than
the file:

  * **wl-copy offers exactly one MIME type.** A file copy needs at least two:
    `text/uri-list`, which Qt reads (`QMimeData::urls`), and
    `x-special/gnome-copied-files`, which is how GTK — and Chromium/Electron
    behind it, i.e. a browser or Discord — decides a paste is a FILE rather
    than a string. Offer only the first and the apps that want the second fall
    back to whatever text is on the clipboard.
  * **wl-copy appends a newline to argv content** (that is what `-n` turns
    off), so the payload was `file:///…mp4\\n`. A `text/uri-list` is
    CRLF-terminated, RFC 2483; a consumer that splits on CRLF gets one entry
    with a stray LF glued to the end and rejects it as a URI.

It speaks the Wayland wire protocol directly — stdlib only, no bindings —
over `zwlr_data_control_manager_v1` (or `ext_data_control_manager_v1`), which
is the same protocol wl-clipboard uses and the reason this can work at all:
data-control needs neither a surface nor keyboard focus, so the clipboard
owner may be a headless background process. `QClipboard` cannot do this job —
`wl_data_device.set_selection` wants an input-event serial, which only a
focused window has.

It forks once the compositor has acknowledged the selection: the parent exits
0 (so a caller can report success or failure honestly) and the child stays on
as the holder, because a Wayland selection dies with the process that offered
it and a copy must outlive the app that made it. The child exits when
something else takes the clipboard.
"""

import array
import os
import socket
import struct
import sys
from urllib.parse import quote

DISPLAY = 1          # wl_display is always object id 1
DISPLAY_ERROR = 0    # wl_display.error
CALLBACK_DONE = 0    # wl_callback.done
REGISTRY_GLOBAL = 0  # wl_registry.global
SOURCE_SEND = 0      # zwlr_data_control_source_v1.send
SOURCE_CANCELLED = 1 # zwlr_data_control_source_v1.cancelled

# In offer order. gnome-copied-files first because a consumer that scans the
# list and takes the first thing it understands should land on the file
# interpretation, not on the text one.
def payloads(paths):
    uris = ["file://" + quote(os.path.abspath(p), safe="/") for p in paths]
    text = "\n".join(os.path.abspath(p) for p in paths)
    body = {
        # "copy" (vs "cut"), then the URIs, LF-separated and unterminated.
        "x-special/gnome-copied-files": ("copy\n" + "\n".join(uris)).encode(),
        # RFC 2483: every entry CRLF-terminated, the last one included.
        "text/uri-list": "".join(u + "\r\n" for u in uris).encode(),
        "text/plain": text.encode(),
    }
    # The aliases X11-era clients still ask for, same content as text/plain.
    for alias in ("text/plain;charset=utf-8", "UTF8_STRING", "STRING", "TEXT"):
        body[alias] = body["text/plain"]
    return body


def pad(n):
    return (n + 3) & ~3


def wstr(s):
    b = s.encode() + b"\0"
    return struct.pack("<I", len(b)) + b + b"\0" * (pad(len(b)) - len(b))


def rstr(payload, off):
    (n,) = struct.unpack_from("<I", payload, off)
    return payload[off + 4:off + 4 + n - 1].decode(errors="replace"), off + 4 + pad(n)


class Wire:
    """The Wayland connection: object ids out, events (and their fds) in."""

    def __init__(self):
        disp = os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
        path = disp if disp.startswith("/") else os.path.join(
            os.environ.get("XDG_RUNTIME_DIR", ""), disp)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self._next = 2
        self._buf = b""
        self.fds = []

    def nid(self):
        self._next += 1
        return self._next - 1

    def send(self, obj, opcode, payload=b""):
        self.sock.sendall(
            struct.pack("<II", obj, ((8 + len(payload)) << 16) | opcode) + payload)

    def event(self):
        """The next (object, opcode, payload). File descriptors do not travel in
        the payload — they arrive as SCM_RIGHTS ancillary data, in the order the
        events that carry them do, so they queue separately."""
        while True:
            if len(self._buf) >= 8:
                obj, word = struct.unpack("<II", self._buf[:8])
                size, opcode = word >> 16, word & 0xFFFF
                if len(self._buf) >= size:
                    payload, self._buf = self._buf[8:size], self._buf[size:]
                    return obj, opcode, payload
            data, anc, _flags, _addr = self.sock.recvmsg(
                4096, socket.CMSG_SPACE(16 * 4))
            if not data and not anc:
                raise EOFError("the compositor closed the connection")
            for level, typ, cdata in anc:
                if level == socket.SOL_SOCKET and typ == socket.SCM_RIGHTS:
                    a = array.array("i")
                    a.frombytes(cdata[:len(cdata) - (len(cdata) % a.itemsize)])
                    self.fds.extend(a)
            self._buf += data

    def roundtrip(self, on_event=None):
        """wl_display.sync, draining events until it comes back. Any
        wl_display.error on the way is fatal and says why."""
        cb = self.nid()
        self.send(DISPLAY, 0, struct.pack("<I", cb))   # wl_display.sync
        while True:
            obj, opcode, payload = self.event()
            if obj == DISPLAY and opcode == DISPLAY_ERROR:
                _oid, _code = struct.unpack_from("<II", payload, 0)
                msg, _ = rstr(payload, 8)
                raise RuntimeError(msg)
            if obj == cb and opcode == CALLBACK_DONE:
                return
            if on_event:
                on_event(obj, opcode, payload)


MANAGERS = ("zwlr_data_control_manager_v1", "ext_data_control_manager_v1")


def copy(paths):
    body = payloads(paths)
    w = Wire()

    registry = w.nid()
    w.send(DISPLAY, 1, struct.pack("<I", registry))      # wl_display.get_registry
    globals_ = {}

    def collect(obj, opcode, payload):
        if obj == registry and opcode == REGISTRY_GLOBAL:
            (name,) = struct.unpack_from("<I", payload, 0)
            iface, off = rstr(payload, 4)
            (version,) = struct.unpack_from("<I", payload, off)
            globals_.setdefault(iface, (name, version))

    w.roundtrip(collect)

    iface = next((m for m in MANAGERS if m in globals_), None)
    if iface is None or "wl_seat" not in globals_:
        raise RuntimeError("this compositor offers no data-control protocol")

    def bind(name, ifname, version):
        oid = w.nid()
        w.send(registry, 0,
               struct.pack("<I", name) + wstr(ifname)
               + struct.pack("<II", version, oid))
        return oid

    mname, mver = globals_[iface]
    manager = bind(mname, iface, min(mver, 2))
    sname, sver = globals_["wl_seat"]
    seat = bind(sname, "wl_seat", min(sver, 2))

    source = w.nid()
    w.send(manager, 0, struct.pack("<I", source))          # create_data_source
    for mime in body:
        w.send(source, 0, wstr(mime))                      # source.offer
    device = w.nid()
    w.send(manager, 1, struct.pack("<II", device, seat))   # get_data_device
    w.send(device, 0, struct.pack("<I", source))           # set_selection

    # Only now is the copy real; a protocol error would have arrived by here.
    w.roundtrip()
    return w, source, body


def serve(w, source, body):
    """Hand the bytes over on every paste, until the clipboard moves on."""
    while True:
        try:
            obj, opcode, payload = w.event()
        except (EOFError, OSError):
            return
        if obj != source:
            continue
        if opcode == SOURCE_CANCELLED:
            return
        if opcode == SOURCE_SEND:
            mime, _ = rstr(payload, 0)
            fd = w.fds.pop(0) if w.fds else None
            if fd is None:
                continue
            data = body.get(mime, b"")
            try:
                while data:
                    data = data[os.write(fd, data):]
            except OSError:
                pass          # the paster went away mid-read; not our problem
            finally:
                os.close(fd)


def main(argv):
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if not paths:
        print("usage: clipfile.py FILE [FILE...]", file=sys.stderr)
        return 2
    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        print("no such file: " + ", ".join(missing), file=sys.stderr)
        return 1
    try:
        w, source, body = copy(paths)
    except Exception as exc:                              # noqa: BLE001
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if os.fork():
        # The parent's exit code IS the answer: the selection is ours.
        os._exit(0)
    os.setsid()
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    serve(w, source, body)
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
