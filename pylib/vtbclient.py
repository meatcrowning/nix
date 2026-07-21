"""Client for hyprvtb's app-button socket (the inner half of the double-wide
titlebar the compositor draws on every window's right edge).

Protocol (newline-terminated lines over a Unix stream socket at
$XDG_RUNTIME_DIR/hyprvtb-buttons.sock — see ~/nix/home/prog/hyprvtb/vtbIpc.hpp,
the server side):

    -> REGISTER <pid> <id>:<label>:<state>:<tip>:<drag>|...  our whole button set
    -> FOOTER <text>                             stacked text at column bottom
    -> TITLEEDIT <0|1>                           title region is an address bar
    <- CLICK <id>                                a button was clicked
    <- REORDER <srcId> <dstId>                   a draggable button was dropped
    <- ADDR <text>                               the title editor was submitted
    <- WAKE                                       the window was just un-hidden

Buttons are (id, label, state[, tooltip[, draggable[, bottom]]]) tuples —
state 0 normal, 1 active/lit, 2 disabled — or the string "-" for a separator.
Labels are 1-2 char glyphs drawn in the titlebar's pixel font; the optional
tooltip pops out beside the bar on hover; draggable (bool) marks a button
reorderable by dragging (surfer's tabs); bottom (bool) anchors it to the
bottom of the column (surfer's settings button). Fields may contain ANY
character — the wire
separators ':' and '|' (and newlines) are percent-encoded here and decoded by
the plugin, so a "|" or ":" glyph label survives intact.

All I/O runs on a daemon thread that reconnects forever (start the app before
the plugin loads and the buttons appear once it does; plugin reloads re-register
automatically). on_click/on_reorder/on_addr/on_wake fire ON THAT THREAD — Qt
apps should bounce them through a Signal (queued across threads) before touching
any UI.
"""
import os
import socket
import threading
import time


def _sock_path():
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(rt, "hyprvtb-buttons.sock")


class VtbClient:
    def __init__(self, on_click=None, pid=None, on_reorder=None, on_addr=None,
                 on_wake=None):
        self._on_click = on_click
        self._on_reorder = on_reorder
        self._on_addr = on_addr
        self._on_wake = on_wake
        self._pid = pid or os.getpid()
        self._lock = threading.Lock()
        self._sock = None          # guarded by _lock
        self._buttons = []         # last set, guarded by _lock (resent on reconnect)
        self._footer = ""
        self._title_edit = False
        self._stop = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---- public API ----

    def set_buttons(self, buttons):
        """buttons: list of (id, label, state[, tooltip[, draggable]]) tuples or
        "-" separators. Replaces the whole set; call again on any change."""
        with self._lock:
            self._buttons = list(buttons)
            self._send_register_locked()

    def set_footer(self, text):
        with self._lock:
            self._footer = str(text)
            self._send_footer_locked()

    def set_title_edit(self, on):
        """Mark the title region an editable address bar (surfer)."""
        with self._lock:
            self._title_edit = bool(on)
            self._send_title_edit_locked()

    def close(self):
        self._stop = True
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None

    # ---- wire helpers (call with _lock held) ----

    def _send_locked(self, line):
        if not self._sock:
            return
        try:
            self._sock.sendall((line + "\n").encode())
        except OSError:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None  # reader thread will reconnect

    @staticmethod
    def _enc(s):
        # Percent-encode only the wire separators (and newlines/CR) so a field
        # may hold ANY character — notably a "|" or ":" glyph label (e.g. kitty's
        # vertical-split "|"), which the old space-replacement silently blanked.
        # The plugin percent-decodes each field; non-ASCII glyphs (↑ » …) pass
        # through untouched as UTF-8. Order matters: "%" must be escaped first.
        return (str(s).replace("%", "%25").replace(":", "%3A").replace("|", "%7C")
                .replace("\n", "%0A").replace("\r", "%0D"))

    def _send_register_locked(self):
        if not self._buttons:
            return
        parts = []
        for b in self._buttons:
            if b == "-":
                parts.append("-::0")
            else:
                bid, label, state = b[0], b[1], b[2]
                tip = b[3] if len(b) > 3 else ""
                drag = 1 if (len(b) > 4 and b[4]) else 0
                bottom = 1 if (len(b) > 5 and b[5]) else 0
                parts.append(f"{self._enc(bid)}:{self._enc(label)}:{int(state)}:{self._enc(tip)}:{drag}:{bottom}")
        self._send_locked(f"REGISTER {self._pid} " + "|".join(parts))

    def _send_footer_locked(self):
        self._send_locked("FOOTER " + self._footer)

    def _send_title_edit_locked(self):
        self._send_locked("TITLEEDIT " + ("1" if self._title_edit else "0"))

    # ---- reader / reconnect thread ----

    def _loop(self):
        buf = b""
        while not self._stop:
            with self._lock:
                sock = self._sock
            if sock is None:
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(_sock_path())
                except OSError:
                    try:
                        sock.close()
                    except OSError:
                        pass
                    time.sleep(3)  # plugin not loaded (yet) — keep trying
                    continue
                buf = b""
                with self._lock:
                    self._sock = sock
                    self._send_register_locked()
                    if self._footer:
                        self._send_footer_locked()
                    if self._title_edit:
                        self._send_title_edit_locked()
            try:
                data = sock.recv(4096)
            except OSError:
                data = b""
            if not data:  # server gone (plugin unloaded) — reconnect loop
                with self._lock:
                    if self._sock is sock:
                        self._sock = None
                try:
                    sock.close()
                except OSError:
                    pass
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="replace").strip()
                try:
                    if text.startswith("CLICK ") and self._on_click:
                        self._on_click(text[6:])
                    elif text.startswith("REORDER ") and self._on_reorder:
                        rest = text[8:].split(" ", 1)
                        if len(rest) == 2:
                            self._on_reorder(rest[0], rest[1])
                    elif text.startswith("ADDR ") and self._on_addr:
                        self._on_addr(text[5:])
                    elif text == "WAKE" and self._on_wake:
                        self._on_wake()
                except Exception:
                    pass  # a handler bug must not kill the reader
