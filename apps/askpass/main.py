#!/usr/bin/env python3
"""askpass — the desktop's own `SUDO_ASKPASS` password dialog.

Replaces ksshaskpass, which drew a stock Plasma dialog: it inherited whatever
KDE colour scheme the machine happened to have, so it rendered dark-ish on `top`
and LIGHT on book (Fedora Asahi, no Plasma theme of ours). This one owns every
pixel — frame, banner, field, buttons — and takes its colours from the same live
wallpaper palette the panel and the other apps use, so both hosts look identical
and nothing depends on Plasma being installed at all.

THE PASSWORD PATH, which is the whole point of this program:

    QML TextInput (echoMode Password)  ->  Sudo.accept(text)  ->  stdout  ->  sudo

and nowhere else. It is never put in argv, never written to a file, never
logged, never passed through a shell variable (the wrapper in
`home/prog/askpass.nix` `exec`s this with stdout inherited straight from sudo's
pipe). stdout carries the password and NOTHING else — every diagnostic goes to
stderr.

FAIL CLOSED, and exit codes the wrapper depends on:

    0   password written to stdout (user pressed OK / Enter)
    1   user cancelled, or the window was closed  -> no output at all
    3   could not display the dialog (import/QML/GL failure)

3 is distinct on purpose: `sudo -A` is load-bearing infrastructure here (agents
run root commands non-interactively through it), so the wrapper falls back to
ksshaskpass on 3 rather than leaving the machine with no way to authenticate.
1 must never trigger that fallback — a cancel is a decision, not a failure.

The Wayland app-id is `vista-askpass`, which two other things key off:
  * the `askpass-dim` window rule in hypr-files/hyprland.lua (dim_around,
    centre, pin), and
  * Askpass.qml in the Quickshell panel, which dims the BAR while this window
    exists — the compositor's dim_around only covers the window pass, so the
    layer-shell panel above it would otherwise stay bright.
Renaming the app-id means changing all three.
"""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
QML = HERE / "qml"

# Anything that goes wrong before the dialog is on screen is exit 3 ("could not
# display"), which the wrapper answers by falling back to ksshaskpass. Importing
# PySide6 is the realistic failure — on book it comes from Fedora's
# python3-pyside6, which an OS upgrade can break independently of this repo.
try:
    from PySide6.QtCore import QObject, Slot, QUrl, QFileSystemWatcher, Signal, Property
    from PySide6.QtGui import QGuiApplication, QColor
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
except Exception as exc:  # noqa: BLE001 - any import failure at all
    print(f"askpass: cannot load PySide6: {exc}", file=sys.stderr)
    sys.exit(3)


# The panel's palette file, rewritten by wal-set.sh between the wal markers.
# Same source of truth filer/viewer/player parse — see viewer/main.py.
PANEL_THEME = Path.home() / ".config" / "quickshell" / "Theme.qml"
PALETTE_KEYS = ["bg", "bgAlt", "border", "accent", "dim", "text", "textDim",
                "highlight", "ok", "warn", "crit", "info"]
PALETTE_DEFAULTS = {
    "bg": "#000000", "bgAlt": "#120b08", "border": "#382216", "accent": "#cc4400",
    "dim": "#54382a", "text": "#cc4400", "textDim": "#8c5438", "highlight": "#21140d",
    "ok": "#e08e65", "warn": "#b86237", "crit": "#fa5c0c", "info": "#ad7457",
}


class Palette(QObject):
    """The live wallpaper palette, parsed from the panel's Theme.qml.

    Deliberately NO QFileSystemWatcher rescan loop beyond the plain one the
    other apps use: this process lives for seconds, not hours. It is kept only
    so a wallpaper recolour mid-prompt does not leave a stale frame.
    """

    changed = Signal()

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self._path = str(path)
        self._colors = dict(PALETTE_DEFAULTS)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        if os.path.exists(self._path):
            self._watcher.addPath(self._path)
        self._load()

    def _on_change(self, _):
        if os.path.exists(self._path) and self._path not in self._watcher.files():
            self._watcher.addPath(self._path)
        self._load()

    def _load(self):
        try:
            txt = open(self._path, encoding="utf-8").read()
        except OSError:
            return
        colors = dict(self._colors)
        for m in re.finditer(r'property\s+color\s+(\w+)\s*:\s*"(#[0-9a-fA-F]{3,8})"', txt):
            name, val = m.group(1), m.group(2)
            if name in PALETTE_KEYS:
                colors[name] = val
        if colors != self._colors:
            self._colors = colors
            self.changed.emit()

    def _c(self, k):
        return QColor(self._colors.get(k, PALETTE_DEFAULTS[k]))

    @Property(QColor, notify=changed)
    def bg(self): return self._c("bg")
    @Property(QColor, notify=changed)
    def bgAlt(self): return self._c("bgAlt")
    @Property(QColor, notify=changed)
    def border(self): return self._c("border")
    @Property(QColor, notify=changed)
    def accent(self): return self._c("accent")
    @Property(QColor, notify=changed)
    def dim(self): return self._c("dim")
    @Property(QColor, notify=changed)
    def text(self): return self._c("text")
    @Property(QColor, notify=changed)
    def textDim(self): return self._c("textDim")
    @Property(QColor, notify=changed)
    def highlight(self): return self._c("highlight")
    @Property(QColor, notify=changed)
    def ok(self): return self._c("ok")
    @Property(QColor, notify=changed)
    def warn(self): return self._c("warn")
    @Property(QColor, notify=changed)
    def crit(self): return self._c("crit")
    @Property(QColor, notify=changed)
    def info(self): return self._c("info")


def sanitize(text, limit=240):
    """Make caller-supplied text safe to render on a password prompt.

    Both strings this dialog displays are UNTRUSTED: sudo's prompt is argv[1],
    and the reason is $SUDO_ASKPASS_REASON, which any caller can set to
    anything. A password dialog whose body text is attacker-controlled is a
    phishing surface, so:

      * control characters (C0 and C1) are dropped, and newlines/tabs collapse
        into single spaces — nothing can escape its line, fake a blank region,
        or push the real chrome off the window,
      * the length is clamped, so nothing can grow the dialog or shove the
        password field off-screen,
      * "..." not the ellipsis glyph, because the pixel font has no "…" and one
        missing glyph re-renders the whole line in a fallback face.

    The remaining half of the defence is in QML: PixelText sets
    `textFormat: Text.PlainText`, so markup is shown, never interpreted.
    """
    if not text:
        return ""
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\n\r\t":
            out.append(" ")
        elif o < 0x20 or 0x7F <= o <= 0x9F:
            continue     # control characters, including the C1 block
        else:
            out.append(ch)
    flat = " ".join("".join(out).split())
    if len(flat) > limit:
        flat = flat[:limit - 3].rstrip() + "..."
    return flat


class Sudo(QObject):
    """The only route out of the QML engine.

    `accept` writes the secret to fd 1 and terminates immediately; `cancel`
    terminates with 1 having written nothing. Both use os._exit after the write
    so no interpreter teardown, atexit hook or Qt destructor can run afterwards
    and put anything else on stdout.
    """

    @Slot(str)
    def accept(self, password):
        try:
            # os.write on the raw fd: no buffering layer keeps a second copy,
            # and no encoding surprises. sudo strips the trailing newline.
            data = (password + "\n").encode("utf-8")
            n = 0
            while n < len(data):
                n += os.write(1, data[n:])
        except OSError as exc:
            print(f"askpass: could not write password: {exc}", file=sys.stderr)
            os._exit(1)          # fail closed: no password, and NOT a fallback
        os._exit(0)

    @Slot()
    def cancel(self):
        os._exit(1)


def main():
    app = QGuiApplication(sys.argv)
    # Both are set: Qt derives the Wayland app_id from desktopFileName, falling
    # back to applicationName. The hyprland window rule and the panel's
    # Askpass.qml both match this exact string.
    app.setApplicationName("vista-askpass")
    app.setDesktopFileName("vista-askpass")

    # sudo passes its prompt as argv[1] ("[sudo] password for lam:" or
    # $SUDO_PROMPT). It is a prompt, not a secret; still, it is only ever shown,
    # never echoed to stdout — and it is untrusted, so it goes through sanitize.
    prompt = sanitize(sys.argv[1] if len(sys.argv) > 1 else "", limit=120)
    if not prompt:
        prompt = f"[sudo] password for {os.environ.get('USER', 'user')}:"

    # WHY root is being asked for, supplied by whoever is running sudo:
    #
    #     SUDO_ASKPASS_REASON="rebuilding the flake" sudo -A nixos-rebuild switch
    #
    # The caller states it; this dialog never invents one. Unset means unset —
    # the panel says so plainly rather than guessing or going blank, because a
    # prompt that fabricates a justification for its own privilege request is
    # worse than one that admits it does not know.
    reason = sanitize(os.environ.get("SUDO_ASKPASS_REASON", ""))

    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()

    palette = Palette(PANEL_THEME)
    sudo = Sudo()
    ctx.setContextProperty("WalPalette", palette)
    ctx.setContextProperty("Sudo", sudo)
    ctx.setContextProperty("startPrompt", prompt)
    ctx.setContextProperty("startReason", reason)

    theme_comp = QQmlComponent(engine, QUrl.fromLocalFile(str(QML / "theme" / "Theme.qml")))
    theme = theme_comp.create()
    if theme is None:
        print("askpass: Theme.qml failed:\n" + theme_comp.errorString(), file=sys.stderr)
        sys.exit(3)
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    engine.load(QUrl.fromLocalFile(str(QML / "Main.qml")))
    if not engine.rootObjects():
        print("askpass: Main.qml failed to load", file=sys.stderr)
        sys.exit(3)

    # Reached only if the event loop ends without accept/cancel having called
    # os._exit — i.e. the window went away. Treat as a cancel, never a fallback.
    app.exec()
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - never leak a traceback to stdout
        print(f"askpass: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(3)
