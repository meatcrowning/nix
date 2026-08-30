"""Client for hyprvtb's app-button socket (the inner half of the double-wide
titlebar the compositor draws on every window's right edge).

Protocol (newline-terminated lines over a Unix stream socket at
$XDG_RUNTIME_DIR/hyprvtb-buttons.sock — see ~/nix/home/prog/hyprvtb/vtbIpc.hpp,
the server side):

    -> REGISTER <pid> <id>:<label>:<state>:<tip>:<drag>|...  our whole button set
    -> FOOTER <text>                             stacked text at column bottom
    -> FOOTERPOS <0|1>                           footer below the scrub bar (player)
    -> TITLEEDIT <0|1>                           title region is an address bar
    -> TITLETEXT <0|1>                           draw the stacked window title at all
                                                 (default 1; goetia sends 0)
    -> EDITSEED <text>                           what the address editor opens WITH,
                                                 when it must differ from the shown
                                                 title (surfer: bar shows the page
                                                 title, editor opens the real URL);
                                                 empty falls back to the title
    -> LOADING <0|1>                             page loading (draws a spinner)
    -> PLAYBAR <0|1> <pos>                       media scrub bar + playback fraction
    <- CLICK <id> <x> <y>                        a button was clicked;
                                                 x/y are window-local logical px
    <- RCLICK <id> <x> <y>                       a button was right-clicked
                                                 (x/y window-local, for a menu)
    <- REORDER <srcId> <dstId>                   a draggable button was dropped
    <- ADDR <text>                               the title editor was submitted
    <- SEEK <frac>                               the scrub bar was dragged/scrolled
    <- WAKE                                       the window was just un-hidden

**REGISTER carries its own non-default flags, in the SAME write.** The plugin
keeps no state for an unknown pid and `dropClient` erases the entry outright, so
a fresh registration starts at the plugin's defaults — `titleText` on above all.
Anything sent as a second write is therefore a window in which the bar draws
state the app has already declared it does not want. The plugin's reader drains
the socket and handles every complete line before returning to its poll, so one
`sendall` of "REGISTER …\nTITLETEXT 0\n" is one wakeup and the default state is
never on screen; no parser change was needed for this. `_flag_lines_locked()`
emits a line only for a flag this app has moved OFF the default, so an app that
wants the defaults sends exactly what it always did.

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
automatically). on_click/on_rclick/on_reorder/on_addr/on_seek/on_wake fire ON
THAT THREAD
— Qt apps should bounce them through a Signal (queued across threads) before
touching any UI.
"""
import os
import socket
import threading
import time


def _sock_path():
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(rt, "hyprvtb-buttons.sock")


class VtbClient:
    # Reconnect backoff. A flat 3s poll was the DOMINANT cause of goetia's
    # titlebar flashing its window title: a `hyprctl reload` plugin hot-swap
    # takes the socket away and brings a new one back within a few hundred ms,
    # but the client had already committed to a 3s sleep — and for every one of
    # those seconds the pid has no registration, so the plugin falls back to its
    # `titleText` default and the bar draws "goetia" on a mapped, visible
    # window. Measured at a flat 3000 ms; ~50 ms now. Ramps back to the same 3s
    # ceiling in ten attempts (~9 s), so a session with no plugin loaded at all
    # polls exactly as sparsely as it always did.
    _RETRY_MIN = 0.05
    _RETRY_MAX = 3.0

    def __init__(self, on_click=None, on_rclick=None, pid=None, on_reorder=None, on_addr=None,
                 on_wake=None, on_seek=None, buttons=None, title_edit=False, on_click_at=None):
        self._on_click = on_click
        self._on_click_at = on_click_at
        self._on_rclick = on_rclick
        self._on_reorder = on_reorder
        self._on_addr = on_addr
        self._on_wake = on_wake
        self._on_seek = on_seek
        self._pid = pid or os.getpid()
        self._lock = threading.Lock()
        self._sock = None          # guarded by _lock
        # `buttons` + `title_edit` are the born-correct seed: an app whose chrome
        # is NOT the plugin's default (surfer's address bar) stages it here, BEFORE
        # the I/O thread starts, so the very first connect's REGISTER already
        # carries it in one write and the window can never map at the default bar
        # (the startup titlebar flash). Staging before `_thread.start()` also means
        # no standalone flag write can race ahead of that REGISTER.
        self._buttons = list(buttons) if buttons else []   # last set, resent on reconnect
        self._footer = ""
        self._footer_bottom = False
        self._title_edit = bool(title_edit)
        self._title_text = True    # the bar draws the window title unless told not to
        self._edit_seed = ""       # what the address editor opens with (empty == the title)
        self._loading = False
        self._playbar = None       # (shown, pos) or None if never set
        self._stop = False
        self._retry = self._RETRY_MIN
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ---- public API ----

    def set_buttons(self, buttons):
        """buttons: list of (id, label, state[, tooltip[, draggable]]) tuples or
        "-" separators. Replaces the whole set; call again on any change.

        An UNCHANGED set is not sent — the same guard `set_loading`,
        `set_playbar` and `set_footer_bottom` already have. REGISTER is the one
        verb the plugin does not deduplicate itself (`vtbIpc.cpp`
        `handleRegister` bumps `serial` unconditionally, while `handleFooter`
        returns early on identical text), and every bump makes every window's
        titlebar re-warm its glyphs and repaint. An app that re-sends its set on
        a redraw was paying for that; board sent its whole set twice at startup.
        The reconnect path calls `_send_register_locked` directly, so a
        re-register after the plugin restarts is unaffected.
        """
        with self._lock:
            new = list(buttons)
            if new == self._buttons:
                return
            self._buttons = new
            self._send_register_locked()

    def set_footer(self, text):
        with self._lock:
            if str(text) == self._footer:
                return
            self._footer = str(text)
            self._send_footer_locked()

    def set_footer_bottom(self, on):
        """Put the footer BELOW the scrub bar instead of above it (player's
        position readout, which belongs against its own track). Default off
        keeps viewer's order: readout under the buttons, track beneath it."""
        with self._lock:
            if bool(on) == self._footer_bottom:
                return
            self._footer_bottom = bool(on)
            self._send_footer_pos_locked()

    def set_title_edit(self, on):
        """Mark the title region an editable address bar (surfer)."""
        with self._lock:
            if bool(on) == self._title_edit:
                return
            self._title_edit = bool(on)
            self._send_title_edit_locked()

    def set_edit_seed(self, text):
        """Seed the address editor with `text` instead of the shown title.

        surfer shows the page title in the bar but must open the editor on the
        real URL. Empty restores the default (edit whatever the title shows)."""
        text = text or ""
        with self._lock:
            if text == self._edit_seed:
                return
            self._edit_seed = text
            self._send_edit_seed_locked()

    def set_title_text(self, on):
        """Draw the stacked window title in the bar at all? Default on.

        Off is for a program whose title is only its own name — the bar is for
        document/state identity (docs/DESIGN.md 12), and goetia has none to
        show. It leaves the xdg_toplevel title alone, so the taskbar and
        alt-tab still name the window; blanking `Window.title` instead does
        not work at all (Qt substitutes the application name)."""
        with self._lock:
            if bool(on) == self._title_text:
                return
            self._title_text = bool(on)
            self._send_title_text_locked()

    def set_loading(self, on):
        """Page loading? The plugin draws an animated spinner above the address
        bar while true (surfer)."""
        with self._lock:
            if bool(on) == self._loading:
                return
            self._loading = bool(on)
            self._send_loading_locked()

    def set_playbar(self, shown, pos=0.0):
        """Media scrub bar: when shown, the plugin draws a vertical progress
        track below the footer at fraction `pos` (0..1); dragging/scrolling it
        sends SEEK back (viewer's video). Hidden for still images."""
        state = (bool(shown), float(pos))
        with self._lock:
            if state == self._playbar:
                return
            self._playbar = state
            self._send_playbar_locked()

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
        self._send_lines_locked([line])

    def _send_lines_locked(self, lines):
        """ONE sendall for the whole batch — see the atomicity note in the
        module docstring. The plugin handles every complete line it can see
        before it polls again, so a batch sent this way cannot be observed
        half-applied."""
        if not self._sock or not lines:
            return
        try:
            self._sock.sendall("".join(ln + "\n" for ln in lines).encode())
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

    def _flag_lines_locked(self):
        """Only the flags this app has moved off the plugin's defaults.

        Empty for an app that wants the defaults, which is the whole safety
        property: bundling these with REGISTER must not start asserting a flag
        nobody asked for. Re-asserting one that is already set costs nothing
        either — every flag handler in `vtbIpc.cpp` returns early on an
        unchanged value WITHOUT bumping the IPC serial, so a re-register (which
        goetia does on every scroll) triggers no extra repaint.
        """
        out = []
        if not self._title_text:
            out.append("TITLETEXT 0")   # first, so it is the least deferrable
        if self._title_edit:
            out.append("TITLEEDIT 1")
        if self._edit_seed:
            out.append("EDITSEED " + self._edit_seed)
        if self._footer_bottom:
            out.append("FOOTERPOS 1")
        if self._footer:
            out.append("FOOTER " + self._footer)
        if self._loading:
            out.append("LOADING 1")
        if self._playbar is not None:
            shown, pos = self._playbar
            out.append("PLAYBAR %d %.5f" % (1 if shown else 0, pos))
        return out

    def _send_register_locked(self):
        # No buttons, nothing to send: the plugin learns a connection's pid only
        # FROM a REGISTER and drops every other verb until it has one, so the
        # flags would be discarded on their own anyway.
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
        self._send_lines_locked([f"REGISTER {self._pid} " + "|".join(parts)]
                                + self._flag_lines_locked())

    def _send_footer_locked(self):
        self._send_locked("FOOTER " + self._footer)

    def _send_footer_pos_locked(self):
        self._send_locked("FOOTERPOS " + ("1" if self._footer_bottom else "0"))

    def _send_title_edit_locked(self):
        self._send_locked("TITLEEDIT " + ("1" if self._title_edit else "0"))

    def _send_title_text_locked(self):
        self._send_locked("TITLETEXT " + ("1" if self._title_text else "0"))

    def _send_edit_seed_locked(self):
        self._send_locked("EDITSEED " + self._edit_seed)

    def _send_loading_locked(self):
        self._send_locked("LOADING " + ("1" if self._loading else "0"))

    def _send_playbar_locked(self):
        if self._playbar is None:
            return
        shown, pos = self._playbar
        self._send_locked("PLAYBAR %d %.5f" % (1 if shown else 0, pos))

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
                    time.sleep(self._retry)  # plugin not loaded (yet) — keep trying
                    self._retry = min(self._RETRY_MAX, self._retry * 1.6)
                    continue
                buf = b""
                self._retry = self._RETRY_MIN  # next outage starts fast again
                with self._lock:
                    self._sock = sock
                    # REGISTER *and* every non-default flag, one write. The
                    # plugin's dropClient erased this pid's entry when the old
                    # connection died, so a reconnect is a first registration
                    # as far as the compositor is concerned.
                    self._send_register_locked()
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
                    if text.startswith("CLICK ") and (self._on_click or self._on_click_at):
                        parts = text[6:].split(" ", 2)
                        if len(parts) == 3:
                            try:
                                if self._on_click_at:
                                    self._on_click_at(parts[0], float(parts[1]), float(parts[2]))
                                elif self._on_click:
                                    self._on_click(parts[0])
                            except ValueError:
                                pass
                        else:
                            if self._on_click:
                                self._on_click(text[6:])
                    elif text.startswith("RCLICK ") and self._on_rclick:
                        parts = text[7:].split(" ", 2)
                        if len(parts) == 3:
                            try:
                                self._on_rclick(parts[0], float(parts[1]), float(parts[2]))
                            except ValueError:
                                pass
                    elif text.startswith("REORDER ") and self._on_reorder:
                        rest = text[8:].split(" ", 1)
                        if len(rest) == 2:
                            self._on_reorder(rest[0], rest[1])
                    elif text.startswith("ADDR ") and self._on_addr:
                        self._on_addr(text[5:])
                    elif text.startswith("SEEK ") and self._on_seek:
                        try:
                            self._on_seek(float(text[5:]))
                        except ValueError:
                            pass
                    elif text == "WAKE" and self._on_wake:
                        self._on_wake()
                except Exception:
                    pass  # a handler bug must not kill the reader


# ---- animated close -------------------------------------------------------
# Quitting on a key (viewer's `q`, Escape) is not the same thing as clicking the
# titlebar's [x]: `Qt.quit()` tears the surface down and all the compositor has
# left to animate is a fade of the last frame, where the [x] rolls the window up
# into its bar first. This asks hyprvtb to run that same close on OUR window;
# the plugin's sendClose() then arrives as an ordinary window-close event, so
# the app still quits through whatever it already does on `closing`.
#
# Straight down Hyprland's own control socket rather than through `hyprctl`: no
# subprocess on the quit path, and nothing to resolve on a PATH that a .desktop
# launch may not carry. The reply is the plugin's answer — "ok" means it took
# the close, anything else (no plugin, an ambiguous pid, no compositor at all)
# means it did not, and the caller must quit itself. It cannot hit the wrong
# window: the request names our pid, and the plugin refuses a pid it cannot
# resolve to exactly one window.

def _hypr_socket_path():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        return None
    rt = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(rt, "hypr", sig, ".socket.sock")


def close_animated(pid=None, timeout=0.5):
    """Ask hyprvtb to close this app's window with the titlebar's animation.

    True if the compositor took it (quit on the close event that follows),
    False if it did not (quit now — never leave the window there because the
    animation was unavailable). Never raises."""
    path = _hypr_socket_path()
    if not path:
        return False
    req = b"/eval hl.plugin.hyprvtb.close_pid(%d)" % (pid or os.getpid())
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect(path)
            s.sendall(req)
            return s.recv(256).strip() == b"ok"
        finally:
            s.close()
    except OSError:
        return False
