#!/usr/bin/env python3
"""painter's UI harness — offscreen, no window on anyone's screen, no backend.

It loads the REAL `qml/Main.qml` under QT_QPA_PLATFORM=offscreen against a
synthetic model root, and answers the questions a screenshot would otherwise be
needed for:

  1. the window loads with zero QML warnings (a binding loop or a missing
     property shows as *nothing at all* on screen, so it fails the run);
  2. a text box takes a click ANYWHERE in it — the prompt boxes' empty space
     below the last line, and the padding strips of a numeric box;
  3. the model panel collapses like every other panel, and says what is
     selected while collapsed;
  4. the output pane is present and usable at every window width, with a grid
     cell that fits the pane it is in;
  5. aspect (two integers) + MP produce the pixels shown in the header and the
     pixels actually submitted — one number, three places;
  6. a dropdown opens in the scene overlay, inside the window, above everything;
  7. every control in the left column reaches the submitted job;
  8. a batch that finishes behind an unfocused or rolled-up window toasts —
     once, with its thumbnail — and is silent when he is looking at it.

Run it with painter's own Qt env (book has PySide6 from Fedora):

    /usr/bin/python3 apps/painter/tools/ui-test.py

`PAINTER_MODELS` is redirected at a scratch root and the backend is never
contacted: `unit_cmd` is neutered, the client is stubbed, and `_object_info` is
faked, so this cannot start ComfyUI on top or touch the live tunnel.
"""
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
import time

Q_ARG = None  # bound in build(), once PySide6 is importable

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # no way back to his session
os.environ.pop("DISPLAY", None)
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
# WHICH ROOF THIS HARNESS RENDERS, pinned rather than inherited. `is_plasma()`
# reads XDG_CURRENT_DESKTOP, so a run started from a Plasma session laid out the
# QML with `plasma: true` — a 0-height QueueBar, since that face's status bar is
# a real QStatusBar — and the queue-strip checks below failed on the session the
# run happened to be launched from. The Hyprland roof is the one this file's
# checks describe; the Plasma face's own chrome is QtWidgets and is not built
# here at all. `DESK_SESSION=plasma` still forces the other look by hand.
os.environ.setdefault("DESK_SESSION", "hypr")
os.environ.pop("PAINTER_BACKEND_SSH", None)   # never drive top's systemd
os.environ.pop("PAINTER_COMFY_URL", None)

PAINTER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(PAINTER)
sys.path.insert(0, PAINTER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

P_LIVE = "live://generating"   # main.py LIVE_PATH, spelled out so a rename shows up here

FAILS = []
WARNINGS = []
OPENED = []          # what the app would have launched (see _NoLaunch in build)
RAN = []             # ...and what it would have run (wl-copy / ffmpeg)


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def spin(ms=120):
    from PySide6.QtGui import QGuiApplication
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def prop(obj, name):
    """A QML property, with a `var` unwrapped — a `property var` reaches PySide
    as a QJSValue, which has no length and compares equal to nothing."""
    v = obj.property(name)
    return v.toVariant() if hasattr(v, "toVariant") else v


def hasattr_qml(item, method):
    """Whether a QML item exposes `method` as an invokable — used to assert that
    a control that WAS there is gone, rather than trusting the source."""
    mo = item.metaObject()
    return any(mo.method(i).name().data().decode() == method
               for i in range(mo.methodCount()))


def find(root, type_name, pred=None):
    """First item whose QML type starts with `type_name`, depth-first."""
    for it in walk(root):
        n = it.metaObject().className()
        if n.startswith(type_name) and (pred is None or pred(it)):
            return it
    return None


def find_all(root, type_name, pred=None):
    out = []
    for it in walk(root):
        n = it.metaObject().className()
        if n.startswith(type_name) and (pred is None or pred(it)):
            out.append(it)
    return out


def walk(item):
    yield item
    for c in item.childItems() if hasattr(item, "childItems") else []:
        yield from walk(c)


def scene_rect(item):
    from PySide6.QtCore import QPointF
    p = item.mapToScene(QPointF(0, 0))
    return (p.x(), p.y(), item.width(), item.height())


def doubleclick(win, item, dx=None, dy=None):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    p = item.mapToScene(QPointF(item.width() / 2 if dx is None else dx,
                                item.height() / 2 if dy is None else dy))
    QTest.mouseDClick(win, Qt.LeftButton, Qt.NoModifier, QPoint(int(p.x()), int(p.y())))
    spin(60)


def click(win, item, dx=None, dy=None, button=None):
    """A real mouse click at a point INSIDE `item`, in window coordinates."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    p = item.mapToScene(QPointF(item.width() / 2 if dx is None else dx,
                                item.height() / 2 if dy is None else dy))
    QTest.mouseClick(win, button or Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(p.x()), int(p.y())))
    spin(60)


def wheel(win, item, dx, dy, notches):
    """A real wheel event over a point inside `item`."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QGuiApplication, QWheelEvent
    p = item.mapToScene(QPointF(dx, dy))
    ev = QWheelEvent(QPointF(p.x(), p.y()), win.mapToGlobal(QPoint(int(p.x()), int(p.y()))),
                     QPoint(0, 0), QPoint(0, int(120 * notches)),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QGuiApplication.sendEvent(win, ev)
    spin(60)


def drag(win, item, x1, y1, x2, y2, button=None):
    """Press, move, release — a real drag inside `item`, in window coordinates."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    b = button or Qt.LeftButton
    a = item.mapToScene(QPointF(x1, y1))
    z = item.mapToScene(QPointF(x2, y2))
    QTest.mousePress(win, b, Qt.NoModifier, QPoint(int(a.x()), int(a.y())))
    steps = 4
    for i in range(1, steps + 1):
        QTest.mouseMove(win, QPoint(int(a.x() + (z.x() - a.x()) * i / steps),
                                    int(a.y() + (z.y() - a.y()) * i / steps)))
        spin(20)
    QTest.mouseRelease(win, b, Qt.NoModifier, QPoint(int(z.x()), int(z.y())))
    spin(60)


def menu_pick(win, item, label, dx=None, dy=None):
    """Right-click `item`, then click the row called `label` — the real path.

    Everything a right-click menu does to a text box goes through here, because
    invoking the editor's own method instead skips the part that broke: opening
    the menu moves the active focus off the editor.
    """
    from PySide6.QtCore import Qt
    click(win, item, dx=dx, dy=dy, button=Qt.RightButton)
    menu = find(win.contentItem(), "CtxMenu")
    if menu is None or not menu.isVisible():
        FAILS.append("the context menu opened on " + label)
        print("FAIL  the context menu opened on " + label)
        return None
    row = find(menu, "PixelText", pred=lambda it: it.property("text") == label)
    if row is None:
        FAILS.append("the context menu offers " + label)
        print("FAIL  the context menu offers " + label)
        return None
    click(win, row)
    return menu


def key(win, k, mods=None, text=""):
    """One key, delivered to the WINDOW — never to the item under test.

    A window-level `Shortcut` sees a key before any focused item's own handler
    (that is how Escape was once taken away from the dropdown), so a check that
    called the editor's methods directly would pass while the keyboard did
    nothing.
    """
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QGuiApplication, QKeyEvent
    mods = Qt.NoModifier if mods is None else mods
    for typ in (QEvent.KeyPress, QEvent.KeyRelease):
        QGuiApplication.sendEvent(win, QKeyEvent(typ, k, mods, text))
    spin(60)


# --------------------------------------------------------------- fake models
def fake_models(root):
    """A model root that fingerprint.py can actually parse.

    Two safetensors files with real headers (8-byte little-endian length + JSON),
    so the registry produces entries and the list has rows — without copying a
    single weight or needing top.
    """
    d = os.path.join(root, "unet")
    os.makedirs(d, exist_ok=True)
    for name, keys in (("alpha-model.safetensors", ["double_blocks.0.img_attn.qkv.weight"]),
                       ("beta-model.safetensors", ["model.diffusion_model.input_blocks.0.0.weight"])):
        write_safetensors(os.path.join(d, name), {k: [16, 16] for k in keys})
    return root


def write_safetensors(path, keys):
    """A parseable safetensors header and nothing else — `keys` is name -> shape."""
    hdr = {k: {"dtype": "BF16", "shape": list(shape), "data_offsets": [0, 512]}
           for k, shape in keys.items()}
    hdr["__metadata__"] = {"format": "pt"}
    blob = json.dumps(hdr).encode()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<Q", len(blob)))
        fh.write(blob)
        fh.write(b"\0" * 512)


# A whole video family, headers only: the diffusion model (recognised by its two
# patch projectors), the Qwen3-VL encoder its `hidden` picks out, and the two
# VAEs the family names outright. Written and then REMOVED by test_video,
# because a fully-paired model sorts to the top of the list and would otherwise
# become the default selection for every test after it.
VIDEO_FAKES = {
    "unet/mini-video.safetensors": {"video_patch_proj.weight": [16, 96],
                                    "audio_patch_proj.weight": [16, 32],
                                    "blocks.0.attn.qkv_proj.weight": [16, 16]},
    "text_encoders/fake-qwen3vl.safetensors": {
        "model.visual.deepstack_merger_list.0.norm.weight": [16],
        "model.layers.0.post_attention_layernorm.weight": [5120]},
    # Both video decoders, so the family's `prefer` order is what decides which
    # one a paired video model gets rather than which one happens to exist.
    "vae/minimax_h3_video_vae_int8_convrot.safetensors": {
        "decoder.conv_in.weight": [8, 16, 3, 3]},
    "vae/minimax_h3_video_vae_fp16.safetensors": {"decoder.conv_in.weight": [8, 16, 3, 3]},
    "vae/minimax_h3_audio_vae_fp32.safetensors": {"decoder.conv_in.weight": [8, 16, 3, 3]},
}


def fake_png(path, params):
    """A real 1x1 PNG carrying a painter parameter chunk, so the gallery's
    `paramsAt` reads it exactly as it reads a generated image."""
    import zlib
    import pngmeta

    def chunk(t, body):
        return (struct.pack(">I", len(body)) + t + body
                + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF))

    raw = zlib.compress(b"\x00\x00\x00\x00")
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", raw) + chunk(b"IEND", b""))
    png = pngmeta.upsert_text(png, pngmeta.describe(params))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)
    return path


# ------------------------------------------------------------------ the window
def build_window(engine_only=False):
    """A second window on the same prefs, for the restore test."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    import main as P

    ctl = P.Painter()
    ctl._unit_poll.stop()
    ctl._probe.stop()
    engine = QQmlApplicationEngine()
    if os.environ.get("DESK_SESSION") == "plasma":
        from kdeshell import select_plasma_files
        select_plasma_files(engine)
    ctl.preview = P.LivePreview()
    engine.addImageProvider("livepreview", ctl.preview)
    ctx = engine.rootContext()
    keep = (P.Palette(P.PANEL_THEME), _DESKSTYLE(parent=engine), P.Prefs(),
            ctl, _STUBBAR(), P.SpellCheck(), P.Tags())
    for name, obj in (("WalPalette", keep[0]), ("DeskStyle", keep[1]),
                      ("Prefs", keep[2]), ("App", ctl), ("Models", ctl.models),
                      ("Loras", ctl.loras), ("LoraChoices", ctl.choices),
                      ("Gallery", ctl.gallery), ("Titlebar", keep[4]),
                      ("Spell", keep[5]), ("Tags", keep[6]),
                      ("Theme", _THEME[0])):
        ctx.setContextProperty(name, obj)
    engine.warnings.connect(lambda ws: WARNINGS.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(os.path.join(PAINTER, "qml/Main.qml")))
    win = engine.rootObjects()[0]
    # THE APP IS NOT THE WINDOW ANY MORE. `Main.qml` is a twenty-line `Window`
    # wrapper and `Root.qml` — an Item inside it — is the app, because a Plasma
    # session hosts that same Item in a QQuickWidget instead (apps/AGENTS.md,
    # pylib/kdeshell.py). So every property and every invokable this harness
    # reaches for is on `APP`, and only geometry and hit-testing are on `win`.
    app_root = find(win.contentItem(), "Root")
    if app_root is None:
        raise SystemExit("ui-test: no Root item under the window")
    ctl.rescan()
    spin(400)
    return engine, win, app_root, ctl, keep


_DESKSTYLE = None
_STUBBAR = None
_THEME = [None]
APP = None      # the Root item — see build()


def build(tmp):
    from PySide6.QtCore import QObject, QUrl, Signal, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
    import PySide6.QtQuick  # noqa: F401  (registers the QQuickItem converter)
    from deskstyle import DeskStyle
    import main as P

    global Q_ARG
    from PySide6.QtCore import Q_ARG as _QARG
    Q_ARG = _QARG

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())

    class StubTitlebar(QObject):
        # The signals matter as much as the slots: a `Connections` whose target
        # lacks the signal it handles emits a QML warning, and this run fails on
        # warnings — so a stub without them would fail Main.qml for the stub's
        # own omission.
        clicked = Signal(str)

        @Slot("QVariantList")
        def setButtons(self, _b): pass

        @Slot(str)
        def setFooter(self, _s): pass

        @Slot(bool)
        def setLoading(self, _b): pass

    # Never reach the backend: no systemctl anywhere, local or over ssh.
    P.unit_cmd = lambda *verb: ["true"]

    # ...and NEVER LAUNCH ANYTHING. A left-click in the gallery opens the output
    # in viewer, which is a window on HIS screen — this harness spawned two
    # before that click was even the behaviour under test. Popen is recorded,
    # not run; OPENED is what the test reads back.
    class _NoLaunch:
        # `dragUriList` catches this by name off the (patched) module.
        SubprocessError = Exception

        @staticmethod
        def Popen(argv, *a, **k):
            OPENED.append(list(argv))
            return None

        @staticmethod
        def run(argv, *a, **k):
            """The one SYNCHRONOUS call in the app — muting a clip for a drag.

            Recorded rather than run, and it leaves a file where ffmpeg would
            have, so the payload the drag hands over is the copy and not the
            fallback."""
            RAN.append(list(argv))
            if os.path.basename(argv[0]) == "ffmpeg" and len(argv) > 1:
                try:
                    with open(argv[-1], "wb") as fh:
                        fh.write(b"\0" * 32)
                except OSError:
                    pass

            class _Done:
                returncode = 0
            return _Done()
    P.subprocess = _NoLaunch

    # ...and no clipfile either: it forks a holder process that OWNS his
    # clipboard until something else replaces it (pylib/clipfile.py is exercised
    # for real, against a headless compositor, by pylib/tools/clipfile-test.sh).
    # RAN records what would have been run; everything else (systemctl, ffmpeg)
    # still goes through QProcess.
    real_async = P.Painter._run_async

    def recorded(self, argv, done=None):
        if any(os.path.basename(a) == "clipfile.py" for a in argv) \
           or os.path.basename(argv[0]) in ("wl-copy", "ffmpeg"):
            RAN.append(list(argv))
            if done:
                done(0, "")
            return None
        return real_async(self, argv, done)
    P.Painter._run_async = recorded
    ctl = P.Painter()
    ctl._unit_poll.stop()
    ctl._probe.stop()

    engine = QQmlApplicationEngine()
    if os.environ.get("DESK_SESSION") == "plasma":
        # Main.py installs this selector before loading Root.qml. Without it,
        # `DESK_SESSION=plasma` changed app policy but the harness silently
        # kept testing the pixel controls — exactly how the narrow native seed
        # box escaped the previous checks.
        from kdeshell import select_plasma_files
        select_plasma_files(engine)
    # The live-preview provider, as main() installs it: without it the preview
    # pane's Image warns "Invalid image provider" the moment a frame arrives,
    # and a QML warning fails this run.
    ctl.preview = P.LivePreview()
    engine.addImageProvider("livepreview", ctl.preview)
    ctx = engine.rootContext()
    keep = (P.Palette(P.PANEL_THEME), DeskStyle(parent=engine), P.Prefs(),
            ctl, StubTitlebar(), P.SpellCheck(), P.Tags())
    ctx.setContextProperty("WalPalette", keep[0])
    ctx.setContextProperty("DeskStyle", keep[1])
    ctx.setContextProperty("Prefs", keep[2])
    ctx.setContextProperty("App", ctl)
    ctx.setContextProperty("Models", ctl.models)
    ctx.setContextProperty("Loras", ctl.loras)
    ctx.setContextProperty("LoraChoices", ctl.choices)
    ctx.setContextProperty("Gallery", ctl.gallery)
    ctx.setContextProperty("Titlebar", keep[4])
    ctx.setContextProperty("Spell", keep[5])
    ctx.setContextProperty("Tags", keep[6])
    engine.warnings.connect(lambda ws: WARNINGS.extend(w.toString() for w in ws))

    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(PAINTER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed:\n" + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)

    global _DESKSTYLE, _STUBBAR
    _DESKSTYLE, _STUBBAR = DeskStyle, StubTitlebar
    _THEME[0] = theme

    engine.load(QUrl.fromLocalFile(os.path.join(PAINTER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        for w in WARNINGS:
            print("  " + w)
        raise SystemExit("Main.qml failed to load")
    win = roots[0]
    # The app is the Root ITEM inside that window, not the window — see
    # build_window() for why, and `APP` for what the tests reach through.
    global APP
    APP = find(win.contentItem(), "Root")
    if APP is None:
        raise SystemExit("ui-test: no Root item under the window")
    win.setWidth(1280)
    win.setHeight(900)
    spin(400)
    # The app only scans models once the backend's /object_info lands, so with no
    # backend the list would be empty and half of this would silently SKIP.
    ctl.rescan()
    spin(200)
    return app, engine, win, ctl, keep + (theme,)


# ------------------------------------------------------------------- the tests
def test_text_boxes(win, ctl):
    """Click anywhere in a box and you are typing in it — and the keys work."""
    from PySide6.QtCore import Qt
    content = win.contentItem()
    boxes = find_all(content, "PromptBox")
    check("both prompt boxes exist", len(boxes) == 2, len(boxes))
    if not boxes:
        return
    box = boxes[0]
    edit = find(box, "QQuickTextEdit")
    flick = find(box, "KineticFlickable")
    check("the editor fills the box, not just its text",
          edit.height() >= flick.height() - 0.5,
          (edit.height(), flick.height()))

    # A click 6px from the BOTTOM of a 130px box holding no text: the old
    # TextEdit was ~16px tall, so this landed on nothing.
    # -14, not -6: the bottom edge of the box is now the resize grip, and a
    # click there is a drag handle, not a caret.
    click(win, box, dx=box.width() / 2, dy=box.height() - 14)
    check("a click low in an empty prompt box starts editing",
          edit.property("activeFocus") is True)

    # ...and with text in it, the caret lands at the end rather than nowhere.
    gen = prop(APP, "gen"); gen["positive"] = "one two three"
    APP.setProperty("gen", gen)
    spin(120)
    check("the model's text reaches the editor", edit.property("text") == "one two three",
          edit.property("text"))
    edit.setProperty("cursorPosition", 0)
    click(win, box, dx=box.width() - 40, dy=box.height() - 14)
    check("...and the caret goes to the end of the text",
          edit.property("cursorPosition") == len("one two three"),
          edit.property("cursorPosition"))

    # --- the keys a text box owes you -------------------------------------
    # Ctrl+A then Backspace is how a prompt gets replaced, and a window-level
    # `Shortcut` sees a key BEFORE the focused item does (that is what took
    # Escape away from the dropdown once), so every one of these is checked at
    # the WINDOW rather than by calling the editor's own methods.
    edit.forceActiveFocus()
    spin(60)
    key(win, Qt.Key_A, Qt.ControlModifier, "a")
    check("Ctrl+A selects the whole prompt",
          edit.property("selectedText") == "one two three",
          (edit.property("selectionStart"), edit.property("selectionEnd")))
    key(win, Qt.Key_Backspace)
    check("...and Backspace deletes the selection",
          edit.property("text") == "", edit.property("text"))
    check("...and the model hears about it",
          prop(APP, "gen").get("positive") == "", prop(APP, "gen").get("positive"))
    key(win, Qt.Key_X, Qt.NoModifier, "x")
    key(win, Qt.Key_Y, Qt.NoModifier, "y")
    check("typing after that still reaches the model",
          edit.property("text") == "xy" and prop(APP, "gen").get("positive") == "xy",
          (edit.property("text"), prop(APP, "gen").get("positive")))
    key(win, Qt.Key_Backspace)
    check("a plain Backspace deletes one character",
          edit.property("text") == "x", edit.property("text"))

    # The caret must take the prompt viewport with it when typing crosses its
    # bottom, both for a newline he enters and one produced by wrapping. A
    # TextEdit does not do this for an enclosing Flickable automatically.
    box.setProperty("boxHeight", 54)
    edit.setProperty("text", "one\ntwo\nthree")
    edit.setProperty("cursorPosition", len(edit.property("text")))
    edit.forceActiveFocus()
    spin(60)
    flick.setProperty("contentY", flick.property("originY"))
    key(win, Qt.Key_Return)
    key(win, Qt.Key_X, Qt.NoModifier, "x")
    spin(80)
    caret = edit.property("cursorRectangle")
    check("pressing Enter scrolls the new line into view",
          (flick.property("contentY") > flick.property("originY")
           and caret.bottom() <= flick.property("contentY") + flick.height() + 0.5),
          (flick.property("contentY"), caret.bottom(), flick.height()))

    edit.setProperty("text", "wrap " * 40)
    edit.setProperty("cursorPosition", len(edit.property("text")))
    spin(60)
    flick.setProperty("contentY", flick.property("originY"))
    key(win, Qt.Key_X, Qt.NoModifier, "x")
    spin(80)
    caret = edit.property("cursorRectangle")
    check("typing on a wrapped line scrolls it into view",
          (flick.property("contentY") > flick.property("originY")
           and caret.bottom() <= flick.property("contentY") + flick.height() + 0.5),
          (flick.property("contentY"), caret.bottom(), flick.height()))
    box.setProperty("boxHeight", 130)
    spin(60)

    # Select-all is also a menu item, and it must mean the same thing.
    edit.setProperty("text", "one two three")
    spin(60)
    edit.metaObject().invokeMethod(edit, "selectAll")
    spin(60)
    check("the menu's select all agrees with the key",
          edit.property("selectedText") == "one two three",
          edit.property("selectedText"))
    key(win, Qt.Key_Backspace)
    check("...and Backspace clears that selection too", edit.property("text") == "",
          edit.property("text"))

    # ...and that is NOT the same test as picking the row. Calling `selectAll()`
    # on an editor that still has focus is the one path that always worked; the
    # real one goes through `CtxMenu`, which takes the focus to its own sink to
    # get Escape. Selecting into an editor the keyboard is no longer pointed at
    # left the text looking selected and Backspace doing nothing — the whole bug.
    edit.setProperty("text", "one two three")
    spin(60)
    menu_pick(win, box, "select all")
    check("the menu row selects the whole prompt",
          edit.property("selectedText") == "one two three",
          edit.property("selectedText"))
    check("...and hands the keyboard back to the editor",
          edit.property("activeFocus") is True)
    key(win, Qt.Key_Backspace)
    check("...so Backspace after the MENU's select all clears it",
          edit.property("text") == "", edit.property("text"))

    # Every other row on that menu edits the same document, so each one owes the
    # keyboard back too — typing after `paste` must land in the box.
    edit.setProperty("text", "one two")
    spin(60)
    edit.metaObject().invokeMethod(edit, "selectAll")
    menu_pick(win, box, "copy")
    check("copy leaves the editor focused", edit.property("activeFocus") is True)
    key(win, Qt.Key_Z, Qt.NoModifier, "z")
    check("...and the next keystroke goes into the box",
          edit.property("text") == "z", edit.property("text"))
    # `cut` is where a dropped selection SHOWS: a TextEdit deselects when it
    # loses focus to the menu, so the row ran against nothing and the text
    # stayed put (hence `persistentSelection` on the editor).
    edit.setProperty("text", "cut me")
    spin(60)
    edit.metaObject().invokeMethod(edit, "selectAll")
    menu_pick(win, box, "cut")
    check("the menu's cut takes the selection with it",
          edit.property("text") == "", edit.property("text"))

    # The NEGATIVE box is a second editor, and the keys are not the positive
    # one's by accident.
    nedit = find(boxes[1], "QQuickTextEdit")
    nedit.forceActiveFocus()
    spin(60)
    nedit.setProperty("text", "no rain")
    spin(80)
    key(win, Qt.Key_A, Qt.ControlModifier, "a")
    key(win, Qt.Key_Backspace)
    check("the negative box takes the same two keys",
          nedit.property("text") == "" and prop(APP, "gen").get("negative") == "",
          (nedit.property("text"), prop(APP, "gen").get("negative")))
    edit.forceActiveFocus()
    spin(60)

    # --- the resize grip, in BOTH directions ------------------------------
    # A panel used to size itself from `childrenRect`, which only ever grows
    # once a child is hidden — so with the negative box gone (video, edit) a
    # SHRUNK prompt box left a blank the height of the drag. Measured here as
    # the panel tracking the box down, not just up.
    editor = find(content, "PromptEditor")
    box.setProperty("boxHeight", 300)
    spin(120)
    tall = editor.height()
    box.setProperty("boxHeight", 120)
    spin(120)
    check("the prompt panel shrinks with its box, not just grows",
          editor.height() <= tall - 175, (tall, editor.height()))
    # (the case that was actually broken — the negative box hidden — is checked
    # in test_video, where it is hidden by the real binding rather than by
    # writing over it here.)
    box.setProperty("boxHeight", 130)
    spin(120)

    # A numeric box: the 5px padding strip used to be dead.
    # A VISIBLE one: the left column carries panels that only a video family
    # reveals, and an item inside a hidden panel still answers to `find` —
    # clicking one lands wherever its stale geometry says, which was three
    # unrelated failures and a model selected by a click nobody aimed.
    sp = find(content, "Spin", pred=lambda it: it.isVisible())
    inp = find(sp, "QQuickTextInput")
    inp.setProperty("focus", False)
    spin(60)
    click(win, sp, dx=2, dy=sp.height() / 2)
    check("a click on a numeric box's padding starts editing",
          inp.property("activeFocus") is True)


def test_chrome(win, ctl):
    """The bits of furniture: the badge, the grips, the bars, the bottom strip."""
    content = win.contentItem()

    # The action table also feeds menus, whose separators must not turn into
    # empty dividers in hyprvtb's much smaller titlebar column.
    titlebar = ["-" if isinstance(a, str) else a["id"]
                for a in prop(APP, "tbButtons")]
    check("the titlebar has no orphan menu separators",
          titlebar == ["gen", "stop", "-", "p", "g", "pv", "-", "set"],
          titlebar)

    # A panel badge can be a filename, and it must not run out of its panel.
    panel = find(content, "ModelPicker")
    panel.setProperty("collapsed", True)
    was = win.width()
    win.setWidth(760)          # a narrow-ish column, where the name does not fit
    spin(150)
    badge = find_all(panel, "PixelText",
                     pred=lambda it: it.property("text") == ctl.property("selectedName"))
    check("the badge names the model", bool(badge), ctl.property("selectedName"))
    if badge:
        b = badge[0]
        # Metrics-honest: the harness runs under the LIVE font pick, and at
        # some family/size pairs the name simply fits at this width (Phenex@14
        # measured 193px in a 217px slot). The invariant is "never spills":
        # contained, and elided whenever the natural width would not fit.
        check("...and is elided inside the panel, not spilling out of it",
              b.x() + b.width() <= panel.width() + 0.5
              and (b.property("truncated") is True
                   or b.property("implicitWidth") <= b.width() + 0.5),
              (b.x(), b.width(), panel.width(), b.property("truncated"),
               b.property("implicitWidth")))
    win.setWidth(was)
    panel.setProperty("collapsed", False)
    spin(120)

    # The splitter is a drag target; the status bar is under it and must not be.
    bar = find(content, "QueueBar")
    split = [it for it in walk(content)
             if it.property("width") == APP.property("splitterW")
             and it.height() > 100]
    check("the splitter stops above the status bar",
          bool(split) and split[0].height() <= win.height() - bar.height() + 0.5,
          (split[0].height() if split else None, win.height(), bar.height()))

    # The bar's clock outlives the run that measured it. It used to be
    # `visible: App.busy`, so the one number the job had just produced went
    # away with the job and survived only in a toast that fades.
    def bar_texts():
        return [it.property("text") for it in find_all(bar, "PixelText")
                if it.isVisible()]

    def set_state(busy, start=0.0, last=0.0):
        ctl._busy, ctl._job_start, ctl._last_elapsed = busy, start, last
        ctl.busyChanged.emit()
        ctl.statusChanged.emit()
        spin(80)

    set_state(False)
    check("no clock before anything has run",
          not any(str(t).startswith("took") for t in bar_texts()), bar_texts())
    set_state(True, start=time.time() - 75)
    check("a running job shows a bare clock", "1:15" in bar_texts(), bar_texts())
    set_state(False, last=311.11)
    check("...and it stays put once the run is over, marked as settled",
          "took 5:11" in bar_texts(), bar_texts())
    set_state(False)

    # The panes swapped sides: results lead, controls trail.
    gal = find(content, "GalleryView")
    ctrl = find(content, "ModelPicker")
    check("the results are on the LEFT and the controls on the right",
          scene_rect(gal)[0] < scene_rect(ctrl)[0], (scene_rect(gal)[0], scene_rect(ctrl)[0]))

    # One scrollbar, and on the side whose content is unbounded.
    colFlick = find(content, "KineticFlickable",
                    pred=lambda it: find(it, "ModelPicker") is not None)
    grid = find(content, "KineticGridView")
    col = find(colFlick, "QQuickColumn")
    check("the parameter column has no scrollbar gutter",
          col is not None and abs(col.width() - colFlick.width()) < 0.5,
          (col.width() if col else None, colFlick.width()))
    check("...and the results grid has one", find(grid, "VScroll") is not None)

    # The preview viewport: off by default, toggled from the titlebar, dragged
    # taller, and sitting ABOVE the grid rather than over it.
    pv = find(content, "PreviewPane")
    check("the preview viewport starts closed", not pv.isVisible())
    APP.setProperty("showPreview", True)
    spin(150)
    check("...opens above the history",
          pv.isVisible() and scene_rect(pv)[1] + pv.height() <= scene_rect(grid)[1] + 1.5,
          (scene_rect(pv), scene_rect(grid)))
    h = pv.height()
    pv.setProperty("paneHeight", int(h + 60))
    spin(120)
    check("...and takes a dragged height", abs(pv.height() - (h + 60)) < 1.5,
          (h, pv.height()))
    pv.setProperty("paneHeight", int(h))
    APP.setProperty("showPreview", False)
    spin(120)
    check("...and folds away to nothing", not pv.isVisible() and pv.height() == 0,
          pv.height())

    # It follows the JOB, not a selection: the newest output is what it shows,
    # and nothing in the grid can point it elsewhere.
    check("the preview pane has no way to be pointed at an old output",
          not hasattr_qml(pv, "show"), None)

    # A prompt box is dragged taller by its bottom edge, and remembers it.
    box = find_all(content, "PromptBox")[0]
    before = box.height()
    box.setProperty("boxHeight", int(before + 70))
    spin(120)
    check("a prompt box takes a new height", abs(box.height() - (before + 70)) < 1.5,
          (before, box.height()))
    edit = find(box, "QQuickTextEdit")
    check("...and the editor still fills it", edit.height() >= box.height() - 20,
          (edit.height(), box.height()))
    box.setProperty("boxHeight", int(before))
    spin(60)


def test_model_panel(win, ctl):
    content = win.contentItem()
    panel = find(content, "ModelPicker")
    check("the model panel is collapsible now", panel.property("collapsible") is True)
    tall = panel.height()
    panel.setProperty("collapsed", True)
    spin(80)
    check("collapsing it actually shrinks it", panel.height() < tall,
          (tall, panel.height()))
    check("collapsed, its badge names the selected model",
          panel.property("badge") == ctl.property("selectedName"),
          (panel.property("badge"), ctl.property("selectedName")))
    panel.setProperty("collapsed", False)
    spin(80)
    check("and it comes back", abs(panel.height() - tall) < 1.5,
          (tall, panel.height()))


def test_panes(win):
    """The output pane is there at every width, with a cell that fits it."""
    content = win.contentItem()
    grid = find(content, "KineticGridView")
    right = None
    for it in walk(content):
        if it.property("objectName") == "":
            pass
    gal = find(content, "GalleryView")

    for w in (1280, 1000, 900, 800, 720, 640, 560):
        win.setWidth(w)
        APP.setProperty("view", 0)
        spin(120)
        check("w=%d: the output pane is visible in the params view" % w,
              gal.isVisible() and gal.width() > 0, (gal.isVisible(), gal.width()))
        check("w=%d: a grid cell fits inside the pane" % w,
              grid.property("cellWidth") <= gal.width() + 0.5,
              (grid.property("cellWidth"), gal.width()))
        check("w=%d: the controls pane is still usable" % w,
              find(content, "ModelPicker").width() >= 260,
              find(content, "ModelPicker").width())

    # Below the floor it is one pane at a time, and the g button must reach the
    # gallery rather than leave it hidden for good.
    win.setWidth(480)
    APP.setProperty("view", 0)
    spin(120)
    narrow_params = gal.isVisible()
    APP.setProperty("view", 1)
    spin(120)
    check("below the split floor the gallery is one button away",
          (not narrow_params) and gal.isVisible(), (narrow_params, gal.isVisible()))
    win.setWidth(1280)
    APP.setProperty("view", 0)
    spin(120)


def test_resolution(win, ctl):
    """aspect + MP -> one size, in the header, in the readout, in the job."""
    import registry as R

    gen = prop(APP, "gen")
    for aw, ah, mp in ((3, 2, 1.0), (21, 9, 2.0), (5, 3, 0.5), (1, 1, 4.0)):
        gen = prop(APP, "gen")
        gen["aspectW"], gen["aspectH"], gen["megapixels"] = aw, ah, mp
        APP.setProperty("gen", gen)
        APP.metaObject().invokeMethod(APP, "recomputeDims")
        spin(60)
        g = prop(APP, "gen")
        want = R.calc_dims("%d:%d" % (aw, ah), mp, g["multiple"])
        check("%d:%d @ %sMP -> %dx%d" % (aw, ah, mp, want[0], want[1]),
              (g["width"], g["height"]) == want, (g["width"], g["height"]))

    panel = find(win.contentItem(), "ResolutionPanel")
    g = prop(APP, "gen")
    check("the header badge is the real size",
          panel.property("badge") == "%dx%d" % (g["width"], g["height"]),
          panel.property("badge"))
    check("the size boxes are gone",
          len(find_all(panel, "Spin")) == 3, len(find_all(panel, "Spin")))


def test_video(win, ctl, tmp):
    """A video family reshapes the left column, and submits video settings.

    The graph itself is covered by tools/validate-graphs.py against a live
    backend; what is checked here is that the WINDOW stops offering what a video
    job has no room for — a negative prompt, a CFG, an aspect while the dropped
    first frame is deciding it — and that what it does send is the video set.
    """
    content = win.contentItem()
    root = os.environ["PAINTER_MODELS"]
    for rel, keys in VIDEO_FAKES.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})                     # the scratch root is new on every run
    ctl.rescan()
    spin(200)
    ctl.selectModelByName("mini-video.safetensors")
    spin(200)

    check("a video model is recognised and paired",
          ctl.property("selectedName") == "mini-video.safetensors"
          and ctl.property("isVideo") is True,
          (ctl.property("selectedName"), ctl.property("isVideo")))
    if not ctl.property("isVideo"):
        for rel in VIDEO_FAKES:
            os.remove(os.path.join(root, rel))
        return

    # With both decoders present the int8 one wins, because it is faster and
    # 2.3 GiB cheaper and the DiT beside it already stages 20 GB. fp16 stays in
    # the family's `prefer` list purely as the fallback.
    check("a video model pairs with the int8 video VAE, not the fp16 one",
          ctl.property("vaeName") == "minimax_h3_video_vae_int8_convrot.safetensors",
          ctl.property("vaeName"))

    boxes = find_all(content, "PromptBox")
    check("the negative prompt box is gone", [b.isVisible() for b in boxes] == [True, False],
          [b.isVisible() for b in boxes])
    check("the video panel is there", find(content, "VideoPanel").isVisible())
    # ...and the box that went takes its SPACE with it: a Column skips a hidden
    # child when positioning, but the panel sizes itself from childrenRect.
    editor = find(content, "PromptEditor")
    check("no blank where the negative box was",
          boxes[1].height() == 0
          and editor.height() < boxes[0].height() + 60,
          (boxes[1].height(), editor.height(), boxes[0].height()))
    # ...and the panel keeps following the box DOWN with that child hidden. It
    # did not: an invisible child keeps the y the Column last laid it out at and
    # `childrenRect` still spans to it, so the panel could only ever grow and a
    # shrunk prompt box left a blank the height of the drag (his report,
    # 2026-08-06; measured 392 -> 242 with the panel stuck at 435).
    boxes[0].setProperty("boxHeight", 300)
    spin(150)
    tall = editor.height()
    boxes[0].setProperty("boxHeight", 120)
    spin(150)
    check("the panel shrinks with the box even with the negative one hidden",
          editor.height() <= tall - 175 and editor.height() >= boxes[0].height(),
          (tall, editor.height(), boxes[0].height()))
    boxes[0].setProperty("boxHeight", 130)
    spin(120)
    check("the patches panel is not", not find(content, "TogglePanel").isVisible())
    cfg = find(find(content, "ParamsPanel"), "Field",
               pred=lambda it: it.property("label") == "cfg")
    check("there is no CFG to set", not cfg.isVisible())

    res = find(content, "ResolutionPanel")
    aspect = find(res, "Field", pred=lambda it: it.property("label") == "aspect")
    g = prop(APP, "gen")
    g["useInputImage"] = True
    APP.setProperty("gen", g)
    spin(120)
    check("with a first frame the aspect is the image's, so the box goes",
          not aspect.isVisible() and res.property("badge") == "from the image",
          res.property("badge"))
    # ...and a LAST frame on its own does the same: the two toggles are
    # independent, and either dropped image is what the size is measured off.
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(120)
    check("a last frame alone also decides the aspect",
          not aspect.isVisible() and res.property("badge") == "from the image",
          res.property("badge"))
    well = find(find(content, "VideoPanel"), "FrameWell",
                pred=lambda it: it.property("emptyText").endswith("to end on here"))
    check("...and its well stands on its own, with no first frame",
          well is not None and well.isVisible(), well and well.property("active"))
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": False})
    APP.setProperty("gen", g)
    spin(120)
    check("...and text-to-video gets it back", aspect.isVisible())

    # Seconds -> frames, the same arithmetic the graph uses.
    import registry as R
    panel = find(content, "VideoPanel")
    g = prop(APP, "gen")
    g["duration"] = 5.0
    APP.setProperty("gen", g)
    spin(120)
    check("the panel says how many frames that is",
          panel.property("badge") == "%df" % R.video_frames(5.0, 24.0),
          panel.property("badge"))

    # What submit() actually sends for a video job.
    sent = {}
    orig_build, orig_submit = ctl.reg.build, ctl.client.submit

    class FakeJob:
        def __init__(self):
            self.meta = {}

    ctl.reg.build = lambda entry, params, object_info=None: (
        sent.update(params) or {"prompt": {}, "params": dict(params), "pairing": {}})
    ctl.client.submit = lambda prompt, params: (sent.update(_submitted=True) or FakeJob())
    ctl._object_info = {"stub": True}
    g = prop(APP, "gen")
    g.update({"positive": "a clip", "negative": "ignored", "duration": 3.0,
              "steps": 12, "seed": 99, "randomSeed": False, "count": 1,
              "useInputImage": False})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("a video job is submitted", sent.get("_submitted") is True)
    check("...with the duration, not a batch",
          sent.get("duration") == 3.0 and "batch_size" not in sent,
          (sent.get("duration"), "batch_size" in sent))
    check("...and no negative prompt or CFG",
          "negative" not in sent and "cfg" not in sent, sorted(sent))

    # The frame to end on: a second drop, its own upload cache, and INDEPENDENT
    # of the first — first only, last only, or both.
    sent.clear()
    ctl._input_image = os.path.join(root, "first.png")
    ctl._last_image = os.path.join(root, "last.png")
    write_safetensors(os.path.join(root, "unused.safetensors"), {"x": [1]})
    open(ctl._input_image, "wb").write(b"not really a png")
    open(ctl._last_image, "wb").write(b"not really a png either")
    ctl._uploaded = (ctl._input_image, "painter/first.png")
    ctl._uploaded_last = (ctl._last_image, "painter/last.png")
    g = prop(APP, "gen")
    g.update({"useInputImage": True, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("a last frame is sent alongside the first",
          sent.get("use_last_frame") is True and sent.get("last_image") == "painter/last.png"
          and sent.get("input_image") == "painter/first.png",
          (sent.get("use_last_frame"), sent.get("last_image"), sent.get("input_image")))

    # A last frame ON ITS OWN is a job, not an error: the node takes either end.
    sent.clear()
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("a last frame alone is submitted, with no first frame",
          sent.get("_submitted") is True and sent.get("use_last_frame") is True
          and sent.get("use_input_image") is False
          and sent.get("last_image") == "painter/last.png",
          (sent.get("_submitted"), sent.get("use_input_image"), sent.get("last_image")))

    # ...and one turned on with nothing dropped refuses, the same way the first
    # frame does (docs/DESIGN.md §10).
    sent.clear()
    ctl.clearLastImage()
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("a last frame with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)
    g = prop(APP, "gen")
    g["useLastFrame"] = False
    APP.setProperty("gen", g)
    spin(60)
    ctl.clearInputImage()

    # An image-to-video job with nothing dropped must not be silently sent as
    # text-to-video: it says so and submits nothing (docs/DESIGN.md §10).
    sent.clear()
    ctl.clearInputImage()
    g = prop(APP, "gen")
    g["useInputImage"] = True
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("image-to-video with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)

    ctl.reg.build, ctl.client.submit = orig_build, orig_submit
    # A STUBBED SUBMIT STILL QUEUES A ROW. `_start_jobs` puts the job in the
    # history the moment it is submitted (main.py, so the preview changes when
    # generate is pressed and not when the backend gets round to it), and a
    # stubbed client never finishes it — so the row is ended here rather than
    # left at the top of the grid for every test that follows.
    ctl.gallery.end_live()
    spin(60)
    ctl._object_info = None
    g = prop(APP, "gen")
    g["useInputImage"] = False
    APP.setProperty("gen", g)
    for rel in VIDEO_FAKES:
        os.remove(os.path.join(root, rel))
    fp.save_cache({})
    ctl.rescan()
    ctl.selectModelByName("alpha-model.safetensors")
    spin(200)
    check("the image model is back and the column with it",
          ctl.property("isVideo") is False
          and find(content, "TogglePanel").isVisible(), ctl.property("selectedName"))


# The four modes' models, headers only — enough for fingerprint.py to place
# each one in its family, which is all `registry.mode_model` asks. There are TWO
# krea2 files on purpose: `prefer` names the raw one exactly, and a mode that
# quietly landed on turbo would generate at 8 steps for ever without saying so.
MODE_FAKES = {
    "unet/anima-base-v1.0.safetensors": {
        "llm_adapter.blocks.0.cross_attn.q_proj.weight": [16, 1024],
        "x_embedder.proj.1.weight": [16, 16],
        "blocks.0.attn.weight": [16, 16]},
    "unet/krea2_raw_fp8_scaled.safetensors": {
        "txtfusion.projector.weight": [16, 16],
        "txtfusion.layerwise_blocks.0.prenorm.scale": [2560],
        "img_in.weight": [16, 16]},
    "unet/krea2_turbo_fp8_scaled.safetensors": {
        "txtfusion.projector.weight": [16, 16],
        "txtfusion.layerwise_blocks.0.prenorm.scale": [2560],
        "img_in.weight": [16, 16]},
    # Named to exercise the SUBSTRING half of `prefer`: not the filename in the
    # table, but the one word that identifies it.
    "unet/flux-2-klein-4b-test.safetensors": {
        "double_blocks.0.img_attn.qkv.weight": [16, 16],
        "double_blocks.0.double_stream_modulation_img.weight": [16, 16],
        "txt_in.weight": [16, 16]},
}


def test_paste(win, ctl, tmp):
    """A frame well takes the CLIPBOARD as well as a drop.

    The clipboard here is the offscreen platform's own, in-process: there is no
    Wayland connection in this run, so nothing below can read or replace HIS
    selection. Both routes are exercised — the `[ paste ]` button, by a real
    click, and Ctrl+V, by a real key event at the window — because they are
    different failure modes: the button is a callback, the shortcut is a
    window-level Shortcut that must NOT take Ctrl+V away from the prompt boxes.
    """
    import main as P
    from PySide6.QtCore import Qt, QUrl, QMimeData
    from PySide6.QtGui import QGuiApplication, QImage, QColor
    from PySide6.QtTest import QTest

    # QTest, not the `key()` helper: a window-level Shortcut is matched by the
    # shortcut map on the way IN from the platform, and a hand-sent QKeyEvent
    # goes straight to the focus item without ever passing it (test_escape
    # drives its Shortcut the same way).
    def paste_key():
        QTest.keyClick(win, Qt.Key_V, Qt.ControlModifier)
        spin(80)

    clip = QGuiApplication.clipboard()
    content = win.contentItem()
    said = []
    ctl.toast.connect(lambda msg, bad: said.append((msg, bad)))

    # A video family, for the two wells side by side — the one arrangement
    # where "which well did that go into?" can be got wrong.
    root = os.environ["PAINTER_MODELS"]
    for rel, keys in VIDEO_FAKES.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})
    ctl.rescan()
    spin(200)
    ctl.selectModelByName("mini-video.safetensors")
    spin(200)
    g = prop(APP, "gen")
    g.update({"useInputImage": True, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(150)

    well = find(find(content, "VideoPanel"), "FrameWell",
                pred=lambda it: it.property("emptyText").endswith("to start from here"))
    check("the first-frame well is there", well is not None and well.isVisible())
    btn = find(well, "TextButton", pred=lambda it: it.property("label") == "[ paste ]")
    check("...with a [ paste ] button in it", btn is not None and btn.isVisible())

    # ---- a FILE on the clipboard (filer, viewer, a browser) ----
    src = fake_png(os.path.join(tmp, "clip-src.png"), {"positive": "x"})
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(src)])
    clip.setMimeData(md)
    ctl.clearInputImage()
    said.clear()
    click(win, btn)
    check("a copied FILE pastes as itself, no copy made",
          ctl.property("inputImage") == src, ctl.property("inputImage"))
    check("...silently — the well filling is the report", said == [], said)

    # ---- PIXELS on the clipboard (a screenshot, a browser's copy image) ----
    img = QImage(8, 6, QImage.Format_RGB32)
    img.fill(QColor(200, 40, 10))
    clip.setImage(img)
    ctl.clearInputImage()
    click(win, btn)
    got = ctl.property("inputImage")
    check("pasted PIXELS are written to a file painter can send",
          got.endswith(".png") and os.path.isfile(got)
          and os.path.dirname(got) == str(P.CACHE / "pasted"), got)
    check("...and it decodes back to the same picture",
          QImage(got).size() == img.size(), QImage(got).size())
    first = got

    # Twice is one file: named by CONTENT, so the upload cache hits too.
    ctl.clearInputImage()
    click(win, btn)
    check("the same pixels pasted twice are the same file",
          ctl.property("inputImage") == first, (first, ctl.property("inputImage")))
    check("...and only one landed on disk",
          len(list((P.CACHE / "pasted").glob("pasted-*.png"))) == 1,
          list((P.CACHE / "pasted").glob("pasted-*.png")))

    # ---- TEXT that names an image (filer's "copy path") ----
    clip.setText(src)
    ctl.clearInputImage()
    click(win, btn)
    check("a pasted PATH is taken", ctl.property("inputImage") == src,
          ctl.property("inputImage"))

    # ---- a FILE viewer opens but painter cannot SEND (svg/ico/...) ----
    # viewer's IMAGE_EXTS is wider than painter's IMAGE_SUFFIXES, so an image
    # copied out of viewer can be one painter would refuse to upload as a frame.
    # Rather than error on a paste of a real picture, painter decodes the file
    # itself and pastes it as pixels (→ a png in the cache). Regression for the
    # viewer→painter round-trip that errored on such formats.
    svg = os.path.join(tmp, "clip-src.svg")
    open(svg, "w").write(
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="9">'
        '<rect width="12" height="9" fill="#3050c0"/></svg>')
    if not QImage(svg).isNull():   # only where this Qt build can decode svg
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(svg)])
        clip.setMimeData(md)
        ctl.clearInputImage()
        said.clear()
        click(win, btn)
        got = ctl.property("inputImage")
        check("an svg viewer opened pastes as pixels, not an error",
              got.endswith(".png") and os.path.isfile(got)
              and os.path.dirname(got) == str(P.CACHE / "pasted"), (got, said))
        check("...silently — no refusal toast", said == [], said)

    # ---- the refusals, out loud (docs/DESIGN.md §10) ----
    for payload, why in ((("text", "just some words"), "that is not a file painter can read"),
                         (("file", os.path.join(tmp, "notes.txt")), "paste an image (png, jpg, webp)")):
        kind, val = payload
        if kind == "file":
            open(val, "w").write("x")
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(val)])
            clip.setMimeData(md)
        else:
            clip.setText(val)
        ctl.clearInputImage()
        said.clear()
        click(win, btn)
        check("a paste of %r says why" % kind,
              ctl.property("inputImage") == "" and said and said[0][0] == why
              and said[0][1] is True, (said, ctl.property("inputImage")))

    # ---- Ctrl+V, with the pointer wherever it happens to be ----
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(src)])
    clip.setMimeData(md)
    ctl.clearInputImage()
    APP.metaObject().invokeMethod(APP, "releaseFocus")
    spin(60)

    # No hover needed. Requiring one is what made this do nothing at all for
    # anyone pressing Ctrl+V the ordinary way, silently, since a disabled
    # shortcut has no failure to report.
    APP.setProperty("hoveredWell", "")
    paste_key()
    check("Ctrl+V with the pointer nowhere near still pastes",
          ctl.property("inputImage") == src, ctl.property("inputImage"))

    # Both wells on and the first one full: the next paste goes to the empty one
    # rather than replacing what is already there.
    ctl.clearLastImage()
    paste_key()
    check("...into the EMPTY well when the other is taken",
          ctl.property("lastImage") == src and ctl.property("inputImage") == src,
          (ctl.property("inputImage"), ctl.property("lastImage")))

    # The pointer still wins when it is on a well — that is the unambiguous case.
    ctl.clearInputImage()
    ctl.clearLastImage()
    APP.setProperty("hoveredWell", "last")
    paste_key()
    check("the hovered well wins",
          ctl.property("lastImage") == src and ctl.property("inputImage") == "",
          (ctl.property("inputImage"), ctl.property("lastImage")))
    APP.setProperty("hoveredWell", "")
    ctl.clearLastImage()

    # A last frame alone: one well on screen, so Ctrl+V can only mean that one.
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(120)
    paste_key()
    check("with only the last-frame well up, Ctrl+V means it",
          ctl.property("lastImage") == src and ctl.property("inputImage") == "",
          (ctl.property("inputImage"), ctl.property("lastImage")))
    ctl.clearLastImage()

    # Text-to-video has no well at all, and a shortcut with no target must not
    # invent one.
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": False})
    APP.setProperty("gen", g)
    spin(120)
    paste_key()
    check("with no well on screen, Ctrl+V does nothing",
          ctl.property("inputImage") == "" and ctl.property("lastImage") == "",
          (ctl.property("inputImage"), ctl.property("lastImage")))
    g = prop(APP, "gen")
    g.update({"useInputImage": True, "useLastFrame": True})
    APP.setProperty("gen", g)
    spin(120)

    # THE REGRESSION THIS GUARDS: a window Shortcut sees a key before the
    # focused item, so an unguarded Ctrl+V would eat the prompt boxes' paste.
    box = find_all(content, "PromptBox")[0]
    ed = find(box, "QQuickTextEdit")
    ed.forceActiveFocus()
    ed.setProperty("text", "")
    spin(60)
    check("a focused prompt box is seen as one", APP.property("textFocused") is True)
    clip.setText("pasted into the prompt")
    paste_key()
    check("Ctrl+V still pastes TEXT into a focused prompt box",
          ed.property("text") == "pasted into the prompt", ed.property("text"))

    # ...even with the pointer parked on a well. That is why [ paste ] exists.
    ed.setProperty("text", "")
    ctl.clearInputImage()
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(src)])
    clip.setMimeData(md)
    APP.setProperty("hoveredWell", "input")
    paste_key()
    check("a focused text box wins Ctrl+V over a hovered well",
          ctl.property("inputImage") == "", ctl.property("inputImage"))
    APP.setProperty("hoveredWell", "")
    ed.setProperty("text", "")
    APP.metaObject().invokeMethod(APP, "releaseFocus")
    spin(60)
    check("...and letting go of the box gives Ctrl+V back",
          APP.property("textFocused") is False)

    # Put the column back the way test_video expects to find it.
    ctl.clearInputImage()
    ctl.clearLastImage()
    g = prop(APP, "gen")
    g.update({"useInputImage": False, "useLastFrame": False})
    APP.setProperty("gen", g)
    for rel in VIDEO_FAKES:
        os.remove(os.path.join(root, rel))
    fp.save_cache({})
    ctl.rescan()
    ctl.selectModelByName("alpha-model.safetensors")
    spin(200)


def test_modes(win, ctl, tmp):
    """The switcher above the model list: four shortcuts, and the list greyed.

    What is checked is the whole contract of a mode — which file it lands on,
    that the list stops taking clicks while one is lit, that turning it off
    hands the list back without moving the selection, and that `edit` reshapes
    the left column into an image well and one prompt.
    """
    content = win.contentItem()
    root = os.environ["PAINTER_MODELS"]
    import fingerprint as fp
    for rel, keys in MODE_FAKES.items():
        write_safetensors(os.path.join(root, rel), keys)
    fp.save_cache({})
    ctl.rescan()
    spin(200)

    modes = {m["id"]: m for m in ctl.modes()}
    check("the switcher offers the four modes",
          list(modes) == ["anime", "real", "edit", "video"], list(modes))
    check("anime is anima's base model",
          modes["anime"]["available"] and modes["anime"]["model"] == "anima-base-v1.0.safetensors",
          modes["anime"])
    check("real is krea 2 RAW, not the turbo beside it",
          modes["real"]["model"] == "krea2_raw_fp8_scaled.safetensors", modes["real"])
    check("edit finds Klein by name even when the file is not the one in the table",
          modes["edit"]["available"]
          and "klein" in modes["edit"]["model"], modes["edit"])
    check("video has no model here, and says so rather than vanishing",
          modes["video"]["available"] is False and "minimax" in modes["video"]["tip"],
          modes["video"])

    switcher = find(content, "ModeSwitcher")
    buttons = find_all(switcher, "TextButton")
    check("...and there is a button for each of them", len(buttons) == 4,
          [b.property("label") for b in buttons])
    check("the one with no model is disabled, not missing",
          [b.property("enabled") for b in buttons] == [True, True, True, False],
          [(b.property("label"), b.property("enabled")) for b in buttons])

    listview = find(find(content, "ModelPicker"), "KineticListView")
    check("with no mode on, the model list takes clicks", listview.isEnabled())

    ctl.setMode("real")
    spin(150)
    check("picking a mode selects its model",
          ctl.property("mode") == "real"
          and ctl.property("selectedName") == "krea2_raw_fp8_scaled.safetensors",
          (ctl.property("mode"), ctl.property("selectedName")))
    check("...and greys the list out, clicks and all",
          not listview.isEnabled() and listview.parent().property("opacity") < 1,
          (listview.isEnabled(), listview.parent().property("opacity")))
    check("...with its own button lit",
          [b.property("lit") for b in buttons] == [False, True, False, False],
          [(b.property("label"), b.property("lit")) for b in buttons])

    # Turning it off hands the list back and LEAVES the model where it is: he
    # got here through the button, and jumping back would undo a choice he did
    # not make.
    ctl.setMode("")
    spin(150)
    check("turning the mode off hands the list back",
          ctl.property("mode") == "" and listview.isEnabled()
          and ctl.property("selectedName") == "krea2_raw_fp8_scaled.safetensors",
          (ctl.property("mode"), ctl.property("selectedName")))

    # A mode whose model is not here refuses and stays off, rather than lighting
    # up over a selection that did not change (docs/DESIGN.md §10).
    ctl.setMode("video")
    spin(150)
    check("a mode with no model refuses instead of lighting up",
          ctl.property("mode") == "" and ctl.property("isVideo") is False,
          ctl.property("mode"))

    # --- edit: an image well and a prompt, and nothing else ------------------
    ctl.setMode("edit")
    spin(200)
    check("edit selects Klein and switches the pipeline",
          ctl.property("mode") == "edit" and ctl.property("isEdit") is True
          and "klein" in ctl.property("selectedName"),
          (ctl.property("mode"), ctl.property("selectedName")))

    edit_panel = find(content, "EditPanel")
    check("there is a place to drop the image", edit_panel is not None
          and edit_panel.isVisible())
    check("...and it is a real drop target",
          find(edit_panel, "FrameWell") is not None
          and find(edit_panel, "FrameWell").property("active") is True)
    boxes = find_all(content, "PromptBox")
    check("one prompt box, no negative",
          [b.isVisible() for b in boxes] == [True, False],
          [b.isVisible() for b in boxes])
    hidden = {name: find(content, name) for name in
              ("ParamsPanel", "ResolutionPanel", "TogglePanel", "VideoPanel")}
    check("every control the edit graph would ignore is gone",
          all(not it.isVisible() for it in hidden.values()),
          {k: it.isVisible() for k, it in hidden.items()})
    # ...but a LoRA IS applied to the edit graph (the LoraLoader chains onto the
    # loader→ModelSampling seam exactly as the image path does), so the picker
    # stays offered in edit mode — the one control below the prompt that changes
    # what the edit graph produces.
    lora_stack = find(content, "LoraStack")
    check("the LoRA stack is offered in edit mode too",
          lora_stack is not None and lora_stack.isVisible(),
          lora_stack and lora_stack.isVisible())
    # ...but the seed IS read by the edit graph, so its control survives here —
    # the sampling panel that normally carries it is one of the hidden ones.
    seed_panel = find(content, "SeedPanel")
    check("the edit preset keeps a seed control", seed_panel is not None
          and seed_panel.isVisible())
    g = prop(APP, "gen")
    g.update({"randomSeed": False, "reuseSeed": False})
    APP.setProperty("gen", g)
    spin(60)
    seed_spin = seed_panel and find(seed_panel, "Spin")
    check("...and its seed number is editable when not random/reuse",
          seed_spin is not None and seed_spin.property("enabled") is True,
          seed_spin and seed_spin.property("enabled"))

    # What submit() sends for an edit job: the prompt and the seed, and NOT the
    # numbers whose controls are off screen — the family's edit block owns those.
    sent = {}
    orig_build, orig_submit = ctl.reg.build, ctl.client.submit

    class FakeJob:
        def __init__(self):
            self.meta = {}

    ctl.reg.build = lambda entry, params, object_info=None: (
        sent.update(params) or {"prompt": {}, "params": dict(params), "pairing": {}})
    ctl.client.submit = lambda prompt, params: (sent.update(_submitted=True) or FakeJob())
    ctl._object_info = {"stub": True}

    # ...and with nothing dropped it refuses rather than submitting a graph with
    # an empty filename in it.
    ctl.clearInputImage()
    g = prop(APP, "gen")
    g.update({"positive": "make it a doll", "negative": "ignored",
              "seed": 4242, "randomSeed": False, "count": 1})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("edit with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)

    src = os.path.join(tmp, "to-edit.png")
    with open(src, "wb") as fh:
        fh.write(b"not really a png")
    ctl._input_image = src
    ctl._uploaded = (src, "painter/to-edit.png")   # already uploaded: no network
    sent.clear()
    APP.metaObject().invokeMethod(APP, "submit")
    spin(250)
    check("an edit job is submitted", sent.get("_submitted") is True, sent)
    check("...as an edit, with the image and the prompt",
          sent.get("edit") is True and sent.get("input_image") == "painter/to-edit.png"
          and sent.get("positive") == "make it a doll",
          {k: sent.get(k) for k in ("edit", "input_image", "positive")})
    check("...and the seed the edit preset chose reaches the graph",
          sent.get("seed") == 4242, sent.get("seed"))
    check("...and none of the controls it does not show",
          not any(k in sent for k in ("steps", "cfg", "width", "height",
                                      "batch_size", "negative", "toggles")),
          sorted(sent))
    check("...a single image still submits input_images with one entry",
          sent.get("input_images") == ["painter/to-edit.png"],
          sent.get("input_images"))

    # An active LoRA reaches the edit graph the same way it reaches an image one:
    # `_start_jobs` sends `loras.active()` for every pipeline, and `_build_edit`
    # chains a LoraLoader onto it. (The list is populated by `_start_jobs`, not
    # submit(), so it appears in the built params rather than the submit dict.)
    ctl.loras.add("edit-lora.safetensors", False)
    ctl.loras.setStrength(0, 0.7)
    sent.clear()
    APP.metaObject().invokeMethod(APP, "submit")
    spin(250)
    check("an active LoRA reaches the edit job",
          sent.get("loras") == [{"name": "edit-lora.safetensors", "strength": 0.7,
                                 "enabled": True, "patches_clip": False}],
          sent.get("loras"))
    ctl.loras.clear()

    # MULTIPLE reference images: Flux 2 Klein takes N, chained as reference
    # latents. The extras are their own list; the primary still sizes the job,
    # so input_images is [primary, extra1, extra2] in order.
    for rel in ("ref-a.png", "ref-b.png"):
        with open(os.path.join(tmp, rel), "wb") as fh:
            fh.write(b"not really a png")
    ctl._edit_extra = [os.path.join(tmp, "ref-a.png"), os.path.join(tmp, "ref-b.png")]
    ctl._edit_uploads = {ctl._edit_extra[0]: "painter/ref-a.png",
                         ctl._edit_extra[1]: "painter/ref-b.png"}
    check("editExtraImages exposes the reference list to QML",
          list(ctl.property("editExtraImages")) == ctl._edit_extra,
          ctl.property("editExtraImages"))
    sent.clear()
    APP.metaObject().invokeMethod(APP, "submit")
    spin(300)
    check("an edit job carries every reference image, primary first",
          sent.get("input_images") == ["painter/to-edit.png",
                                       "painter/ref-a.png", "painter/ref-b.png"]
          and sent.get("input_image") == "painter/to-edit.png",
          {k: sent.get(k) for k in ("input_image", "input_images")})
    ctl.removeEditImage(0)
    check("removeEditImage drops one reference, keeping the rest",
          list(ctl.property("editExtraImages")) == [os.path.join(tmp, "ref-b.png")],
          ctl.property("editExtraImages"))
    ctl.clearEditImages()
    check("clearEditImages empties the reference list",
          len(ctl.property("editExtraImages")) == 0,
          ctl.property("editExtraImages"))

    ctl.reg.build, ctl.client.submit = orig_build, orig_submit
    # A STUBBED SUBMIT STILL QUEUES A ROW. `_start_jobs` puts the job in the
    # history the moment it is submitted (main.py, so the preview changes when
    # generate is pressed and not when the backend gets round to it), and a
    # stubbed client never finishes it — so the row is ended here rather than
    # left at the top of the grid for every test that follows.
    ctl.gallery.end_live()
    spin(60)
    ctl._object_info = None
    ctl.clearInputImage()
    ctl.setMode("")
    spin(60)
    for rel in MODE_FAKES:
        os.remove(os.path.join(root, rel))
    fp.save_cache({})
    ctl.rescan()
    ctl.selectModelByName("alpha-model.safetensors")
    spin(200)
    check("the plain image model is back, and the column with it",
          ctl.property("isEdit") is False
          and find(content, "TogglePanel").isVisible(),
          ctl.property("selectedName"))


def test_drag_out(win, ctl, tmp):
    """An output can be dragged into another app — and a clip goes out muted.

    The gesture itself is Qt's (a cross-app QDrag, which an offscreen harness
    cannot complete), so what is checked here is the two halves that are ours:
    the delegate carries the drag wiring, and the PAYLOAD names the right file.
    """
    import main as P
    content = win.contentItem()

    still = fake_png(os.path.join(tmp, "out", "drag_00001_.png"), {"steps": 4})
    vid_dir = os.path.join(tmp, "out", "video")
    os.makedirs(vid_dir, exist_ok=True)
    clip = os.path.join(vid_dir, "drag_00001_.mp4")
    with open(clip, "wb") as fh:
        fh.write(b"\0" * 64)
    ctl.gallery.load_existing()
    spin(200)

    tile = None
    for it in walk(content):
        if it.metaObject().indexOfProperty("dragOriginal") >= 0:
            tile = it
            break
    check("a gallery tile is armed for dragging out", tile is not None)

    RAN.clear()
    payload = ctl.dragUriList(still, False)
    check("a still drags out as itself, CRLF-terminated (RFC 2483)",
          payload == "file://" + still + "\r\n" and not RAN, (payload, RAN))

    RAN.clear()
    payload = ctl.dragUriList(clip, False)
    made = [a for a in RAN if os.path.basename(a[0]) == "ffmpeg"]
    check("a clip drags out MUTED, remuxed rather than re-encoded",
          payload.strip().endswith("drag_00001_-muted.mp4")
          and len(made) == 1 and "-c" in made[0] and "copy" in made[0], (payload, RAN))
    check("...into the cache, not beside the original",
          "/cache/" in payload and "drag_00001_-muted.mp4" not in os.listdir(vid_dir),
          (payload, os.listdir(vid_dir)))

    RAN.clear()
    again = ctl.dragUriList(clip, False)
    check("...made once, then reused", again == payload and not RAN, (again, RAN))

    RAN.clear()
    payload = ctl.dragUriList(clip, True)
    check("Shift hands over the original, with its sound",
          payload == "file://" + clip + "\r\n" and not RAN, (payload, RAN))

    # A fresh copy already sitting beside the clip (the right-click action made
    # one) is used as it stands rather than remade in the cache.
    sibling = os.path.join(vid_dir, "drag_00001_-muted.mp4")
    with open(sibling, "wb") as fh:
        fh.write(b"\0" * 64)
    os.utime(sibling, (time.time() + 5, time.time() + 5))
    RAN.clear()
    payload = ctl.dragUriList(clip, False)
    check("an existing muted copy beside it wins over making another",
          payload == "file://" + sibling + "\r\n" and not RAN, (payload, RAN))

    check("a file that has gone hands over nothing at all",
          ctl.dragUriList(os.path.join(tmp, "not-here.mp4"), False) == "")

    for f in (still, clip, sibling):
        os.remove(f)
    ctl.gallery.load_existing()
    spin(120)


def noisy_png(path, w, h):
    """An output that will not compress away: per-pixel pseudo-random colour, so
    the budget search has to actually spend bytes on it. Deterministic — a
    harness has to give the same answer twice. (filer's imgconv-test has the
    same helper for the same reason.)"""
    from PySide6.QtGui import QImage
    img = QImage(w, h, QImage.Format_RGB32)
    s = 0x2545F491
    for y in range(h):
        for x in range(w):
            s = (s * 1103515245 + 12345) & 0xFFFFFFFF
            img.setPixel(x, y, ((s >> 16) & 255) << 16 | ((s >> 8) & 255) << 8 | (s & 255))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")
    return path


def test_thumb_cache(win, ctl, tmp):
    """A still's tile draws a CACHED THUMBNAIL, never the output itself.

    Half of book's history is top's output directory over sshfs, where reading
    one 1.2 MB PNG was measured at 0.70s — and a GridView re-reads it every time
    the delegate comes back. So the model makes a small JPEG once and the
    delegate binds at that; the checks are that the file lands, that the row
    reports it, that the tile is bound to the ROW and not to the original, and
    that a second scan takes it straight off disk with no work at all.
    """
    import main as P
    from PySide6.QtCore import QUrl

    big = noisy_png(os.path.join(tmp, "out", "thumb_00001_.png"), 1400, 900)
    ctl.gallery.load_existing()
    spin(1200)

    row = [r for r in ctl.gallery._all if r["path"] == big]
    check("the still is in the gallery", len(row) == 1)
    if not row:
        return
    thumb = QUrl(row[0]["thumb"]).toLocalFile() if row[0]["thumb"] else ""
    check("a still gains a cached thumbnail", bool(thumb), row[0]["thumb"])
    if thumb:
        check("...which is a file in painter's cache, not the output",
              os.path.exists(thumb) and thumb != big
              and os.path.dirname(thumb) == str(P.CACHE / "thumbs"), thumb)
        from PySide6.QtGui import QImage
        img = QImage(thumb)
        check("...decodable and no bigger than the grid ever draws",
              not img.isNull() and max(img.width(), img.height()) <= P.THUMB_PX,
              (img.width(), img.height()))
        check("...and a fraction of the original's bytes",
              os.path.getsize(thumb) < os.path.getsize(big) / 2,
              (os.path.getsize(thumb), os.path.getsize(big)))

    # A second scan must not queue a single job: the whole point is that the
    # history is decoded once and never again.
    ctl.gallery.load_existing()
    check("a second scan takes them off disk, decoding nothing",
          not ctl.gallery._thumb_queue and not ctl.gallery._thumb_busy,
          (len(ctl.gallery._thumb_queue), len(ctl.gallery._thumb_busy)))

    # And the tile is bound at the row, so a landing thumbnail reaches it and
    # the original is never the source.
    with open(os.path.join(PAINTER, "qml", "GalleryView.qml")) as fh:
        src = fh.read()
    # (The live row's tile draws the sampler's frames instead, which is the
    # other branch of the same binding — still never the output url.)
    check("the tile draws `thumb`, never the output url",
          "(isVideo ? poster : thumb)" in src)

    # This fixture is a big unparameterised still and every later test scans the
    # same output root; leave the world as it was found.
    os.remove(big)
    ctl.gallery.load_existing()
    spin(60)


def test_selection_and_collage(win, ctl, tmp):
    """Shift and ctrl select outputs, and dragging a set hands over ONE picture.

    [his] "make it so i can shift / cntrl shift a selection of outputs, and when
    i click and drag them, what gets put down where the cursor lies is a collage
    of them in the highest quality under 4mb".
    """
    import imgfit
    content = win.contentItem()
    view = find(content, "GalleryView")

    made = [noisy_png(os.path.join(tmp, "out", "sel_0000%d_.png" % i), 300, 220)
            for i in range(1, 5)]
    ctl.gallery.load_existing()
    spin(250)
    paths = [ctl.gallery.pathAt(i) for i in range(ctl.gallery.rowCount())]
    check("the four outputs are in the gallery",
          all(p in paths for p in made), paths)

    # --- the three gestures, through the view's own functions ---------------
    view.metaObject().invokeMethod(view, "clearSelection")
    spin(60)
    check("nothing is selected to start with", len(prop(view, "selection")) == 0)

    order = [p for p in paths if p in made]      # gallery order, newest first
    invoke_str(view, "selectSingle", order[0])
    check("a plain click selects one", prop(view, "selection") == [order[0]],
          prop(view, "selection"))
    invoke_str(view, "extendTo", order[2])
    sel = prop(view, "selection")
    check("shift extends a range from the anchor",
          sel == order[0:3], sel)
    invoke_str(view, "toggleSelect", order[1])
    sel = prop(view, "selection")
    check("ctrl takes one back out of the middle",
          sel == [order[0], order[2]], sel)
    invoke_str(view, "toggleSelect", order[3])
    sel = prop(view, "selection")
    check("...and puts another in", sorted(sel) == sorted([order[0], order[2], order[3]]),
          sel)

    # A selection survives a new output landing — it is kept as paths, so the
    # row that inserts at 0 does not renumber it.
    extra = noisy_png(os.path.join(tmp, "out", "sel_00099_.png"), 80, 80)
    ctl.gallery.add(extra)
    spin(150)
    check("a finished job does not disturb the selection",
          sorted(prop(view, "selection")) == sorted([order[0], order[2], order[3]]),
          prop(view, "selection"))

    # --- what a drag of that set hands over ---------------------------------
    payload = ctl.dragUriListFor([order[0], order[2], order[3]], False)
    check("a selection drags as ONE uri, not three",
          payload.count("file://") == 1 and payload.endswith("\r\n"), payload)
    out = payload.strip().replace("file://", "")
    check("...which is a collage file that exists", os.path.exists(out), out)
    if os.path.exists(out):
        size = os.path.getsize(out)
        check("...under 4MB, as asked", size <= imgfit.LIMIT, size)
        from PySide6.QtGui import QImage
        made_img = QImage(out)
        check("...and decodable, laid out as a grid of them",
              not made_img.isNull() and made_img.width() > 400 and made_img.height() > 300,
              (made_img.width(), made_img.height()))

    # Asking twice does not build twice.
    import time as _t
    t0 = _t.time()
    again = ctl.dragUriListFor([order[0], order[2], order[3]], False)
    check("...built once, then reused", again == payload and _t.time() - t0 < 1.0,
          (again == payload, round(_t.time() - t0, 2)))

    # One output is still one output — no collage, no re-encode.
    single = ctl.dragUriListFor([order[0]], False)
    check("a selection of one drags as the file itself",
          single == "file://" + order[0] + "\r\n", single)

    # --- the layout itself ---------------------------------------------------
    import collage as C
    check("the grid is as square as the count allows",
          [C.grid_for(n) for n in (1, 2, 3, 4, 5, 9)]
          == [(1, 1), (2, 1), (2, 2), (2, 2), (3, 2), (3, 3)],
          [C.grid_for(n) for n in (1, 2, 3, 4, 5, 9)])
    from PySide6.QtGui import QImage as QI
    imgs = [QI(300, 220, QI.Format_RGB32) for _ in range(3)]
    for im in imgs:
        im.fill(0x204060)
    canvas = C.render(imgs, cell=200)
    check("a collage of three is one canvas big enough to hold them",
          canvas is not None and canvas.width() >= 400 and canvas.height() >= 400,
          canvas and (canvas.width(), canvas.height()))
    check("a collage of one is that one image, not a canvas with a border",
          C.render([imgs[0]]) is imgs[0])

    view.metaObject().invokeMethod(view, "clearSelection")
    spin(60)
    for f in made + [extra]:
        os.remove(f)
    ctl.gallery.load_existing()
    spin(150)


def invoke_str(obj, method, arg):
    """Call a QML function that takes one string, from Python."""
    from PySide6.QtCore import Q_ARG, QMetaObject, Qt
    QMetaObject.invokeMethod(obj, method, Qt.DirectConnection,
                             Q_ARG("QVariant", arg))
    spin(80)


def test_hover_play(win, ctl, tmp):
    """Hovering a clip plays it, silently, and only while the pointer is there.

    The decoding itself is Qt's, so what is asserted is the wiring: nothing
    plays until the pointer is on the tile, what plays is muted, the play
    marker stands down while it does, and LEAVING destroys the player rather
    than leaving a decoder running on every tile the mouse ever crossed.
    """
    import subprocess as sp
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest

    content = win.contentItem()
    vid_dir = os.path.join(tmp, "out", "video")
    os.makedirs(vid_dir, exist_ok=True)
    clip = os.path.join(vid_dir, "hover_00001_.mp4")
    try:
        sp.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                "-i", "testsrc=size=160x120:rate=12:duration=2", "-pix_fmt", "yuv420p",
                clip], check=True, timeout=60)
    except (OSError, sp.SubprocessError):
        check("ffmpeg is there to make a test clip", False, "skipped")
        return
    ctl.gallery.load_existing()
    spin(300)

    grid = find(content, "KineticGridView")
    APP.setProperty("view", 1)
    spin(150)
    tile = None
    for it in walk(grid):
        if it.metaObject().indexOfProperty("dragOriginal") >= 0 and it.height() > 0:
            tile = it
            break
    if tile is None:
        check("a clip tile is realised to hover", False)
        return

    players = lambda: [it for it in walk(tile)
                       if it.metaObject().className().startswith("QQuickVideoOutput")]
    check("nothing is decoding before the pointer arrives", not players(), len(players()))

    p = tile.mapToScene(QPointF(tile.width() / 2, tile.height() / 2))
    QTest.mouseMove(win, QPoint(int(p.x()), int(p.y())))
    spin(400)
    vo = players()
    check("hovering a clip starts it playing", len(vo) == 1, len(vo))
    if vo:
        holder = vo[0].parent()
        check("...and it plays, rather than sitting at frame 0",
              holder.property("playing") is True, holder.property("playing"))
        check("...with the sound off, not merely turned down",
              holder.property("muted") is True and holder.property("volume") == 0,
              (holder.property("muted"), holder.property("volume")))
        marker = find(tile, "QQuickLoader",
                      pred=lambda it: it.property("active") is True) is not None
        check("...and the play marker stands down while it is playing", True, marker)

    # ...and off the tile it is gone, not paused.
    QTest.mouseMove(win, QPoint(int(p.x()), int(p.y()) + int(grid.height())))
    spin(400)
    check("leaving the tile destroys the player", not players(), len(players()))

    APP.setProperty("view", 0)
    os.remove(clip)
    ctl.gallery.load_existing()
    spin(150)


def test_live_bindings(win, ctl):
    """A setting changed by a CONTROL must reach the screen, not just the data.

    This is the regression that made the resolution readout wrong: painter
    mutated its `gen` object in place, which emits no change signal, so every
    display bound to it was stale until something else happened to reassign.
    """
    content = win.contentItem()
    res = find(content, "ResolutionPanel")
    spins = find_all(res, "Spin")

    # Drive the real onEdited chain, exactly as a typed edit does.
    for sp, v in ((spins[0], 16.0), (spins[1], 9.0), (spins[2], 2.0)):
        sp.metaObject().invokeMethod(sp, "commit", Q_ARG("QVariant", v))
    spin(150)
    g = prop(APP, "gen")
    check("editing the aspect boxes reaches the model",
          (g["aspectW"], g["aspectH"], g["megapixels"]) == (16, 9, 2.0),
          (g["aspectW"], g["aspectH"], g["megapixels"]))
    check("...and the header badge follows the edit",
          res.property("badge") == "%dx%d" % (g["width"], g["height"]),
          (res.property("badge"), g["width"], g["height"]))

    # A Spin must still follow the MODEL after it has been edited once: the old
    # commit() assigned its own bound `value`, which destroys the binding.
    APP.metaObject().invokeMethod(APP, "set", Q_ARG("QVariant", "megapixels"),
                                  Q_ARG("QVariant", 1.5))
    spin(120)
    check("a Spin still follows the model after being edited",
          abs(spins[2].property("value") - 1.5) < 1e-6, spins[2].property("value"))

    # The ModelSampling block is bound to gen.modelSampling — with in-place
    # mutation it never appeared when the toggle was flipped.
    tog = find(content, "TogglePanel")
    APP.metaObject().invokeMethod(APP, "set", Q_ARG("QVariant", "modelSampling"),
                                  Q_ARG("QVariant", False))
    spin(120)
    short = tog.height()
    APP.metaObject().invokeMethod(APP, "set", Q_ARG("QVariant", "modelSampling"),
                                  Q_ARG("QVariant", True))
    spin(120)
    check("toggling ModelSampling reveals its parameters", tog.height() > short + 40,
          (short, tog.height()))

    # The prompt boxes round-trip without fighting the model.
    box = find_all(content, "PromptBox")[0]
    edit = find(box, "QQuickTextEdit")
    edit.setProperty("text", "typed by hand")
    spin(120)
    check("typing reaches the model", prop(APP, "gen")["positive"] == "typed by hand",
          prop(APP, "gen")["positive"])


def test_dropdown(win, ctl):
    """One list, in the overlay, inside the window, above everything."""
    # The sampler list normally comes from the backend's /object_info; offline
    # it would be empty and the pick path would go untested, so inject one.
    ctl._samplers = ["euler", "euler_ancestral", "dpmpp_2m", "heun"]
    ctl._schedulers = ["simple", "karras", "beta"]
    ctl.optionsChanged.emit()
    spin(120)
    content = win.contentItem()
    overlay = find(content, "PickerOverlay")
    check("there is a scene-level picker overlay", overlay is not None)
    if overlay is None:
        return
    check("the overlay is a direct child of the window's root item",
          overlay.parentItem() is content or overlay.parentItem().parentItem() is content)

    params = find(content, "ParamsPanel")
    picker = find(params, "Picker")
    check("the picker no longer carries its own list",
          len(find_all(picker, "KineticListView")) == 0)

    box = find(picker, "QQuickRectangle")
    scroll_to(box)
    click(win, box)
    spin(120)
    check("clicking a picker opens the overlay list", overlay.isVisible())

    pop = None
    for c in overlay.childItems():
        if c.metaObject().className().startswith("QQuickRectangle"):
            pop = c
    check("the list is drawn", pop is not None and pop.height() > 0)
    if pop is not None:
        x, y, w, h = scene_rect(pop)
        check("the list stays inside the window",
              x >= 0 and y >= 0 and x + w <= win.width() + 0.5 and y + h <= win.height() + 0.5,
              (x, y, w, h, win.width(), win.height()))
        check("the list sits above the panes", overlay.z() > 100, overlay.z())

    # Pick the second row and see it land on the control.
    lst = find(overlay, "KineticListView")
    opts = prop(overlay, "options") or []
    if len(opts) > 1:
        rows = [c for c in walk(lst) if c.metaObject().className().startswith("QQuickRectangle")
                and c.height() == 19]
        if rows:
            click(win, rows[1])
            spin(120)
            check("picking closes the list", not overlay.isVisible())
            # The MODEL is what must change: the control follows it back through
            # its binding, which is why accept() must not write `value` itself.
            check("picking sets the model, and the control follows it",
                  prop(APP, "gen")["sampler_name"] == opts[1]
                  and picker.property("value") == opts[1],
                  (prop(APP, "gen")["sampler_name"], picker.property("value"), opts[1]))
            # ...and the binding must SURVIVE the pick.
            APP.metaObject().invokeMethod(APP, "set", Q_ARG("QVariant", "sampler_name"),
                                          Q_ARG("QVariant", opts[2]))
            spin(120)
            check("the picker still follows the model after a pick",
                  picker.property("value") == opts[2],
                  (picker.property("value"), opts[2]))
    else:
        print("SKIP  picking a row (backend offline: no sampler list)")


def test_escape(win, ctl):
    """Escape lets go of a text box. It does not stop anything."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    content = win.contentItem()
    box = find_all(content, "PromptBox")[0]
    edit = find(box, "QQuickTextEdit")
    click(win, box, dx=box.width() / 2, dy=box.height() - 14)
    check("a prompt box takes focus", edit.property("activeFocus") is True)

    cancelled = []
    real_cancel = ctl.cancel
    QTest.keyClick(win, Qt.Key_Escape)
    spin(150)
    check("Escape releases the text box", edit.property("activeFocus") is False)

    # ...and nothing was cancelled: the queue is untouched. `_jobs` is the
    # counter cancel() zeroes, so a non-zero one surviving Escape is the proof.
    ctl._jobs = 3
    ctl._busy = True
    # A VISIBLE one: the left column carries panels that only a video family
    # reveals, and an item inside a hidden panel still answers to `find` —
    # clicking one lands wherever its stale geometry says, which was three
    # unrelated failures and a model selected by a click nobody aimed.
    sp = find(content, "Spin", pred=lambda it: it.isVisible())
    inp = find(sp, "QQuickTextInput")
    click(win, sp, dx=2, dy=sp.height() / 2)
    check("a numeric box takes focus", inp.property("activeFocus") is True)
    QTest.keyClick(win, Qt.Key_Escape)
    spin(150)
    check("Escape releases the numeric box", inp.property("activeFocus") is False)
    check("...and Escape cancelled nothing", ctl._jobs == 3, ctl._jobs)
    ctl._jobs = 0
    ctl._busy = False

    # A window-level Shortcut gets key events BEFORE a focused item's Keys
    # handler, so adding one for Escape could quietly take Escape away from the
    # two things that were already using it to close.
    params = find(content, "ParamsPanel")
    picker = find(params, "Picker")
    overlay = find(content, "PickerOverlay")
    pbox = find(picker, "QQuickRectangle")
    scroll_to(pbox)
    click(win, pbox)
    spin(120)
    if overlay.isVisible():
        QTest.keyClick(win, Qt.Key_Escape)
        spin(150)
        check("Escape still closes an open dropdown", not overlay.isVisible())
    else:
        check("Escape test: the dropdown opened", False, "did not open")

    menu = find(content, "CtxMenu")
    menu.metaObject().invokeMethod(menu, "open", Q_ARG("QVariant", 100),
                                   Q_ARG("QVariant", 100),
                                   Q_ARG("QVariant", [{"label": "x"}]))
    spin(150)
    if menu.isVisible():
        QTest.keyClick(win, Qt.Key_Escape)
        spin(150)
        check("Escape still closes the context menu", not menu.isVisible())
    else:
        check("Escape test: the menu opened", False, "did not open")

    APP.setProperty("showSettings", True)
    spin(150)
    QTest.keyClick(win, Qt.Key_Escape)
    spin(150)
    check("Escape closes the settings drawer", APP.property("showSettings") is False)


def scroll_to(item):
    """Bring `item` to the top of whatever Kinetic view it is inside.

    A click is delivered at a WINDOW coordinate, so a control that has scrolled
    past the bottom edge simply is not clicked — and the parameter column is
    long enough that a 26px change anywhere above it (the drag band did exactly
    that) moves the last panel out of the window. Scrolling first makes these
    checks about the control rather than about where it happened to sit.
    """
    from PySide6.QtCore import QPointF
    flick = item.parentItem()
    while flick is not None and not flick.metaObject().className().startswith(
            ("KineticFlickable", "QQuickFlickable")):
        flick = flick.parentItem()
    if flick is None:
        return
    content = flick.property("contentItem")
    if content is None:
        return
    y = item.mapToItem(content, QPointF(0, 0)).y()
    span = max(0.0, flick.property("contentHeight") - flick.height())
    flick.setProperty("contentY", max(0.0, min(span, y - 8)))
    spin(80)


def _section_order(pane):
    """The section keys in the order they are LAID OUT, which is the thing the
    user sees — not the order of a list somewhere."""
    rows = []
    for it in walk(pane):
        try:
            key = it.property("sectionKey")
        except RuntimeError:
            continue
        if not key:
            continue
        ld = it.parentItem()
        if ld is None or not ld.isVisible():
            continue
        rows.append((ld.y(), str(key)))
    rows.sort()
    return [k for _, k in rows]


def _loader_for(pane, key):
    for it in walk(pane):
        if it.property("sectionKey") == key:
            return it.parentItem(), it
    return None, None


def test_panel_order_and_pins(win, ctl, tmp, keep):
    """The column he arranges, and the values a folded panel still shows."""
    from PySide6.QtCore import QPointF

    pane = find(win.contentItem(), "ParamsPane")
    check("the params pane is there", pane is not None)
    if pane is None:
        return

    pane.metaObject().invokeMethod(pane, "resetOrder")
    spin(150)
    before = _section_order(pane)
    check("the built-in order is the one it starts in",
          before[:3] == ["model", "resolution", "prompt"], before)

    # Drag `prompt`'s header up past `resolution`'s middle: it takes that slot
    # and everything between shifts down, exactly as a release would leave it.
    src_ld, _ = _loader_for(pane, "prompt")
    dst_ld, _ = _loader_for(pane, "resolution")
    if src_ld is None or dst_ld is None:
        check("both sections are on screen to drag between", False,
              (src_ld, dst_ld))
        return
    # A hair above the target's midpoint: at exactly the midpoint the drag has
    # not passed it yet, which is the point of using midpoints.
    mid = dst_ld.mapToItem(None, QPointF(0, dst_ld.height() / 2)).y() - 2
    pane.metaObject().invokeMethod(pane, "dragSection",
                                   Q_ARG("QVariant", "prompt"),
                                   Q_ARG("QVariant", float(mid)))
    spin(250)
    after = _section_order(pane)
    check("dragging a header moves that section",
          after.index("prompt") < after.index("resolution"),
          after)
    check("...and moves nothing else",
          [k for k in after if k != "prompt"] == [k for k in before if k != "prompt"],
          after)

    # Persisted on RELEASE, not during the drag.
    prefs_path = os.path.join(os.environ["XDG_STATE_HOME"], "painter", "prefs.json")
    pane.metaObject().invokeMethod(pane, "dropSection")
    spin(120)
    APP.metaObject().invokeMethod(APP, "saveState")
    spin(80)
    saved = json.loads(json.load(open(prefs_path)).get("sections") or "[]")
    check("the order is persisted for a relaunch",
          saved.index("prompt") < saved.index("resolution"), saved)

    # A saved order that has never heard of a section must not lose it: it comes
    # back at its BUILT-IN position, not appended at the bottom.
    prefs = keep[2]
    prefs.set("sections", json.dumps(["prompt", "model"]))
    pane.metaObject().invokeMethod(pane, "buildSections")
    spin(200)
    rebuilt = _section_order(pane)
    check("a section missing from the saved order returns in place, not last",
          rebuilt[:2] == ["prompt", "lora"]
          and rebuilt.index("resolution") == rebuilt.index("model") + 1,
          rebuilt)

    pane.metaObject().invokeMethod(pane, "resetOrder")
    spin(150)
    check("reset puts the built-in order back", _section_order(pane) == before,
          _section_order(pane))

    # ---- pins
    _, panel = _loader_for(pane, "resolution")
    rows = [it for it in walk(panel)
            if it.property("pinLabel") not in (None, "")
            and it.metaObject().className().startswith("Field")]
    check("the resolution panel has pinnable rows", bool(rows), len(rows))
    if not rows:
        return
    row = rows[-1]                      # "MP", whose value is a number
    label = str(row.property("pinLabel"))

    # THE WAY HE DOES IT: right-click the row's label. It opens the pane's one
    # menu and NAMES the action — pinning used to happen silently on that click,
    # which is an action with no name and no way to discover it.
    from PySide6.QtCore import Qt as _Qt
    lbl = find(row, "PixelText")
    menu = find(win.contentItem(), "CtxMenu")
    scroll_to(row)
    click(win, lbl, button=_Qt.RightButton)
    spin(150)
    labels = [i.get("label") for i in (prop(menu, "items") or []) if i.get("label")]
    check("right-clicking a row's label offers to pin it",
          any(l.startswith("pin " + label) for l in labels), labels)
    menu.metaObject().invokeMethod(menu, "close")
    spin(60)

    # EVERY PANEL, not just this one. `ParamsPanel.qml` had no `id: panel`, so
    # every row in the sampling section was silently unpinnable — the lookup is
    # guarded, so nothing said a word. This walks each panel in the column and
    # asks its first labelled row for a menu.
    for pkey in ("model", "resolution", "prompt", "lora", "sampling", "patches"):
        _ld, pan = _loader_for(pane, pkey)
        if pan is None:
            continue
        cand = [it for it in walk(pan)
                if it.property("pinLabel") not in (None, "")
                and it.metaObject().className().startswith(("Field", "Toggle",
                                                            "ModeSwitcher"))]
        if not cand:
            continue
        target = cand[0]
        host = target
        found = False
        for _ in range(8):
            host = host.parentItem()
            if host is None:
                break
            if host.property("pins") is not None:
                found = True
                break
        check("a row in the %s panel can find its panel" % pkey, found,
              str(target.property("pinLabel")))

    panel.metaObject().invokeMethod(panel, "togglePin", Q_ARG("QVariant", row))
    spin(120)
    pins = prop(panel, "pins") or []
    check("...and taking it pins the row", label in pins, (label, pins))
    check("...and the pin reports the row's live value",
          str(row.property("pinValue")) != "", row.property("pinValue"))

    panel.setProperty("collapsed", True)
    spin(150)
    strip = [it for it in walk(panel)
             if it.metaObject().className().startswith(("PixelText", "Label"))
             and it.isVisible() and label in str(it.property("text") or "")]
    check("a collapsed panel still shows its pins", bool(strip),
          [str(it.property("text")) for it in walk(panel)
           if it.isVisible() and it.property("text")])

    # THE ROW ITSELF, not a copy: it is reparented into the header strip, so it
    # is still the live control up there (his call — pins are editable).
    # COLLAPSING NOW HIDES WHAT IS NOT PINNED, rather than everything: the
    # pinned row stays where it was, live, and the panel shrinks to it.
    others = [it for it in rows if it is not row]
    check("...while an unpinned row is parked out of the column",
          all(not it.isVisible() for it in others),
          [(str(it.property("pinLabel")), it.isVisible()) for it in others])
    check("...and the panel is header + that one row, not just the header",
          panel.height() > 30, panel.height())
    check("...and it is still a working control", row.isEnabled())

    # Expanding puts every row back IN ORDER — QML cannot re-insert a child at
    # an index, so the panel reparents all of them, which is the only thing that
    # keeps a returned row from landing at the bottom.
    panel.setProperty("collapsed", False)
    spin(200)
    # BY POSITION, not by walk order: what matters is where they are laid out.
    laid = sorted(((it.y(), str(it.property("pinLabel"))) for it in walk(panel)
                   if it.property("pinLabel") not in (None, "")
                   and it.metaObject().className().startswith("Field")))
    check("expanding restores the rows in their declared order",
          [k for _y, k in laid] == ["aspect", "MP"], laid)

    panel.metaObject().invokeMethod(panel, "togglePin", Q_ARG("QVariant", row))
    spin(120)
    check("unpinning takes it back off", label not in (prop(panel, "pins") or []),
          prop(panel, "pins"))


def test_filter(win, ctl, tmp):
    """The toolbar's filter field, from the model's side.

    The field itself is a QLineEdit in the KDE toolbar (pylib/kdeshell.py
    `toolbar_search`) and only exists in that session; what it drives is this,
    and this runs in both.
    """
    staged = [
        fake_png(os.path.join(tmp, "out", "kitten.png"),
                 {"positive": "a small cat on a roof", "steps": 10}),
        fake_png(os.path.join(tmp, "out", "cityscape.png"),
                 {"positive": "a rainy city at night", "steps": 11}),
    ]
    for pth in staged:
        ctl.gallery.add(pth)
    spin(200)
    total = ctl.gallery.property("count")
    check("both fixtures are in the gallery", total >= 2, total)

    # By FILENAME.
    ctl.gallery.setFilter("kitten")
    spin(150)
    check("filtering by name shows only the match",
          ctl.gallery.property("count") == 1
          and ctl.gallery.pathAt(0).endswith("kitten.png"),
          (ctl.gallery.property("count"), ctl.gallery.pathAt(0)))

    # By PROMPT, which is read out of the file rather than out of a name.
    ctl.gallery.setFilter("rainy city")
    spin(150)
    check("...and by prompt, every word of it",
          ctl.gallery.property("count") == 1
          and ctl.gallery.pathAt(0).endswith("cityscape.png"),
          (ctl.gallery.property("count"), ctl.gallery.pathAt(0)))

    # Indices are the VISIBLE ones, or every path the selection holds would
    # point at the wrong row while a filter is on.
    check("indexOf answers in the filtered list",
          ctl.gallery.indexOf(ctl.gallery.pathAt(0)) == 0,
          ctl.gallery.indexOf(ctl.gallery.pathAt(0)))

    ctl.gallery.setFilter("no such thing anywhere")
    spin(150)
    check("a filter that matches nothing empties the grid rather than erroring",
          ctl.gallery.property("count") == 0, ctl.gallery.property("count"))

    ctl.gallery.setFilter("")
    spin(150)
    check("clearing it brings everything back",
          ctl.gallery.property("count") == total,
          (ctl.gallery.property("count"), total))

    for pth in staged:
        try: os.remove(pth)
        except OSError: pass
    ctl.gallery.load_existing()
    spin(120)


def test_browse_view(win, ctl, tmp):
    """Browse <-> View: enter, walk, zoom, leave.

    The Gwenview spine, on BOTH faces — so it is tested here, against the
    Hyprland roof, and not only in the KDE shell's menus.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    paths = [fake_png(os.path.join(tmp, "out", "bv%d.png" % i),
                      {"positive": "bv%d" % i, "steps": 10 + i})
             for i in range(3)]
    for pth in paths:
        ctl.gallery.add(pth)
    spin(200)

    gal = find(win.contentItem(), "GalleryView")
    out = find(win.contentItem(), "OutputView")
    check("the output view exists", out is not None)
    if out is None:
        return

    # Newest first, so the last one added is row 0.
    newest = ctl.gallery.pathAt(0)
    APP.metaObject().invokeMethod(APP, "enterView", Q_ARG("QVariant", ""))
    spin(150)
    check("entering View shows one output and hides the grid",
          APP.property("inView") is True and out.isVisible() and not gal.isVisible(),
          (APP.property("inView"), out.isVisible(), gal.isVisible()))
    check("...the newest one, and it is the selection too",
          out.property("source") == newest and APP.property("selOne") == newest,
          (out.property("source"), APP.property("selOne")))

    # The walk moves the SELECTION, which is what View is showing — one cursor.
    APP.metaObject().invokeMethod(APP, "stepOutput", Q_ARG("QVariant", 1))
    spin(120)
    check("the walk keys move to the next output",
          APP.property("selOne") == ctl.gallery.pathAt(1)
          and out.property("source") == ctl.gallery.pathAt(1),
          (APP.property("selOne"), out.property("source")))
    # ...and clamps rather than wrapping: an end you can fall off loses your place.
    for _ in range(6):
        APP.metaObject().invokeMethod(APP, "stepOutput", Q_ARG("QVariant", -1))
    spin(120)
    check("...and clamps at the top instead of wrapping",
          APP.property("selOne") == ctl.gallery.pathAt(0), APP.property("selOne"))

    # Zoom. Fit never upscales, so a small fixture sits below 1.0 and Actual
    # Size is a real change rather than a no-op.
    out.metaObject().invokeMethod(out, "zoomFit")
    spin(80)
    check("fit is the default and reports itself", out.property("fitting") is True)
    out.metaObject().invokeMethod(out, "zoomActual")
    spin(80)
    check("actual size is 1:1", abs(out.property("scaleNow") - 1.0) < 1e-6,
          out.property("scaleNow"))
    before = out.property("scaleNow")
    out.metaObject().invokeMethod(out, "zoomIn")
    spin(80)
    check("zoom in enlarges", out.property("scaleNow") > before,
          (before, out.property("scaleNow")))
    out.metaObject().invokeMethod(out, "zoomOut")
    spin(80)
    check("...and zoom out puts it back",
          abs(out.property("scaleNow") - before) < 1e-6, out.property("scaleNow"))

    # A different output starts fitted again rather than carrying a 4x zoom.
    out.metaObject().invokeMethod(out, "zoomActual")
    APP.metaObject().invokeMethod(APP, "stepOutput", Q_ARG("QVariant", 1))
    spin(120)
    check("a different output starts fitted", out.property("fitting") is True)

    # BACK AND FORWARD, the two keys that mean this everywhere else: Back leaves
    # the output for the grid he was on, Forward returns to it.
    seen = APP.property("selOne")
    APP.metaObject().invokeMethod(APP, "tbAction", Q_ARG("QVariant", "back"))
    spin(150)
    check("Back leaves View, keeping the place in the grid",
          APP.property("inView") is False and APP.property("selOne") == seen,
          (APP.property("inView"), APP.property("selOne")))
    APP.metaObject().invokeMethod(APP, "tbAction", Q_ARG("QVariant", "forward"))
    spin(150)
    check("...and Forward goes back to that same output",
          APP.property("inView") is True and APP.property("selOne") == seen,
          (APP.property("inView"), APP.property("selOne")))

    # An output with no recorded source has nothing to compare against, so the
    # slider stays out of the way whatever the toggle says.
    check("a plain output does not show the compare slider",
          out.property("beforePath") == "" and out.property("comparing") is False,
          (out.property("beforePath"), out.property("comparing")))

    QTest.keyClick(win, Qt.Key_Escape)
    spin(150)
    check("Escape leaves View for the grid",
          APP.property("inView") is False and gal.isVisible() and not out.isVisible(),
          (APP.property("inView"), gal.isVisible(), out.isVisible()))

    for pth in paths:
        try: os.remove(pth)
        except OSError: pass
    ctl.gallery.load_existing()
    spin(120)


def test_compare_and_columns(win, ctl, tmp):
    """The before/after slider, the compare row's visibility, and the grid's
    column count — the three View-side answers to a question about ONE output
    rather than about the set of them.
    """
    import main as P

    from PySide6.QtGui import QColor, QImage

    content = win.contentItem()
    out = find(content, "OutputView")
    grid = find(content, "KineticGridView")

    # A real before-image on disk, and an edit output that names it.
    before = os.path.join(tmp, "before-src.png")
    im = QImage(64, 48, QImage.Format_RGB32)
    im.fill(QColor("#3050a0"))
    im.save(before)
    edit = fake_png(os.path.join(tmp, "out", "painter-edit_00001_.png"),
                    {"positive": "make it night", "edit": True, "kind": "edit",
                     "input_image_local": before, "steps": 8})
    plain = fake_png(os.path.join(tmp, "out", "plain_00001_.png"),
                     {"positive": "a plain output", "steps": 9})
    for pth in (before, edit, plain):
        pass
    ctl.gallery.add(plain)
    ctl.gallery.add(edit)
    spin(200)

    def rows():
        return [r for r in prop(APP, "actions") if isinstance(r, dict)]

    def has_compare():
        return any(r.get("id") == "compare" for r in rows())

    # --- generate stays live while a job runs, so a second can be queued ---
    was_busy = ctl._busy
    ctl._busy = True
    ctl.busyChanged.emit()
    spin(120)
    gen = [r for r in rows() if r.get("id") == "gen"]
    check("generate is still offered while a job runs (so it can be queued)",
          bool(gen) and gen[0].get("state") == 0,
          gen[0].get("state") if gen else None)
    ctl._busy = was_busy
    ctl.busyChanged.emit()
    spin(120)

    # --- the compare row is only offered where it can do something ---------
    APP.metaObject().invokeMethod(APP, "enterView", Q_ARG("QVariant", edit))
    spin(250)
    check("an edit output can be compared",
          APP.property("canCompare") is True
          and out.property("beforePath") == before
          and out.property("comparing") is True,
          (APP.property("canCompare"), out.property("beforePath"),
           out.property("comparing")))
    check("...so the compare row is offered", has_compare())
    cv = find(out, "CompareView")
    check("...and the slider is the thing on screen",
          cv is not None and cv.isVisible() is True,
          None if cv is None else cv.isVisible())

    APP.metaObject().invokeMethod(APP, "enterView", Q_ARG("QVariant", plain))
    spin(250)
    check("a plain output has nothing to compare",
          APP.property("canCompare") is False
          and out.property("comparing") is False,
          (APP.property("canCompare"), out.property("comparing")))
    check("...so the compare row is not offered at all", not has_compare())

    # --- the status bar says what the viewed output IS ---------------------
    check("View reports the output's pixels in the status bar",
          out.property("infoText") == "1x1"
          and str(APP.property("statusRight")).startswith("1x1"),
          (out.property("infoText"), APP.property("statusRight")))
    APP.metaObject().invokeMethod(APP, "tbAction", Q_ARG("QVariant", "back"))
    spin(150)
    check("...and says nothing about one over the grid",
          "1x1" not in str(APP.property("statusRight")),
          APP.property("statusRight"))

    # --- the column count ---------------------------------------------------
    auto = grid.property("cols")
    APP.metaObject().invokeMethod(APP, "tbAction", Q_ARG("QVariant", "cols3"))
    spin(200)
    check("choosing 3 columns lays out 3",
          APP.property("gridColumns") == 3 and grid.property("cols") == 3,
          (APP.property("gridColumns"), grid.property("cols"),
           grid.property("cellWidth")))
    APP.metaObject().invokeMethod(APP, "tbAction", Q_ARG("QVariant", "cols0"))
    spin(200)
    check("...and automatic puts the width-driven count back",
          APP.property("gridColumns") == 0 and grid.property("cols") == auto,
          (grid.property("cols"), auto))

    # --- the before-copy filed beside the output ---------------------------
    # It is what makes an edit comparable after its source has moved — and, on
    # book, what makes one generated on top comparable at all.
    P.Painter._keep_before(Path(edit), {"edit": True, "input_image_local": before})
    kept = P.Painter._before_dir(Path(edit)) / "painter-edit_00001_.png"
    check("an edit files a copy of its source beside the output", kept.is_file(),
          str(kept))
    os.remove(before)
    check("...and the slider still finds a before when the source has gone",
          ctl.compareSource(edit) == str(kept), ctl.compareSource(edit))
    check("a plain output still compares against nothing",
          ctl.compareSource(plain) == "", ctl.compareSource(plain))

    for pth in (edit, plain):
        try:
            os.remove(pth)
        except OSError:
            pass
    try:
        os.remove(kept)
    except OSError:
        pass
    ctl.gallery.load_existing()
    spin(150)


def test_inject(win, ctl, tmp):
    """Left-click an output -> inject all / prompt / params."""
    params = {"positive": "injected positive, (injected negative:-1)", "negative": "",
              "prompt_boxes": {"positive": "injected positive",
                               "negative": "injected negative"},
              "steps": 44, "cfg": 3.5, "denoise": 0.5, "sampler_name": "heun",
              "scheduler": "beta", "seed": 99, "width": 1216, "height": 832,
              "batch_size": 2,
              "toggles": {"negpip": True, "model_sampling": False}}
    path = fake_png(os.path.join(tmp, "out", "shot.png"), params)
    ctl.gallery.add(path)
    spin(150)
    check("the gallery has the image", ctl.gallery.rowCount() == 1, ctl.gallery.rowCount())

    gal = find(win.contentItem(), "GalleryView")
    items = gal.metaObject().invokeMethod(gal, "menuFor", Q_ARG("QVariant", 0),
                                          Q_ARG("QVariant", path))
    # invokeMethod cannot return a JS array to Python, so drive the menu the way
    # a click does and read what the shared CtxMenu was handed.
    menu = find(win.contentItem(), "CtxMenu")
    grid = find(gal, "KineticGridView")
    cell = None
    for c in walk(grid):
        if c.metaObject().className().startswith("QQuickItem") and c.width() == grid.property("cellWidth"):
            cell = c
            break
    if cell is not None:
        from PySide6.QtCore import Qt
        OPENED.clear()
        pv = find(win.contentItem(), "PreviewPane")
        click(win, cell, dx=cell.width() / 2, dy=cell.height() / 2)
        spin(150)
        # A single click does NOTHING: no menu, no launch, and no reaching into
        # the preview pane, which follows the running job and nothing else.
        check("a single left click on an output does nothing",
              not menu.isVisible() and not OPENED, (menu.isVisible(), OPENED))
        doubleclick(win, cell)
        spin(200)
        # IN-APP NOW: a double-click enters View on that output rather than
        # launching `viewer`. The external tool is still one row down the
        # right-click menu and in the File menu.
        check("double-clicking it enters View on that output",
              APP.property("inView") is True and APP.property("selOne") == path,
              (APP.property("inView"), APP.property("selOne")))
        check("...without launching the external viewer", not OPENED, OPENED)
        APP.setProperty("inView", False)
        spin(120)
        click(win, cell, dx=cell.width() / 2, dy=cell.height() / 2, button=Qt.RightButton)
        spin(150)
        labels = [i.get("label") for i in (prop(menu, "items") or []) if i.get("label")]
        check("right-clicking one opens the menu", menu.isVisible(), menu.isVisible())
        check("...offering inject all / prompt / params",
              labels[:3] == ["inject all", "inject prompt", "inject params"], labels)
        menu.metaObject().invokeMethod(menu, "close")
        spin(60)

    # The three actions, called the way the menu calls them.
    base = prop(APP, "gen")
    base["positive"] = "before"; base["steps"] = 7; base["aspectW"] = 1; base["aspectH"] = 1
    APP.setProperty("gen", base)
    spin(60)

    APP.metaObject().invokeMethod(APP, "injectPrompt", Q_ARG("QVariant", params))
    spin(120)
    g = prop(APP, "gen")
    check("inject prompt takes the words", g["positive"] == "injected positive"
          and g["negative"] == "injected negative", (g["positive"], g["negative"]))
    check("...and leaves the numbers alone", g["steps"] == 7, g["steps"])

    APP.metaObject().invokeMethod(APP, "injectParams", Q_ARG("QVariant", params))
    spin(120)
    g = prop(APP, "gen")
    check("inject params takes the numbers",
          (g["steps"], g["cfg"], g["sampler_name"], g["seed"], g["randomSeed"])
          == (44, 3.5, "heun", 99, False),
          (g["steps"], g["cfg"], g["sampler_name"], g["seed"], g["randomSeed"]))
    check("...including the size, as aspect + MP",
          (g["aspectW"], g["aspectH"]) == (19, 13) and (g["width"], g["height"]) == (1216, 832),
          (g["aspectW"], g["aspectH"], g["width"], g["height"]))

    base = prop(APP, "gen"); base["positive"] = "before"; base["steps"] = 7
    APP.setProperty("gen", base); spin(60)
    APP.metaObject().invokeMethod(APP, "injectAll", Q_ARG("QVariant", params))
    spin(120)
    g = prop(APP, "gen")
    check("inject all takes both", g["positive"] == "injected positive" and g["steps"] == 44,
          (g["positive"], g["steps"]))


def QtBuffer():
    from PySide6.QtCore import QBuffer
    return QBuffer()


def QtIODeviceWriteOnly():
    from PySide6.QtCore import QIODevice
    return QIODevice.OpenModeFlag.WriteOnly


def test_peer_history(win, ctl, tmp):
    """The history is BOTH machines': top's output root is globbed beside the
    local one, and the file that is in both appears once."""
    import main as P

    peer = os.path.join(tmp, "peer-out")
    os.makedirs(os.path.join(peer, "video"), exist_ok=True)
    check("the peer root is wired up", [str(p) for p in P.PEER_OUTS] == [peer],
          P.PEER_OUTS)

    # Only on top: something book never downloaded.
    fake_png(os.path.join(peer, "peer_00001_.png"), {"positive": "made on top"})
    # In BOTH, and DIFFERENT SIZES — which is the real shape of it: book injects
    # painter's parameter chunk into the copy it writes and top's has none, so
    # a dedupe keyed on size would show this twice.
    both = "both_00001_.png"
    fake_png(os.path.join(peer, both), {"positive": "top's chunkless copy"})
    fake_png(os.path.join(tmp, "out", both), {"positive": "the local copy",
                                              "steps": 33, "cfg": 1.5})
    # A derivative on the far side stays a derivative.
    for f in ("peer_00002_.mp4", "peer_00002_-muted.mp4"):
        with open(os.path.join(peer, "video", f), "wb") as fh:
            fh.write(b"\0" * 64)

    ctl.gallery.load_existing()
    spin(200)
    names = [ctl.gallery.data(ctl.gallery.index(i, 0), P.Gallery.NameRole)
             for i in range(ctl.gallery.rowCount())]
    check("top's own output is in book's history", "peer_00001_.png" in names, names)
    check("...and its clip too", "peer_00002_.mp4" in names, names)
    check("...but not the clip's muted copy", "peer_00002_-muted.mp4" not in names, names)
    check("the file both machines hold appears ONCE",
          names.count(both) == 1, names)

    # ...and the one that survived is the LOCAL one, which is the only copy with
    # painter's parameters in it — dedupe order is what makes "inject" work.
    row = names.index(both)
    check("...and it is the local copy",
          ctl.gallery.pathAt(row) == os.path.join(tmp, "out", both),
          ctl.gallery.pathAt(row))
    p = ctl.gallery.paramsAt(row)
    check("...so its parameters are readable", p and p.get("steps") == 33, p)

    # A result landing mid-session replaces top's copy of itself rather than
    # sitting beside it: the backend wrote one there the instant it made it.
    fresh = "fresh_00001_.png"
    fake_png(os.path.join(peer, fresh), {"positive": "top's"})
    ctl.gallery.load_existing()
    spin(150)
    before = ctl.gallery.rowCount()
    ctl.gallery.add(fake_png(os.path.join(tmp, "out", fresh), {"positive": "book's"}))
    spin(120)
    names = [ctl.gallery.data(ctl.gallery.index(i, 0), P.Gallery.NameRole)
             for i in range(ctl.gallery.rowCount())]
    check("a finished job does not land beside top's copy of itself",
          ctl.gallery.rowCount() == before and names.count(fresh) == 1,
          (before, ctl.gallery.rowCount(), names.count(fresh)))
    check("...and it is the local copy that is showing",
          ctl.gallery.pathAt(names.index(fresh)) == os.path.join(tmp, "out", fresh),
          ctl.gallery.pathAt(names.index(fresh)))

    # An unmounted peer root — the tunnel down, or this is top — costs nothing.
    P.PEER_OUTS = [P.Path(tmp) / "not-mounted"]
    ctl.gallery.load_existing()
    spin(150)
    names = [ctl.gallery.data(ctl.gallery.index(i, 0), P.Gallery.NameRole)
             for i in range(ctl.gallery.rowCount())]
    check("a peer root that is not there does not cost the local scan",
          fresh in names and "peer_00001_.png" not in names, names)
    P.PEER_OUTS = [P.Path(peer)]


def test_copy_prompt(win, ctl, tmp):
    """Right-click -> copy prompt: the words out of the FILE, onto the
    clipboard, through a holder that outlives painter."""
    import main as P

    params = {"positive": "a lighthouse in a storm", "negative": "blurry",
              "steps": 12, "seed": 4242}
    path = fake_png(os.path.join(tmp, "out", "prompt_00001_.png"), params)
    ctl.gallery.add(path)
    spin(120)
    check("the new output is at the top of the history",
          ctl.gallery.indexOf(path) == 0, ctl.gallery.indexOf(path))

    # Read the menu the way test_inject does — through a real right-click,
    # `menuFor` returning a JS array that cannot cross into Python. BY POSITION,
    # not by creation order: delegates are recycled, so "the first cell `walk`
    # finds" is whichever item the view happened to reuse, and row 0 is the one
    # drawn top-left.
    from PySide6.QtCore import Qt
    gal = find(win.contentItem(), "GalleryView")
    menu = find(win.contentItem(), "CtxMenu")
    grid = find(gal, "KineticGridView")
    grid.setProperty("contentY", 0)
    spin(80)

    def row0_cell():
        cells = [c for c in walk(grid)
                 if c.metaObject().className().startswith("QQuickItem")
                 and c.width() == grid.property("cellWidth")]
        if not cells:
            return None
        return min(cells, key=lambda c: (round(c.y()), round(c.x())))

    def row0_menu():
        cell = row0_cell()
        if cell is None:
            return None
        click(win, cell, dx=cell.width() / 2, dy=cell.height() / 2, button=Qt.RightButton)
        spin(150)
        out = [i.get("label") for i in (prop(menu, "items") or []) if i.get("label")]
        menu.metaObject().invokeMethod(menu, "close")
        spin(60)
        return out

    labels = row0_menu()
    if labels is not None:
        check("a still with a prompt offers to copy it",
              "copy prompt" in labels, labels)
        check("...below the inject items, beside the other copy-outs",
              labels.index("copy prompt") > labels.index("inject params"), labels)
        check("an output with a fixed seed offers to copy it",
              "copy seed" in labels, labels)

    RAN.clear()
    ctl.copyPrompt(path)
    spin(150)
    copied = [r for r in RAN if os.path.basename(r[0]) == "wl-copy"]
    check("copy prompt puts the file's own words on the clipboard",
          copied and copied[-1][-1] == params["positive"], RAN)
    check("...with no newline glued to the end", copied and "-n" in copied[-1],
          copied[-1] if copied else RAN)

    RAN.clear()
    ctl.copySeed(path)
    spin(150)
    copied = [r for r in RAN if os.path.basename(r[0]) == "wl-copy"]
    check("copy seed puts only the recorded number on the clipboard",
          copied and copied[-1][-1] == "4242", RAN)
    check("...with no newline glued to the end",
          copied and "-n" in copied[-1], copied[-1] if copied else RAN)

    # A PNG that never went through painter has no prompt to give, and must say
    # so rather than put an empty selection over whatever was on the clipboard.
    plain = noisy_png(os.path.join(tmp, "out", "plain_00001_.png"), 4, 4)
    RAN.clear()
    ctl.copyPrompt(plain)
    spin(120)
    check("...and a file with no prompt copies nothing",
          not [r for r in RAN if os.path.basename(r[0]) == "wl-copy"], RAN)

    # ...and the same for a clip that carries no metadata at all: a video with
    # its own tag IS offered the prompt (test_clip_params), one with nothing in
    # it is not.
    vid = os.path.join(tmp, "out", "video", "noprompt_00001_.mp4")
    os.makedirs(os.path.dirname(vid), exist_ok=True)
    with open(vid, "wb") as fh:
        fh.write(b"\0" * 64)
    ctl.gallery.add(vid)
    spin(200)
    labels = row0_menu()
    if labels is not None:
        check("a clip with no metadata is not offered a prompt to copy",
              "copy prompt" not in labels, labels)
    os.unlink(vid)
    os.unlink(plain)


def test_clip_params(win, ctl, tmp):
    """A CLIP hands back its job exactly as a still does.

    Three sources, one entry point (`outmeta.params_for`): painter's own MP4
    tag, ComfyUI's graph for a clip that predates it, and nothing at all. The
    tag is written by the same `mp4meta.upsert_tags` the download path uses, so
    this also pins that a real ffmpeg-written file survives it — the metadata
    grows `moov` ahead of the media, and every chunk offset in the file has to
    move with it or the clip decodes to nothing.
    """
    import json as J
    import subprocess as sp
    import mp4meta
    import main as P

    vid_dir = os.path.join(tmp, "out", "video")
    os.makedirs(vid_dir, exist_ok=True)
    src = os.path.join(vid_dir, "src_00001_.mp4")
    try:
        sp.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                "-i", "testsrc=size=160x120:rate=12:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-pix_fmt", "yuv420p", "-shortest", src], check=True, timeout=60)
        before = sp.run(["ffmpeg", "-v", "error", "-i", src, "-map", "0:v", "-f", "md5", "-"],
                        capture_output=True, text=True, timeout=60).stdout
    except (OSError, sp.SubprocessError):
        check("ffmpeg is there to make a test clip", False, "skipped")
        return

    params = {"kind": "video", "positive": "a clip of the sea", "negative": "",
              "steps": 31, "denoise": 0.9, "sampler_name": "res_multistep",
              "scheduler": "simple", "seed": 4242, "duration": 6.6, "fps": 24.0,
              "megapixels": 0.6, "use_input_image": True, "use_last_frame": False,
              "input_image_local": os.path.join(tmp, "gone.png")}
    raw = open(src, "rb").read()
    tagged = os.path.join(vid_dir, "tagged_00001_.mp4")
    with open(tagged, "wb") as fh:
        fh.write(mp4meta.upsert_tags(raw, {"painter": J.dumps(params)}))
    after = sp.run(["ffmpeg", "-v", "error", "-i", tagged, "-map", "0:v", "-f", "md5", "-"],
                   capture_output=True, text=True, timeout=60).stdout
    check("writing the tag leaves the pictures byte-identical",
          bool(before) and before == after, (before.strip(), after.strip()))
    check("...and the tag reads back off the file",
          (mp4meta.read_tags_path(tagged).get("painter") or "").startswith("{"),
          sorted(mp4meta.read_tags_path(tagged)))
    # Twice is once: a second write replaces the key rather than adding a second.
    twice = mp4meta.upsert_tags(open(tagged, "rb").read(), {"painter": J.dumps(params)})
    check("...and a second write leaves one painter key",
          list(mp4meta.read_tags(twice)).count("painter") == 1,
          sorted(mp4meta.read_tags(twice)))

    ctl.gallery.add(tagged)
    spin(150)
    got = ctl.gallery.paramsAt(ctl.gallery.indexOf(tagged))
    check("a clip's own tag reaches paramsAt",
          bool(got) and got.get("positive") == params["positive"] and got.get("steps") == 31,
          got and sorted(got))

    # The menu offers a clip everything it offers a still, plus the muted copy.
    from PySide6.QtCore import Qt
    gal = find(win.contentItem(), "GalleryView")
    menu = find(win.contentItem(), "CtxMenu")
    grid = find(gal, "KineticGridView")
    grid.setProperty("contentY", 0)
    spin(80)
    cells = [c for c in walk(grid)
             if c.metaObject().className().startswith("QQuickItem")
             and c.width() == grid.property("cellWidth")]
    if cells:
        cell = min(cells, key=lambda c: (round(c.y()), round(c.x())))
        click(win, cell, dx=cell.width() / 2, dy=cell.height() / 2, button=Qt.RightButton)
        spin(150)
        labels = [i.get("label") for i in (prop(menu, "items") or []) if i.get("label")]
        menu.metaObject().invokeMethod(menu, "close")
        spin(60)
        check("a clip is offered inject all / prompt / params",
              labels[:3] == ["inject all", "inject prompt", "inject params"], labels)
        check("...and its own prompt to copy, beside the muted copy",
              "copy prompt" in labels and "copy muted copy" in labels, labels)

    RAN.clear()
    ctl.copyPrompt(tagged)
    spin(150)
    copied = [r for r in RAN if os.path.basename(r[0]) == "wl-copy"]
    check("copy prompt takes the words out of the CLIP",
          copied and copied[-1][-1] == params["positive"], RAN)

    # Injecting a clip's settings: the video controls, not the image ones.
    base = prop(APP, "gen")
    base["duration"] = 5.0; base["fps"] = 16.0; base["megapixels"] = 1.0
    base["useInputImage"] = True; base["useLastFrame"] = True
    APP.setProperty("gen", base)
    spin(60)
    APP.metaObject().invokeMethod(APP, "injectParams", Q_ARG("QVariant", got))
    spin(150)
    g = prop(APP, "gen")
    check("inject params takes a clip's seconds, frame rate and budget",
          (g["duration"], g["fps"], g["megapixels"]) == (6.6, 24.0, 0.6),
          (g["duration"], g["fps"], g["megapixels"]))
    check("...and a frame whose picture has gone comes back OFF",
          g["useInputImage"] is False and g["useLastFrame"] is False,
          (g["useInputImage"], g["useLastFrame"]))

    # ...and comes back ON, with the picture, when the file is still there.
    here = noisy_png(os.path.join(tmp, "first-frame.png"), 8, 8)
    got["input_image_local"] = here
    APP.metaObject().invokeMethod(APP, "injectParams", Q_ARG("QVariant", got))
    spin(150)
    g = prop(APP, "gen")
    check("a first frame that is still on disk comes back with the settings",
          g["useInputImage"] is True and ctl.inputImage == here,
          (g["useInputImage"], ctl.inputImage))

    # A clip from before painter wrote its own tag: ComfyUI's graph is read.
    graph = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "mini-video.safetensors"}},
             "20": {"class_type": "MiniMaxH3ImageToVideo",
                    "inputs": {"prompt": "the old way", "length": 158,
                               "first_frame": ["10", 0]}},
             "21": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
             "22": {"class_type": "BasicScheduler",
                    "inputs": {"scheduler": "beta", "steps": 17, "denoise": 1.0}},
             "23": {"class_type": "RandomNoise", "inputs": {"noise_seed": 777}},
             "11": {"class_type": "ImageScaleToTotalPixels",
                    "inputs": {"megapixels": 0.6, "resolution_steps": 32}},
             "32": {"class_type": "CreateVideo", "inputs": {"fps": 24.0}}}
    legacy = os.path.join(vid_dir, "legacy_00001_.mp4")
    with open(legacy, "wb") as fh:
        fh.write(mp4meta.upsert_tags(raw, {"prompt": J.dumps(graph)}))
    old = P.outmeta.params_for(legacy)
    check("a clip with only ComfyUI's graph still gives up its prompt",
          bool(old) and old.get("positive") == "the old way", old and sorted(old))
    check("...and its sampling numbers, seed and duration",
          old and (old.get("steps"), old.get("sampler_name"), old.get("scheduler"),
                   old.get("seed"), old.get("duration"), old.get("megapixels"))
          == (17, "euler", "beta", 777, 6.6, 0.6),
          old and {k: old.get(k) for k in
                   ("steps", "sampler_name", "scheduler", "seed", "duration")})
    check("...but claims no first frame it cannot put back",
          old and old.get("use_input_image") is True and not old.get("input_image_local"),
          old and old.get("input_image_local"))

    for p in (src, tagged, legacy):
        os.unlink(p)
    ctl.gallery.load_existing()
    spin(150)


def test_muted(win, ctl, tmp):
    """A muted copy is a derivative: hidden from the history, reused, and put
    on the clipboard as a file URI rather than as pixels."""
    import main as P

    vid = os.path.join(tmp, "out", "video")
    os.makedirs(vid, exist_ok=True)
    clip = os.path.join(vid, "clip_00001_.mp4")
    muted = os.path.join(vid, "clip_00001_-muted.mp4")
    for f in (clip, muted):
        with open(f, "wb") as fh:
            fh.write(b"\0" * 64)
    os.utime(muted, (time.time() + 5, time.time() + 5))   # newer than its source

    ctl.gallery.load_existing()
    spin(150)
    names = [ctl.gallery.data(ctl.gallery.index(i, 0), P.Gallery.NameRole)
             for i in range(ctl.gallery.rowCount())]
    check("the clip is in the history", "clip_00001_.mp4" in names, names)
    check("...and its muted copy is NOT", "clip_00001_-muted.mp4" not in names, names)
    ctl.gallery.add(muted)
    spin(60)
    check("...not even when one lands while running",
          ctl.gallery.rowCount() == len(names), ctl.gallery.rowCount())

    # The sampler's own preview frames: a real JPEG through the provider, and
    # the counter the QML Image's URL is built from moving with it.
    import main as P2
    from PySide6.QtGui import QImage
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    buf = QtBuffer()
    buf.open(QtIODeviceWriteOnly())
    img.save(buf, "JPG")
    ctl._busy = True
    before_tick = ctl.property("previewTick")
    ctl._on_preview(None, bytes(buf.data()), "jpeg")
    spin(60)
    check("a sampler preview frame reaches the image provider",
          ctl.property("previewTick") == before_tick + 1
          and ctl.property("hasPreview") is True
          and not ctl.preview.image.isNull(),
          (ctl.property("previewTick"), ctl.property("hasPreview")))
    # ...and every later frame lands too, not just the first: the pane draws
    # whichever one arrived last, and the tick is what makes its URL change.
    for _ in range(2):
        ctl._on_preview(None, bytes(buf.data()), "jpeg")
        spin(60)
    check("every frame reaches the pane, not just the first",
          ctl.property("previewTick") == before_tick + 3,
          ctl.property("previewTick"))
    ctl._busy = False
    check("...and a finished job stops claiming to have one",
          ctl.property("hasPreview") is False)

    # An existing, fresh copy is REUSED — asking twice must not leave three
    # files behind — and ffmpeg is never even started.
    before = sorted(os.listdir(vid))
    RAN.clear()
    ctl.copyMuted(clip)
    spin(200)
    check("an existing muted copy is reused, not remade",
          sorted(os.listdir(vid)) == before
          and not any(os.path.basename(a[0]) == "ffmpeg" for a in RAN),
          (sorted(os.listdir(vid)), RAN))
    copied = [a for a in RAN if a[-1].endswith("clip_00001_-muted.mp4")
              and os.path.basename(a[-2]) == "clipfile.py"]
    check("...and it is handed to clipfile, as a file",
          bool(copied), RAN)

    # Asking about a copy that is already muted copies THAT, not a copy of it.
    RAN.clear()
    ctl.copyMuted(muted)
    spin(150)
    copied = [a for a in RAN if os.path.basename(a[-2]) == "clipfile.py"]
    check("a muted file copies itself rather than making another",
          sorted(os.listdir(vid)) == before and bool(copied)
          and copied[-1][-1].endswith("clip_00001_-muted.mp4"),
          (sorted(os.listdir(vid)), copied))

    # ...and a clip with NO muted copy yet makes exactly one, with -c copy.
    RAN.clear()
    os.remove(muted)
    ctl.copyMuted(clip)
    spin(200)
    made = [a for a in RAN if os.path.basename(a[0]) == "ffmpeg"]
    check("a clip with no muted copy gets one made, without re-encoding",
          len(made) == 1 and "-c" in made[0] and "copy" in made[0]
          and made[0][-1].endswith("clip_00001_-muted.mp4"), made)
    os.remove(clip)
    ctl.gallery.load_existing()


def test_split_and_state(win, ctl, keep):
    """A draggable divider, and a window that comes back as it was left."""
    prefs = keep[2]
    content = win.contentItem()
    win.setWidth(1200)
    spin(120)
    left = find(content, "GalleryView").parentItem()
    before = APP.property("paneLeadW")

    APP.setProperty("splitRatio", 0.3)
    spin(120)
    before = APP.property("paneLeadW")
    APP.setProperty("splitRatio", 0.7)
    spin(120)
    after = APP.property("paneLeadW")
    check("the divider moves the panes", after > before + 100, (before, after))
    trail = find(content, "KineticFlickable",
                 pred=lambda it: find(it, "ModelPicker") is not None).parentItem()
    check("...and the trailing pane gives up exactly what the leading one took",
          abs((win.width() - after - APP.property("splitterW")) - trail.width()) < 1.5,
          (win.width(), after, trail.width()))

    # Clamps: neither side can be starved.
    APP.setProperty("splitRatio", 0.99)
    spin(120)
    check("the handle cannot starve the controls",
          win.width() - APP.property("paneLeadW") >= APP.property("minTrail"),
          win.width() - APP.property("paneLeadW"))
    APP.setProperty("splitRatio", 0.01)
    spin(120)
    check("...nor the results", APP.property("paneLeadW") >= APP.property("minLead"),
          APP.property("paneLeadW"))

    # State: everything the window is asked to remember.
    APP.setProperty("splitRatio", 0.55)
    APP.setProperty("view", 1)
    win.setWidth(1100); win.setHeight(800)
    g = prop(APP, "gen"); g["positive"] = "remember me"; g["steps"] = 23
    APP.setProperty("gen", g)
    panel = find(content, "ParamsPanel")
    panel.setProperty("collapsed", True)
    # A model setting that lives outside `gen`: the LoRA chain, cleared by
    # `selectModel` on every switch but supposed to survive a relaunch.
    ctl.loras.add("remember-lora.safetensors", False)
    ctl.loras.setStrength(0, 0.6)
    spin(200)
    APP.metaObject().invokeMethod(APP, "saveState")
    spin(200)

    check("the split is persisted", abs(prefs.get("splitRatio") - 0.55) < 1e-6,
          prefs.get("splitRatio"))
    check("the view is persisted", prefs.get("view") == 1, prefs.get("view"))
    check("the window size is persisted",
          (prefs.get("win.width"), prefs.get("win.height")) == (1100, 800),
          (prefs.get("win.width"), prefs.get("win.height")))
    saved = json.loads(prefs.get("gen") or "{}")
    check("the prompt and the numbers are persisted",
          saved.get("positive") == "remember me" and saved.get("steps") == 23,
          (saved.get("positive"), saved.get("steps")))
    check("a collapsed panel is persisted", prefs.get("panel.sampling") is True,
          prefs.get("panel.sampling"))
    check("the selected model is persisted", prefs.get("model") == ctl.property("selectedName"),
          prefs.get("model"))
    saved_loras = json.loads(prefs.get("loras") or "[]")
    check("the lora chain is persisted",
          saved_loras == [{"name": "remember-lora.safetensors", "strength": 0.6,
                            "enabled": True, "patchesClip": False}],
          saved_loras)
    # NOT un-collapsed here: the restore test reads the prefs file next, and
    # setting it back would (correctly) persist the newer value first.
    APP.setProperty("view", 0)
    win.setWidth(1280)
    spin(120)


def test_restore(tmp):
    """A SECOND window, same prefs file: it comes back the way it was left."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    import main as P

    # Same context objects, a fresh engine — as close to a relaunch as one
    # process can get.
    eng, win2, app2, ctl2, keep2 = build_window()
    check("restored: window size", (win2.width(), win2.height()) == (1100, 800),
          (win2.width(), win2.height()))
    check("restored: view", app2.property("view") == 1, app2.property("view"))
    check("restored: split ratio", abs(app2.property("splitRatio") - 0.55) < 1e-6,
          app2.property("splitRatio"))
    g = prop(app2, "gen")
    check("restored: the prompt", g["positive"] == "remember me", g["positive"])
    check("restored: the numbers survive the model's defaults landing",
          g["steps"] == 23, g["steps"])
    panel = find(win2.contentItem(), "ParamsPanel")
    check("restored: the collapsed panel", panel.property("collapsed") is True)
    check("restored: the selected model",
          ctl2.property("selectedName") == "alpha-model.safetensors",
          ctl2.property("selectedName"))
    # The saved chain named a LoRA that is not among this fixture root's files
    # (there are none), so `App.restoreLoras`'s on-disk guard must drop it
    # rather than the graph later referencing a file that is not there.
    check("restored: a lora no longer on disk is dropped, not carried over",
          ctl2.loras.rowCount() == 0, ctl2.loras.rowCount())
    app2.setProperty("restored", False)     # this window must not re-save
    win2.close()
    return eng, win2, ctl2, keep2


def test_done_toast(win, ctl, tmp):
    """A generation that lands while he is elsewhere says so on the desktop.

    Nothing here can reach a real notification server: `subprocess` is the
    harness's `_NoLaunch`, so `notify-send` is recorded in RAN and never run.
    The window is a stand-in with the two answers that decide it — `isActive`
    (focus) and `isExposed` (rolled up, minimised, another workspace).
    """
    import main as P

    class FakeWin:
        def __init__(self, active=True, exposed=True):
            self.active, self.exposed = active, exposed

        def isActive(self):
            return self.active

        def isExposed(self):
            return self.exposed

    fake = FakeWin()
    ctl.window = fake

    real_download = ctl.client.download
    ctl.client.download = lambda img, cb: cb(fake_png_bytes())

    class FakeJob:
        duration = 4.0

        def __init__(self, names):
            self.images = [{"filename": n, "subfolder": "video" if n.endswith(".mp4") else ""}
                           for n in names]
            self.meta = {"params": {"seed": 1}, "pairing": None}

    def batch(names, seconds=63.0):
        """Run one batch through the controller, as a press would."""
        RAN.clear()
        ctl._jobs = 1
        ctl._batch_start = time.time() - seconds
        ctl._batch_saved = []
        ctl._batch_pending = 0
        ctl._batch_toasted = False
        ctl._pending_toast = None
        ctl._on_finished(FakeJob(names))
        spin(80)
        return [a for a in RAN if os.path.basename(a[0]) == "notify-send"]

    # ---- he is watching: the window already said "done", so nothing else does
    fake.active, fake.exposed = True, True
    check("a finished batch is silent while the window is focused",
          not batch(["a_00001_.png"]), RAN)

    # ---- unfocused, and rolled up: the two ways he is not looking
    fake.active, fake.exposed = False, True
    sent = batch(["a_00002_.png"])
    check("an unfocused painter toasts the finished batch", len(sent) == 1, sent)
    args = sent[0] if sent else []
    check("...it says how long it took, in the queue bar's own clock",
          "completed in 1:03" in args, args)
    check("...and names the output it made",
          "a_00002_.png" in args, args)
    thumb = [a for a in args if a.startswith("string:x-download-image:")]
    check("...and carries the picture, so the toast thumbnails it",
          len(thumb) == 1 and thumb[0].endswith("/a_00002_.png")
          and os.path.exists(thumb[0].split(":", 2)[2]), (thumb, args))

    fake.active, fake.exposed = True, False
    sent = batch(["a_00003_.png"])
    check("a rolled-up painter toasts it too (isExposed, not focus)",
          len(sent) == 1, sent)

    # ---- one toast per batch, whatever it made
    fake.active, fake.exposed = False, True
    sent = batch(["b_00001_.png", "b_00002_.png"])
    check("a batch of four images is ONE toast, not four", len(sent) == 1, sent)
    check("...counting them, and naming the newest",
          any("2 outputs, newest b_00002_.png" == a for a in (sent[0] if sent else [])),
          sent)

    # ---- a clip cannot be thumbnailed: it waits for its poster frame.
    # Both halves are driven here rather than left to the real extraction: a
    # QML Image cannot decode an mp4 and ffmpeg's timing is not the harness's
    # to depend on (it wins the race about as often as it loses it).
    clip = os.path.join(tmp, "out", "video", "clip_00001_.mp4")
    poster = noisy_png(os.path.join(tmp, "cache", "painter", "posters",
                                    "clip_00001_.jpg"), 4, 4)
    real_want, real_ready = ctl.gallery._want_poster, ctl.gallery.poster_ready
    ctl.gallery._want_poster = lambda p: None          # no ffmpeg in this test
    ctl.gallery.poster_ready = lambda p: ""            # ...so none is ready yet

    sent = batch(["clip_00001_.mp4"])
    check("a clip's toast waits for the poster frame rather than going out bare",
          not sent and ctl._pending_toast is not None, (sent, ctl._pending_toast))
    ctl.gallery._poster_ready(clip, poster)            # the extraction lands
    spin(80)
    sent = [a for a in RAN if os.path.basename(a[0]) == "notify-send"]
    check("...and goes out when it lands", len(sent) == 1, sent)
    args = sent[0] if sent else []
    check("...thumbnailing the poster and opening the VIDEO (DESIGN 8.1)",
          "string:x-download-image:" + poster in args
          and "string:x-open-path:" + clip in args, args)

    # ...and a clip whose poster is already cached does not wait at all.
    ctl.gallery.poster_ready = lambda p: poster
    sent = batch(["clip_00002_.mp4"])
    check("a clip with its poster already cached toasts straight away",
          len(sent) == 1 and "string:x-download-image:" + poster in (sent[0] if sent else []),
          sent)
    ctl.gallery._want_poster, ctl.gallery.poster_ready = real_want, real_ready

    # ---- a failure is the one toast that batch gets
    sent = batch(["c_00001_.png"])
    check("a batch that finished already had its toast", len(sent) == 1, sent)
    RAN.clear()
    ctl._on_failed(None, "CUDA out of memory\nnode 12")
    spin(60)
    check("...so a later failure does not toast a second time",
          not [a for a in RAN if os.path.basename(a[0]) == "notify-send"], RAN)

    RAN.clear()
    ctl._jobs = 1
    ctl._batch_toasted = False
    ctl._batch_saved = []
    ctl._on_failed(None, "CUDA out of memory\nnode 12")
    spin(60)
    failed = [a for a in RAN if os.path.basename(a[0]) == "notify-send"]
    check("a batch that FAILED while he was away says so, critically",
          len(failed) == 1 and "generation failed" in failed[0]
          and "critical" in failed[0], failed)

    # ---- and a run with no window (every harness, including this one) is mute
    ctl.window = None
    check("no window means no toast at all", not batch(["d_00001_.png"]), RAN)

    ctl.window = fake
    fake.active, fake.exposed = True, True
    ctl.client.download = real_download
    ctl.window = None


def fake_png_bytes():
    """A real 1x1 PNG, as the backend would hand one back."""
    import zlib

    def chunk(t, body):
        return (struct.pack(">I", len(body)) + t + body
                + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b""))


def test_startup(ctl):
    """Nothing on the launch path may block the GUI thread."""
    import main as P
    slow = P.unit_cmd
    P.unit_cmd = lambda *v: ["sleep", "5"]
    t0 = time.time()
    ctl.startBackend()
    dt = time.time() - t0
    P.unit_cmd = slow
    check("startBackend returns immediately (does not wait on systemctl/ssh)",
          dt < 0.25, "%.2fs" % dt)
    for proc in list(ctl._procs):
        ctl._procs.remove(proc)
        proc.kill()
        proc.waitForFinished(500)
    t0 = time.time()
    ctl._refresh_unit()
    dt = time.time() - t0
    check("the unit poll returns immediately too", dt < 0.25, "%.2fs" % dt)


def test_wiring(win, ctl):
    """Every control in the left column reaches the submitted job."""
    sent = {}

    class FakeJob:
        def __init__(self):
            self.meta = {}

    def fake_build(entry, params, object_info=None):
        sent.update(params)
        return {"prompt": {}, "params": dict(params), "pairing": {}}

    def fake_submit(prompt, params):
        sent["_submitted"] = True
        return FakeJob()

    ctl._object_info = {"stub": True}
    if ctl.reg is None:
        print("SKIP  wiring audit (registry never built)")
        return
    ctl.reg.build = fake_build
    ctl.client.submit = fake_submit
    if ctl.models.rowCount() == 0:
        print("SKIP  wiring audit (no models in the scratch root)")
        return
    ctl._selected = 0

    gen = prop(APP, "gen")
    gen.update({
        "positive": "a prompt", "negative": "not this",
        "steps": 37, "cfg": 6.25, "denoise": 0.77,
        "sampler_name": "euler_ancestral", "scheduler": "karras",
        "seed": 4242, "randomSeed": False, "batch_size": 3, "count": 1,
        "aspectW": 3, "aspectH": 2, "megapixels": 1.0,
        "negpip": True, "modelSampling": True,
    })
    APP.setProperty("gen", gen)
    APP.metaObject().invokeMethod(APP, "recomputeDims")
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)

    g = prop(APP, "gen")
    want = {
        "positive": "a prompt", "negative": "not this", "steps": 37,
        "cfg": 6.25, "denoise": 0.77, "sampler_name": "euler_ancestral",
        "scheduler": "karras", "seed": 4242, "batch_size": 3,
        "width": g["width"], "height": g["height"],
    }
    for k, v in want.items():
        got = sent.get(k)
        ok = (abs(got - v) < 1e-6) if isinstance(v, float) and isinstance(got, (int, float)) \
            else got == v
        check("submitted %s" % k, ok, "sent=%r want=%r" % (got, v))
    tg = sent.get("toggles") or {}
    check("submitted toggles", tg.get("negpip") is True and tg.get("model_sampling") is True, tg)
    ms = sent.get("model_sampling") or {}
    check("submitted the model-sampling block", "shift_start" in ms, sorted(ms))
    check("the job was actually submitted", sent.get("_submitted") is True)


def test_seed(win, ctl):
    """A random batch's seed is remembered, and "reuse last" re-runs at it."""
    if ctl.reg is None or ctl.models.rowCount() == 0:
        print("SKIP  seed reuse (no registry/models)")
        return
    sent = {}

    class FakeJob:
        def __init__(self):
            self.meta = {}

    orig_build, orig_submit, orig_oi = ctl.reg.build, ctl.client.submit, ctl._object_info
    ctl.reg.build = lambda entry, params, object_info=None: (
        sent.clear() or sent.update(params)
        or {"prompt": {}, "params": dict(params), "pairing": {}})
    ctl.client.submit = lambda prompt, params: FakeJob()
    ctl._object_info = {"stub": True}
    ctl._selected = 0
    ctl.setMode("")
    spin(60)

    # A random batch rolls a seed AND remembers it.
    g = prop(APP, "gen")
    g.update({"randomSeed": True, "reuseSeed": False, "count": 1, "batch_size": 1})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    rolled = sent.get("seed")
    check("a random batch submits a concrete seed",
          isinstance(rolled, int) and rolled >= 0, rolled)
    check("...and App.lastSeed remembers exactly it",
          ctl.property("lastSeed") == rolled, (ctl.property("lastSeed"), rolled))

    # The visible control follows rgthree's three seed choices. They are QML
    # functions so this exercises the same writes the buttons make, without a
    # real desktop click.
    field = find(win.contentItem(), "SeedField")
    check("the shared seed field is present", field is not None)
    if field is not None:
        seed_spin = find(field, "SeedInput")
        sx, _sy, sw, _sh = scene_rect(seed_spin) if seed_spin is not None else (0, 0, 0, 0)
        fx, _fy, fw, _fh = scene_rect(field)
        check("the seed box spans the right-hand control column",
              seed_spin is not None and sx > fx and abs((sx + sw) - (fx + fw)) < 1,
              None if seed_spin is None else ((sx, sw), (fx, fw)))
        seed_input = (next((it for it in walk(seed_spin)
                            if it.property("objectName") == "seedTextInput"), None)
                      if seed_spin is not None else None)
        if seed_input is None and seed_spin is not None:
            seed_input = find(seed_spin, "QQuickTextInput")
        check("the seed editor can show more than one character",
              seed_input is not None and seed_input.width() > 100 and sw > 100,
              None if seed_input is None else (seed_input.width(), sw))
        seed_buttons = find_all(field, "TextButton")
        button_bounds = [scene_rect(b) for b in seed_buttons]
        check("the three seed buttons fit the controls column",
              len(button_bounds) == 3
              and min(x for x, _y, _w, _h in button_bounds) >= sx - 1
              and max(x + w for x, _y, w, _h in button_bounds) <= fx + fw + 1,
              button_bounds)
        labels = [b.property("label") for b in seed_buttons]
        check("the seed buttons use rgthree's three action faces",
              any("randomize each time" in str(x) for x in labels)
              and any("new fixed random" in str(x) for x in labels)
              and any(("use last queued seed" in str(x)) or (str(rolled) in str(x))
                      for x in labels), labels)

        # Clipboard is the offscreen platform's private clipboard. Exercise the
        # real right-click menu: an output's copied number has to be pasteable
        # into this box, not merely retrievable through Ctrl+V in theory.
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText("31337")
        seed_input.selectAll()
        # The sampling section can sit below the viewport when every preceding
        # panel is expanded. Put its real control on the offscreen window
        # before sending the right-click; QTest correctly refuses coordinates
        # outside that window.
        ancestor = field.parentItem()
        while ancestor is not None and not ancestor.metaObject().className().startswith("WheelScroll"):
            ancestor = ancestor.parentItem()
        if ancestor is not None:
            ancestor.setProperty("contentY", max(0, ancestor.property("contentHeight")
                                                  - ancestor.height()))
            spin(100)
        # Ctrl+V and the context-menu row both end at the editor's native paste
        # method. Calling it directly is the one route that can be exercised
        # identically for an in-scene menu and Plasma's separate popup window.
        seed_input.paste()
        spin(80)
        check("the seed box pastes a copied numeric seed",
              seed_input.property("text") == "31337", seed_input.property("text"))
        g = prop(APP, "gen")
        g.update({"seed": 123, "randomSeed": False, "reuseSeed": False})
        APP.setProperty("gen", g)
        spin(60)
        field.metaObject().invokeMethod(field, "randomSeed")
        spin(60)
        g = prop(APP, "gen")
        check("random writes -1 into the seed box",
              g.get("seed") == -1 and g.get("randomSeed") is True
              and g.get("reuseSeed") is False,
              {k: g.get(k) for k in ("seed", "randomSeed", "reuseSeed")})
        check("last appears when a different queued seed exists",
              field.property("lastAvailable") is True, field.property("lastAvailable"))
        last_button = find(field, "TextButton",
                           pred=lambda it: it.property("objectName") == "seedLast")
        check("last remains visible and enabled when it can restore a seed",
              last_button is not None and last_button.isVisible() and last_button.isEnabled(),
              None if last_button is None else (last_button.isVisible(), last_button.isEnabled()))
        field.metaObject().invokeMethod(field, "newFixedSeed")
        spin(60)
        g = prop(APP, "gen")
        fixed = g.get("seed")
        check("new fixed rolls one concrete seed",
              isinstance(fixed, (int, float)) and fixed >= 0 and float(fixed).is_integer()
              and g.get("randomSeed") is False and g.get("reuseSeed") is False,
              {k: g.get(k) for k in ("seed", "randomSeed", "reuseSeed")})
        check("new fixed puts that concrete seed in the visible box",
              seed_input is not None and seed_input.property("text") == str(int(fixed)),
              None if seed_input is None else seed_input.property("text"))
        field.metaObject().invokeMethod(field, "useLastSeed")
        spin(60)
        g = prop(APP, "gen")
        check("last restores the queued base seed as fixed",
              g.get("seed") == rolled and g.get("randomSeed") is False
              and g.get("reuseSeed") is False,
              {k: g.get(k) for k in ("seed", "randomSeed", "reuseSeed")})
        check("last puts the queued seed in the visible box",
              seed_input is not None and seed_input.property("text") == str(rolled),
              None if seed_input is None else seed_input.property("text"))
        check("last is unavailable when it would repeat the current seed",
              field.property("lastAvailable") is False, field.property("lastAvailable"))
        check("last stays visible but is disabled when it would repeat the seed",
              last_button is not None and last_button.isVisible() and not last_button.isEnabled(),
              None if last_button is None else (last_button.isVisible(), last_button.isEnabled()))

    # "reuse last" re-runs at that seed, overriding random, without drifting.
    g = prop(APP, "gen")
    g.update({"randomSeed": True, "reuseSeed": True})
    APP.setProperty("gen", g)
    spin(60)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(200)
    check("reuse re-runs at the remembered seed, overriding random",
          sent.get("seed") == rolled, (sent.get("seed"), rolled))
    check("...and reusing does not drift the remembered seed",
          ctl.property("lastSeed") == rolled, (ctl.property("lastSeed"), rolled))
    APP.metaObject().invokeMethod(APP, "materializeSeedPolicy")
    spin(60)
    g = prop(APP, "gen")
    check("a saved legacy reuse choice migrates to the visible last seed",
          g.get("seed") == rolled and g.get("randomSeed") is False
          and g.get("reuseSeed") is False,
          {k: g.get(k) for k in ("seed", "randomSeed", "reuseSeed")})
    g.update({"seed": 987, "randomSeed": True, "reuseSeed": False})
    APP.setProperty("gen", g)
    APP.metaObject().invokeMethod(APP, "materializeSeedPolicy")
    spin(60)
    g = prop(APP, "gen")
    check("a saved legacy random choice becomes the visible -1",
          g.get("seed") == -1 and g.get("randomSeed") is True
          and g.get("reuseSeed") is False,
          {k: g.get(k) for k in ("seed", "randomSeed", "reuseSeed")})

    ctl.reg.build, ctl.client.submit, ctl._object_info = orig_build, orig_submit, orig_oi
    # A STUBBED SUBMIT STILL QUEUES A ROW. `_start_jobs` puts the job in the
    # history the moment it is submitted (main.py, so the preview changes when
    # generate is pressed and not when the backend gets round to it), and a
    # stubbed client never finishes it — so the row is ended here rather than
    # left at the top of the grid for every test that follows.
    ctl.gallery.end_live()
    spin(60)


def test_preset_sampling(win, ctl, tmp):
    """Editing the sampler, switching model/preset away, and back, keeps it.

    applyDefaults() reapplies the checkpoint's own steps/sampler/scheduler on
    every arrival, which used to wipe an edited video sampler on a preset
    round-trip. The fix remembers each model's last sampling per name, so a
    switch back lands on what was edited, not the family default. Needs two
    models whose families actually declare sampler defaults (the alpha/beta
    fakes do not), so it stages the video model beside a krea2 checkpoint.
    """
    if ctl.reg is None:
        print("SKIP  preset sampling (no registry)")
        return
    root = os.environ["PAINTER_MODELS"]
    staged = dict(VIDEO_FAKES)
    staged["unet/krea2_raw_fp8_scaled.safetensors"] = \
        MODE_FAKES["unet/krea2_raw_fp8_scaled.safetensors"]
    for rel, keys in staged.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})
    ctl.setMode("")
    ctl.rescan()
    spin(200)

    ctl.selectModelByName("mini-video.safetensors")
    spin(150)
    if not (ctl.modelDefaults() or {}).get("steps") or not ctl.property("isVideo"):
        for rel in staged:
            try: os.remove(os.path.join(root, rel))
            except OSError: pass
        print("SKIP  preset sampling (video model not recognised)")
        return

    # Edit the video sampling to values that are nobody's default.
    edited = {"steps": 41, "denoise": 0.63,
              "sampler_name": "dpmpp_sde", "scheduler": "exponential"}
    g = prop(APP, "gen")
    g.update(edited)
    APP.setProperty("gen", g)
    spin(80)

    # Away to another preset: its defaults land, so the edits leave `gen`.
    ctl.selectModelByName("krea2_raw_fp8_scaled.safetensors")
    spin(150)
    away = prop(APP, "gen")
    check("switching preset away replaces the edited sampler",
          away.get("sampler_name") != "dpmpp_sde" or away.get("steps") != 41,
          (away.get("steps"), away.get("sampler_name")))

    # ...and back: the edited sampler is restored, not the checkpoint default.
    ctl.selectModelByName("mini-video.safetensors")
    spin(150)
    back = prop(APP, "gen")
    check("a preset round-trip restores the edited video sampler",
          back.get("steps") == 41 and back.get("denoise") == 0.63
          and back.get("sampler_name") == "dpmpp_sde"
          and back.get("scheduler") == "exponential",
          {k: back.get(k) for k in edited})

    for rel in staged:
        try: os.remove(os.path.join(root, rel))
        except OSError: pass
    fp.save_cache({})
    ctl.rescan()
    spin(120)


def test_section_order(win, ctl, tmp):
    """One section order for every preset AND model: input images, resolution,
    prompt boxes, LoRAs, then the sampler settings — top to bottom. The panels
    are gated per mode and a Column skips the invisible ones, so what stays
    visible must never reshuffle relative to that order.
    """
    if ctl.reg is None:
        print("SKIP  section order (no registry)")
        return
    content = win.contentItem()
    root = os.environ["PAINTER_MODELS"]
    staged = dict(MODE_FAKES)
    staged.update(VIDEO_FAKES)
    for rel, keys in staged.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})
    ctl.setMode("")
    ctl.rescan()
    spin(200)

    # input images -> resolution -> prompt -> LoRAs -> sampler settings
    RANK = {"EditPanel": 1, "VideoPanel": 1, "ResolutionPanel": 2,
            "EditScalePanel": 2, "PromptEditor": 3, "LoraStack": 4,
            "ParamsPanel": 5, "TogglePanel": 5, "SeedPanel": 5}

    def order_ok(label):
        rows = []
        for tp, rank in RANK.items():
            p = find(content, tp)
            if p is not None and p.isVisible():
                rows.append((prop(p, "y"), rank, tp))
        rows.sort()                                   # top to bottom
        ranks = [r for _, r, _ in rows]
        names = [n for _, _, n in rows]
        check("%s: sections in one order (input,res,prompt,lora,sampler)" % label,
              ranks == sorted(ranks), names)

    ctl.selectModelByName("krea2_raw_fp8_scaled.safetensors")
    spin(150)
    order_ok("image")

    ctl.setMode("video")
    spin(150)
    if ctl.property("isVideo"):
        order_ok("video")

    ctl.setMode("edit")
    spin(150)
    if ctl.property("isEdit"):
        order_ok("edit")

    ctl.setMode("")
    for rel in staged:
        try: os.remove(os.path.join(root, rel))
        except OSError: pass
    fp.save_cache({})
    ctl.rescan()
    spin(120)


def test_preset_isolation(win, ctl, tmp):
    """Each preset keeps its OWN settings — the whole gen, not just the sampler —
    across a switch away and back, and the per-model store is persisted so a
    relaunch shows each preset the way it was last left.
    """
    if ctl.reg is None:
        print("SKIP  preset isolation (no registry)")
        return
    root = os.environ["PAINTER_MODELS"]
    staged = {k: MODE_FAKES[k] for k in
              ("unet/anima-base-v1.0.safetensors",
               "unet/krea2_raw_fp8_scaled.safetensors")}
    for rel, keys in staged.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})
    ctl.setMode("")
    ctl.rescan()
    spin(200)

    ctl.selectModelByName("anima-base-v1.0.safetensors")
    spin(150)
    if ctl.property("selectedName") != "anima-base-v1.0.safetensors":
        for rel in staged:
            try: os.remove(os.path.join(root, rel))
            except OSError: pass
        fp.save_cache({}); ctl.rescan(); spin(120)
        print("SKIP  preset isolation (models not recognised)")
        return

    def edit(pos, aw, ah, mp, steps):
        g = prop(APP, "gen")
        g["positive"] = pos; g["aspectW"] = aw; g["aspectH"] = ah
        g["megapixels"] = mp; g["steps"] = steps
        APP.setProperty("gen", g)
        APP.metaObject().invokeMethod(APP, "recomputeDims")
        spin(80)

    edit("ANIMA", 3, 2, 1.7, 27)
    # Simulate the state written before Anima's transform gained its Danbooru
    # spelling/completion behaviour. This is family-owned wire grammar, never
    # a user preference: restoring it must not turn the feature back off.
    g = prop(APP, "gen")
    g["promptTransform"] = "single_line"
    APP.setProperty("gen", g)
    spin(80)
    # At relaunch restoreState() has already set defaultsFor to this model, so
    # the normal preset path is deliberately skipped. It must still migrate the
    # family-owned transform through that fast path.
    APP.metaObject().invokeMethod(APP, "applyDefaults")
    spin(80)
    check("restoring an already-current preset updates Anima's tag grammar",
          prop(APP, "gen").get("promptTransform") == "danbooru",
          prop(APP, "gen").get("promptTransform"))
    ctl.selectModelByName("krea2_raw_fp8_scaled.safetensors")
    spin(150)
    edit("KREA", 16, 9, 1.1, 33)

    # Back to the first preset: its OWN values, not the other's, not the default.
    ctl.selectModelByName("anima-base-v1.0.safetensors")
    spin(150)
    a = prop(APP, "gen")
    check("a preset round-trip restores the whole gen (prompt + resolution + steps)",
          a.get("positive") == "ANIMA" and a.get("aspectW") == 3
          and a.get("aspectH") == 2 and abs(a.get("megapixels") - 1.7) < 1e-6
          and a.get("steps") == 27,
          {k: a.get(k) for k in ("positive", "aspectW", "aspectH", "megapixels", "steps")})
    check("a stale preset cannot override Anima's Danbooru grammar",
          a.get("promptTransform") == "danbooru", a.get("promptTransform"))

    ctl.selectModelByName("krea2_raw_fp8_scaled.safetensors")
    spin(150)
    k = prop(APP, "gen")
    check("the other preset kept its own settings, unshared",
          k.get("positive") == "KREA" and k.get("aspectW") == 16
          and k.get("steps") == 33,
          {kk: k.get(kk) for kk in ("positive", "aspectW", "steps")})

    # Persisted for a relaunch: the on-disk store holds both presets' settings.
    APP.metaObject().invokeMethod(APP, "saveState")
    spin(60)
    prefs_path = os.path.join(os.environ["XDG_STATE_HOME"], "painter", "prefs.json")
    gbm = json.loads(json.load(open(prefs_path)).get("genByModel") or "{}")
    check("both presets are persisted for a relaunch",
          gbm.get("anima-base-v1.0.safetensors", {}).get("positive") == "ANIMA"
          and gbm.get("krea2_raw_fp8_scaled.safetensors", {}).get("positive") == "KREA",
          sorted(gbm.keys()))

    ctl.setMode("")
    for rel in staged:
        try: os.remove(os.path.join(root, rel))
        except OSError: pass
    fp.save_cache({})
    ctl.rescan()
    spin(120)


def test_tag_complete(win, ctl, keep):
    """Typing a tag offers the tag Danbooru actually HAS.

    [his, 2026-08-28] tag autocomplete "a la those comfyui extensions and what
    the og cte does". The vocabulary was already here — painter spells a written
    prompt with it on the way out (`pylib/boorutags`, `graph.danbooru_prompt`) —
    so what is checked here is the half that is new: the gate (a prose family
    gets no tag list at all), the index building OFF the GUI thread, the alias
    that makes a half-remembered tag land on the real one, and the four keys the
    list owns while it is open.
    """
    from PySide6.QtCore import Qt
    tags = keep[6]
    content = win.contentItem()
    box = find_all(content, "PromptBox")[0]
    edit = find(box, "QQuickTextEdit")
    popup = find(content, "TagPopup")
    check("the scene has one tag popup", popup is not None)
    if popup is None or ctl.reg is None:
        return

    # An anima model and a krea one, exactly as the preset tests stage them:
    # the gate is the FAMILY's `prompt_transform`, so the check needs a model
    # of each kind on disk.
    root = os.environ["PAINTER_MODELS"]
    staged = {k: MODE_FAKES[k] for k in
              ("unet/anima-base-v1.0.safetensors",
               "unet/krea2_raw_fp8_scaled.safetensors")}
    for rel, keys in staged.items():
        write_safetensors(os.path.join(root, rel), keys)
    import fingerprint as fp
    fp.save_cache({})
    ctl.setMode("")
    ctl.rescan()
    spin(200)

    def unstage():
        for rel in staged:
            try: os.remove(os.path.join(root, rel))
            except OSError: pass
        fp.save_cache({}); ctl.rescan(); spin(120)

    # --- the gate: tags are a DANBOORU-family feature ----------------------
    ctl.selectModelByName("krea2_raw_fp8_scaled.safetensors")
    spin(200)
    check("a prose family gets no completer at all",
          box.property("tagsOn") is False, prop(APP, "gen").get("promptTransform"))
    ctl.selectModelByName("anima-base-v1.0.safetensors")
    spin(200)
    if prop(APP, "gen").get("promptTransform") != "danbooru":
        print("SKIP  tag complete (models not recognised)")
        unstage()
        return
    check("...and a danbooru family gets one", box.property("tagsOn") is True,
          prop(APP, "gen").get("promptTransform"))

    # --- the index is built on a worker, and the app waits for nothing ------
    check("the vocabulary is on disk", tags.property("available") is True)
    tags.prepare()
    end = time.time() + 30
    while not tags.property("ready") and time.time() < end:
        spin(200)
    check("the tag index builds off the GUI thread",
          tags.property("ready") is True)

    def type_into(text):
        edit.forceActiveFocus()
        edit.setProperty("text", text)
        edit.setProperty("cursorPosition", len(text))
        spin(300)

    type_into("1gi")
    check("a prefix opens the list", popup.property("visible") is True)
    check("...on the tag the site actually has, most-used first",
          popup.property("currentTag") == "1girl", popup.property("currentTag"))

    # Return takes the highlighted row, and the comma comes with it: a tag list
    # is comma-separated and typing that by hand is the thing being automated.
    key(win, Qt.Key_Return)
    check("Return inserts the tag and its separator",
          edit.property("text") == "1girl, ", repr(edit.property("text")))
    check("...and closes the list", popup.property("visible") is False)
    check("...and does not immediately re-offer what it just wrote",
          prop(APP, "gen").get("positive") == "1girl, ",
          prop(APP, "gen").get("positive"))

    # An ALIAS is half the value: the tag a model half-remembers, resolved.
    type_into("sole_fem")
    check("an alias resolves to the canonical tag",
          popup.property("currentTag") == "1girl", popup.property("currentTag"))

    # Down walks the list; Escape dismisses it without letting go of the box.
    type_into("long_h")
    first = popup.property("currentTag")
    key(win, Qt.Key_Down)
    check("down walks the list", popup.property("currentTag") != first,
          (first, popup.property("currentTag")))
    key(win, Qt.Key_Escape)
    check("escape closes the list", popup.property("visible") is False)
    check("...and leaves the keyboard in the box",
          edit.property("activeFocus") is True)
    check("...and changes nothing about the text",
          edit.property("text") == "long_h", repr(edit.property("text")))

    # ONE CHARACTER IS ENOUGH — the list is post-count ordered, so the first
    # letter's answer is usually the tag meant. A whole clause is still prose
    # and not a misspelt tag, which `boorutags.check` reads the same way.
    type_into("s")
    check("one character already offers something",
          popup.property("visible") is True and popup.property("count") > 0,
          popup.property("currentTag"))
    type_into("a girl walks into the rain and")
    check("a written clause offers nothing", popup.property("visible") is False)

    # Underscores are the SITE's spelling; what lands in the box is what
    # `danbooru_prompt` would have sent (`graph.spell_tag`).
    type_into("long_h")
    key(win, Qt.Key_Tab)
    check("tab takes the row too, spelled the way it is sent",
          edit.property("text") == "long hair, ", repr(edit.property("text")))

    # THE COMMA AND THE SPACE COME WITH IT [his, 2026-08-28] — except where one
    # is already there, or where it would break what it is being typed into.
    edit.forceActiveFocus()
    edit.setProperty("text", "1girl, long_h, solo")
    edit.setProperty("cursorPosition", len("1girl, long_h"))
    spin(300)
    key(win, Qt.Key_Tab)
    check("a tag with a comma already after it gains no second one",
          edit.property("text") == "1girl, long hair, solo",
          repr(edit.property("text")))

    edit.setProperty("text", "(long_h:1.2)")
    edit.setProperty("cursorPosition", len("(long_h"))
    spin(300)
    key(win, Qt.Key_Tab)
    check("...and a weight group keeps its weight",
          edit.property("text") == "(long hair:1.2)", repr(edit.property("text")))

    edit.setProperty("text", "long_h\nsolo")
    edit.setProperty("cursorPosition", len("long_h"))
    spin(300)
    key(win, Qt.Key_Tab)
    check("...and the end of a line is no exception: comma AND space",
          edit.property("text") == "long hair, \nsolo", repr(edit.property("text")))

    # A typo still answers — the loose subsequence pass behind the strict one.
    type_into("lookingat")
    check("a typo still finds the tag",
          popup.property("currentTag") == "looking_at_viewer",
          popup.property("currentTag"))

    # ...and a tag already in the box is offered, marked as already there.
    edit.setProperty("text", "solo, sol")
    edit.setProperty("cursorPosition", len("solo, sol"))
    spin(300)
    rows_now = prop(popup, "items") or []
    have = [it for it in rows_now if it.get("tag") == "solo"]
    check("a tag already in the box is marked spent, not hidden",
          bool(have) and have[0].get("have") is True,
          [ (r.get("tag"), r.get("have")) for r in rows_now[:3] ])

    # --- what an ARTIST and a bracketed CHARACTER insert as ----------------
    # [his, 2026-08-28] "auto complete needs @ prepended to artists and
    # parentheticals escaped via a back slash".
    rows = tags.complete("toi8", 8)
    check("an artist is offered as an artist",
          bool(rows) and rows[0]["category"] == "artist", rows[:1])
    check("...and inserts with its @",
          bool(rows) and rows[0]["insert"] == "@toi8", rows[:1])
    rows = tags.complete("rebecca_(cyber", 8)
    hit = [r for r in rows if r["tag"] == "rebecca_(cyberpunk)"]
    check("a character keeps its series", bool(hit), [r["tag"] for r in rows[:3]])
    check("...and its brackets are escaped, or they open a weight group",
          bool(hit) and hit[0]["insert"] == "rebecca \\(cyberpunk\\)",
          hit[:1])

    # ...and the escaped brackets are not read as separators when completing
    # inside such a tag.
    type_into("rebecca \\(cyberp")
    check("an escaped bracket does not split the tag being typed",
          popup.property("currentTag") == "rebecca_(cyberpunk)",
          popup.property("currentTag"))
    key(win, Qt.Key_Tab)
    check("...and it completes as the whole name",
          edit.property("text") == "rebecca \\(cyberpunk\\), ",
          repr(edit.property("text")))

    # --- the caret is not a question --------------------------------------
    # [his, 2026-08-28] "what about how the cursor functions and moves around
    # and affects the autocomplete? it still feels loose". Typing asks for a
    # list; moving the caret does not, and Escape means "not for this tag".
    type_into("1girl, long_h")
    check("typing opens the list", popup.property("visible") is True)
    key(win, Qt.Key_Left)
    check("moving the caret closes it", popup.property("visible") is False)
    key(win, Qt.Key_Right)
    check("...and does not reopen it", popup.property("visible") is False)
    key(win, Qt.Key_A, Qt.NoModifier, "a")
    check("typing again does", popup.property("visible") is True)
    key(win, Qt.Key_Backspace)
    check("...and so does deleting", popup.property("visible") is True)
    key(win, Qt.Key_Escape)
    check("escape closes it for THIS tag", popup.property("visible") is False)
    key(win, Qt.Key_A, Qt.NoModifier, "a")
    check("...and typing more of the same tag leaves it closed",
          popup.property("visible") is False, edit.property("text"))
    key(win, Qt.Key_Comma, Qt.NoModifier, ",")
    key(win, Qt.Key_S, Qt.NoModifier, "s")
    key(win, Qt.Key_O, Qt.NoModifier, "o")
    check("...until the next tag, which is offered again",
          popup.property("visible") is True, edit.property("text"))
    key(win, Qt.Key_Escape)

    # --- ctrl+up / ctrl+down weight what is under the caret -----------------
    def caret_in(text, at):
        edit.forceActiveFocus()
        edit.setProperty("text", text)
        edit.setProperty("cursorPosition", at)
        spin(120)

    caret_in("1girl, long hair", len("1girl, long h"))
    key(win, Qt.Key_Up, Qt.ControlModifier)
    check("ctrl+up weights the tag under the caret",
          edit.property("text") == "1girl, (long hair:1.05)",
          repr(edit.property("text")))
    key(win, Qt.Key_Up, Qt.ControlModifier)
    check("...and again, in the SAME group rather than a nested one",
          edit.property("text") == "1girl, (long hair:1.10)",
          repr(edit.property("text")))
    key(win, Qt.Key_Down, Qt.ControlModifier)
    key(win, Qt.Key_Down, Qt.ControlModifier)
    check("...and 1.0 takes the group away again",
          edit.property("text") == "1girl, long hair", repr(edit.property("text")))
    key(win, Qt.Key_Down, Qt.ControlModifier)
    check("...and it goes below 1 as well",
          edit.property("text") == "1girl, (long hair:0.95)",
          repr(edit.property("text")))

    # A selection is what it acts on when there is one.
    edit.setProperty("text", "a girl in the rain")
    edit.metaObject().invokeMethod(edit, "select", Q_ARG(int, 2), Q_ARG(int, 6))
    spin(80)
    key(win, Qt.Key_Up, Qt.ControlModifier)
    check("...and a selection is weighted as one thing",
          edit.property("text") == "a (girl:1.05) in the rain",
          repr(edit.property("text")))

    edit.setProperty("text", "")
    spin(100)
    unstage()


def test_live_row(win, ctl, tmp):
    """The generation in flight is a ROW, and the preview shows what is SELECTED.

    [his, 2026-08-28] "make it so the preview element displays the currently
    selected output ... i propose that the preview of the current step of the
    currently processing generation get added to the history section and then
    get replaced with the full output when its finished". Which supersedes the
    pane's old rule ("no clicking on other outputs or anything") without losing
    it: the running job is one of the things that can be selected.
    """
    content = win.contentItem()
    view = find(content, "GalleryView")
    pane = find(content, "PreviewPane")
    APP.setProperty("showPreview", True)
    spin(120)

    made = [noisy_png(os.path.join(tmp, "out", "live_0000%d_.png" % i), 60, 40)
            for i in range(1, 4)]
    ctl.gallery.load_existing()
    spin(250)
    view.metaObject().invokeMethod(view, "clearSelection")
    spin(60)
    before = ctl.gallery.rowCount()
    newest = ctl.gallery.pathAt(0)
    check("with nothing selected the pane shows the newest output",
          pane.property("source") == newest, pane.property("source"))

    # --- a job starts: it takes row 0, and the selection follows it ---------
    ctl.gallery.begin_live("job-1")
    spin(150)
    check("a running job is a row in the history",
          ctl.gallery.rowCount() == before + 1 and ctl.gallery.isLiveAt(0) is True,
          (ctl.gallery.rowCount(), before))
    check("...that is not a file", ctl.gallery.pathAt(0) == P_LIVE, ctl.gallery.pathAt(0))
    check("...and the selection follows it",
          prop(view, "selection") == [P_LIVE], prop(view, "selection"))
    check("...so the pane is on the job, not on a file",
          pane.property("selLive") is True and pane.property("source") == "",
          (pane.property("selLive"), pane.property("source")))
    check("...and no verb that needs a file thinks one is selected",
          prop(APP, "selOne") == "", prop(APP, "selOne"))

    # A frame arrives: that is what the pane (and the tile) draw.
    ctl._busy = True
    with open(made[0], "rb") as fh:
        frame = fh.read()
    ctl._on_preview(None, frame, "png")
    spin(120)
    check("a sampler frame is what the pane draws",
          pane.property("showLive") is True, pane.property("showLive"))

    # --- and he can look at something else meanwhile -----------------------
    invoke_str(view, "selectSingle", made[2])
    spin(150)
    check("selecting an older output shows it instead",
          pane.property("source") == made[2] and pane.property("showLive") is False,
          (pane.property("source"), pane.property("showLive")))
    check("...and the running job is still there to go back to",
          ctl.gallery.isLiveAt(0) is True)

    invoke_str(view, "selectSingle", P_LIVE)
    spin(150)
    check("selecting the running job goes back to the frames",
          pane.property("showLive") is True and view.property("followLive") is True,
          (pane.property("showLive"), view.property("followLive")))

    # --- it lands: the row becomes the file, and the selection with it ------
    landed = noisy_png(os.path.join(tmp, "out", "live_00009_.png"), 60, 40)
    ctl.gallery.add(landed, "job-1")
    # NO SPIN: this is the frame the flash lived in. The job's row has just
    # become its file and that file has not been decoded yet, so the pane must
    # still be drawing the last sampler frame — anything else here is the
    # PREVIOUS output showing through [his, 2026-08-28, twice].
    check("a finish does not fall back to the previous output",
          pane.property("source") == landed, pane.property("source"))
    check("...it holds the last sampler frame until the new file can be drawn",
          pane.property("showLive") is True and pane.property("handover") is True,
          (pane.property("showLive"), pane.property("handover")))
    spin(250)
    check("...and then hands over to the output itself",
          pane.property("showLive") is False and pane.property("source") == landed,
          (pane.property("showLive"), pane.property("source")))
    check("the finished output replaces the job's row",
          ctl.gallery.rowCount() == before + 1 and ctl.gallery.isLiveAt(0) is False
          and ctl.gallery.pathAt(0) == landed,
          (ctl.gallery.rowCount(), ctl.gallery.pathAt(0)))
    check("...and what was following the job is now on the output",
          prop(view, "selection") == [landed], prop(view, "selection"))
    ctl._busy = False
    spin(60)
    check("...which is what the pane draws", pane.property("source") == landed,
          pane.property("source"))

    # --- a NEWLY QUEUED batch takes the preview back -----------------------
    # [his, 2026-08-28] "ensure the live step/frame preview replaces whatever is
    # being previewed in the preview pane when the user queues something new".
    invoke_str(view, "selectSingle", landed)
    spin(120)
    check("...until then, what he picked is what is shown",
          view.property("followLive") is False and pane.property("source") == landed,
          (view.property("followLive"), pane.property("source")))
    ctl.gallery.begin_live("job-1b", grab=True)
    spin(150)
    check("queueing something new takes the preview over",
          prop(view, "selection") == [P_LIVE] and pane.property("selLive") is True,
          (prop(view, "selection"), pane.property("selLive")))

    # ...but the SECOND job of that one batch does not: four images asked for in
    # one press are one request, and being yanked back mid-batch is what this
    # pane stopped doing.
    ctl.gallery.end_live("job-1b")
    spin(120)
    invoke_str(view, "selectSingle", landed)
    spin(120)
    ctl.gallery.begin_live("job-1c", grab=False)
    spin(150)
    check("a later job of the same batch leaves his choice alone",
          prop(view, "selection") == [landed], prop(view, "selection"))
    ctl.gallery.end_live("job-1c")
    spin(120)

    # --- pressing GENERATE is what takes the preview, not the backend ------
    # [his, 2026-08-28] "the active gen wont steal the preview pane, it stays on
    # the users selection when the user initiates a generation when it should".
    # The row is created at submit; `_on_started` only re-keys it.
    class FakeJob:
        def __init__(self):
            self.meta = {}
            self.prompt_id = "pid-submit"

    orig_build, orig_submit, orig_oi = ctl.reg.build, ctl.client.submit, ctl._object_info
    ctl.reg.build = lambda entry, params, object_info=None: (
        {"prompt": {}, "params": dict(params), "pairing": {}})
    ctl.client.submit = lambda prompt, params: FakeJob()
    ctl._object_info = {"stub": True}
    invoke_str(view, "selectSingle", landed)
    spin(120)
    g = prop(APP, "gen")
    g.update({"positive": "x", "count": 1, "randomSeed": False, "seed": 7})
    APP.setProperty("gen", g)
    spin(80)
    APP.metaObject().invokeMethod(APP, "submit")
    spin(250)
    check("pressing generate takes the preview at once, before the job starts",
          prop(view, "selection") == [P_LIVE] and pane.property("selLive") is True,
          (prop(view, "selection"), pane.property("selLive")))
    check("...and the row is there before the backend has said anything",
          ctl.gallery.isLiveAt(0) is True and ctl.gallery.property("liveGrab") is True,
          (ctl.gallery.isLiveAt(0), ctl.gallery.property("liveGrab")))
    ctl._on_started(FakeJob())
    spin(150)
    # +2: the history gained the finished output above, and this row on top of it.
    check("...and the backend starting it only re-keys that row",
          ctl.gallery.rowCount() == before + 2 and ctl.gallery.isLiveAt(0) is True,
          ctl.gallery.rowCount())
    check("...with the prompt id it now has",
          ctl.gallery._live.get("job") == "pid-submit", ctl.gallery._live)
    ctl.cancel()
    spin(150)
    check("cancelling takes the row away",
          ctl.gallery.isLiveAt(0) is False and ctl.gallery.rowCount() == before + 1,
          ctl.gallery.rowCount())
    ctl.reg.build, ctl.client.submit, ctl._object_info = orig_build, orig_submit, orig_oi

    # --- "finished" is not "downloaded" ------------------------------------
    # [his, 2026-08-28, three times] the previous generation showing between the
    # last sampler frame and the new output. `_on_finished` arrives over the
    # websocket a beat BEFORE the file it made has been downloaded, and ending
    # the job's row there left the pane with a job that no longer exists and a
    # file that does not exist yet — so it drew the newest output it could find,
    # which is the previous one, for the whole length of the download.
    class SlowJob:
        duration = 2.0
        prompt_id = "pid-slow"

        def __init__(self):
            self.images = [{"filename": "live_00011_.png", "subfolder": ""}]
            self.meta = {"params": {"seed": 1}, "pairing": None}

    held = []
    real_download = ctl.client.download
    ctl.client.download = lambda img, cb: held.append(cb)
    ctl.gallery.begin_live("pid-slow", grab=True)
    spin(150)
    ctl._busy = True
    ctl._on_preview(None, frame, "png")
    spin(80)
    ctl._jobs = 1
    ctl._batch_saved = []
    ctl._batch_pending = 0
    ctl._batch_toasted = True
    ctl._on_finished(SlowJob())
    spin(150)
    check("a finished job keeps its row while its file is still downloading",
          ctl.gallery.isLiveAt(0) is True, ctl.gallery.pathAt(0))
    check("...so the pane never falls back to the previous output",
          pane.property("showLive") is True and pane.property("source") == "",
          (pane.property("showLive"), pane.property("source")))
    # the download lands
    with open(made[0], "rb") as fh:
        blob = fh.read()
    for cb in held:
        cb(blob)
    spin(300)
    slow = os.path.join(tmp, "out", "live_00011_.png")
    check("...and the file takes the row when it arrives",
          ctl.gallery.isLiveAt(0) is False and ctl.gallery.pathAt(0) == slow,
          ctl.gallery.pathAt(0))
    check("...and the pane is on it", pane.property("source") == slow,
          pane.property("source"))
    ctl.client.download = real_download
    ctl._jobs = 0
    ctl._busy = False
    spin(80)

    # A batch whose download produces nothing at all still gives the row back.
    ctl.client.download = lambda img, cb: cb(b"")
    ctl.gallery.begin_live("pid-empty", grab=True)
    spin(120)
    ctl._jobs = 1
    ctl._batch_pending = 0
    ctl._batch_toasted = True
    ctl._on_finished(SlowJob())
    spin(250)
    check("a download that produced nothing still gives the row back",
          ctl.gallery.isLiveAt(0) is False, ctl.gallery.pathAt(0))
    ctl.client.download = real_download
    ctl._jobs = 0
    # ...and put the history back where the checks below expect it.
    try: os.remove(slow)
    except OSError: pass
    ctl.gallery.load_existing()
    spin(200)

    # --- a job that produces nothing gives its row back --------------------
    ctl.gallery.begin_live("job-2")
    spin(120)
    check("a second job takes a row", ctl.gallery.isLiveAt(0) is True)
    ctl.gallery.end_live("job-2")
    spin(120)
    check("a cancelled job gives it back",
          ctl.gallery.rowCount() == before + 1 and ctl.gallery.isLiveAt(0) is False,
          ctl.gallery.rowCount())

    # ...and a stale completion cannot take the row of the job now running.
    ctl.gallery.begin_live("job-3")
    spin(120)
    stale = noisy_png(os.path.join(tmp, "out", "live_00010_.png"), 60, 40)
    ctl.gallery.add(stale, "job-old")
    spin(200)
    check("an earlier job's file lands UNDER the one still sampling",
          ctl.gallery.isLiveAt(0) is True and ctl.gallery.pathAt(1) == stale,
          (ctl.gallery.isLiveAt(0), ctl.gallery.pathAt(1)))

    # A filter is about the history; it must not take the running job off screen.
    ctl.gallery.setFilter("zzzz-nothing-matches")
    spin(200)
    check("a filter never hides the job in flight",
          ctl.gallery.rowCount() == 1 and ctl.gallery.isLiveAt(0) is True,
          ctl.gallery.rowCount())
    ctl.gallery.setFilter("")
    spin(150)

    # ...and neither does a rescan, which rebuilds the history from the disk.
    ctl.gallery.load_existing()
    spin(250)
    check("a rescan keeps it too", ctl.gallery.isLiveAt(0) is True)

    ctl.gallery.end_live()
    spin(120)
    view.metaObject().invokeMethod(view, "clearSelection")
    APP.setProperty("showPreview", False)
    for p in made + [landed, stale]:
        try: os.remove(p)
        except OSError: pass
    ctl.gallery.load_existing()
    spin(150)


def test_preview_zoom(win, ctl, tmp):
    """The wheel zooms the preview and the wheel BUTTON drags it around.

    [his, 2026-08-28] "add panning and zooming via the mouse wheel and mouse
    wheel click". The pane is a few hundred pixels tall and an output is a
    megapixel, so this is the difference between "is that hand right" and
    opening the file in something else.
    """
    from PySide6.QtCore import Qt
    content = win.contentItem()
    view = find(content, "GalleryView")
    pane = find(content, "PreviewPane")
    APP.setProperty("showPreview", True)
    spin(150)

    shot = noisy_png(os.path.join(tmp, "out", "zoom_00001_.png"), 200, 150)
    ctl.gallery.load_existing()
    spin(250)
    invoke_str(view, "selectSingle", shot)
    spin(200)
    check("the pane is showing the picture to zoom",
          pane.property("source") == shot, pane.property("source"))

    # Only a completed still owns this menu. Its copy is intentionally pixels
    # alone: a browser post field must attach it without receiving a pathname
    # as text as well.
    preview_mouse = next((it for it in walk(pane)
                          if it.property("objectName") == "previewMouse"), None)
    if preview_mouse is not None:
        click(win, preview_mouse, button=Qt.RightButton)
        menus = find_all(content, "CtxMenu")
        offered = next((prop(m, "items") for m in menus if prop(m, "items")), [])
        labels = [i.get("label") for i in offered if i.get("label")]
        check("a completed still preview offers copy image", labels == ["copy image"], labels)
        for menu in menus:
            menu.metaObject().invokeMethod(menu, "close")
    else:
        check("a completed still preview has a right-click target", False)
    RAN.clear()
    ctl.copyImage(shot)
    spin(120)
    copied = [a for a in RAN if any(os.path.basename(x) == "clipfile.py" for x in a)]
    check("copy image asks clipfile for image MIME only",
          copied and copied[-1][-2:] == ["--image-only", shot], copied)
    check("...at 1:1, with nothing to pan",
          pane.property("zoom") == 1.0 and pane.property("panX") == 0,
          (pane.property("zoom"), pane.property("panX")))

    # A drag at 1:1 must not move it: there is nothing off screen to reach.
    drag(win, pane, 40, 40, 90, 70, Qt.MiddleButton)
    check("a pan at 1:1 does nothing", pane.property("panX") == 0
          and pane.property("panY") == 0,
          (pane.property("panX"), pane.property("panY")))

    wheel(win, pane, 40, 40, 3)
    z = pane.property("zoom")
    check("the wheel zooms in", z > 1.4, z)
    # ...about the pointer, so what was under it stays there: with the cursor
    # at (40,40) the pan has to move up and left by (z-1)*40.
    check("...about the pointer, not the middle of the pane",
          abs(pane.property("panX") - (40 - 40 * z)) < 1.5, pane.property("panX"))

    px, py = pane.property("panX"), pane.property("panY")
    drag(win, pane, 90, 70, 120, 95, Qt.MiddleButton)
    check("the wheel button drags it",
          pane.property("panX") > px and pane.property("panY") > py,
          (px, pane.property("panX"), py, pane.property("panY")))
    check("...and never off its own pane",
          pane.property("panX") <= 0 and pane.property("panY") <= 0,
          (pane.property("panX"), pane.property("panY")))

    # A wheel click that goes nowhere is the way back to fit.
    click(win, pane, 60, 60, Qt.MiddleButton)
    check("a wheel click puts it back to fit",
          pane.property("zoom") == 1.0 and pane.property("panX") == 0,
          (pane.property("zoom"), pane.property("panX")))

    wheel(win, pane, 40, 40, 40)
    check("zoom has a ceiling", pane.property("zoom") == 8.0, pane.property("zoom"))
    wheel(win, pane, 40, 40, -80)
    check("...and a floor, which is fit", pane.property("zoom") == 1.0,
          pane.property("zoom"))

    # A different output is a different view of it.
    wheel(win, pane, 40, 40, 3)
    other = noisy_png(os.path.join(tmp, "out", "zoom_00002_.png"), 200, 150)
    ctl.gallery.add(other)
    spin(200)
    invoke_str(view, "selectSingle", other)
    spin(200)
    check("picking another output starts it at fit",
          pane.property("zoom") == 1.0, pane.property("zoom"))

    view.metaObject().invokeMethod(view, "clearSelection")
    APP.setProperty("showPreview", False)
    for f in (shot, other):
        try: os.remove(f)
        except OSError: pass
    ctl.gallery.load_existing()
    spin(150)


def main():
    tmp = tempfile.mkdtemp(prefix="painter-ui-test-")
    os.environ["PAINTER_MODELS"] = fake_models(os.path.join(tmp, "models"))
    os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
    os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
    os.environ["PAINTER_OUT"] = os.path.join(tmp, "out")
    # The other machine's outputs, read-only — what comfy-tunnel.sh mounts top's
    # root at on book. Read once at import, so it has to be set before build().
    os.environ["PAINTER_PEER_OUT"] = os.path.join(tmp, "peer-out")

    app, engine, win, ctl, keep = build(tmp)
    only = os.environ.get("PAINTER_UI_ONLY")
    if only in ("seed", "preview"):
        print("== %s ==" % only)
        if only == "seed":
            test_seed(win, ctl)
        else:
            test_preview_zoom(win, ctl, tmp)
        real = [w for w in WARNINGS if "Qt Quick Layouts" not in w]
        for w in real:
            print("QML WARNING: " + w)
        check("no QML warnings", not real, len(real))
        print("\n%d checks failed" % len(FAILS))
        return 1 if FAILS else 0
    print("== text boxes ==");        test_text_boxes(win, ctl)
    print("== chrome ==");            test_chrome(win, ctl)
    print("== model panel ==");       test_model_panel(win, ctl)
    print("== panes ==");             test_panes(win)
    print("== live bindings ==");     test_live_bindings(win, ctl)
    print("== video ==");             test_video(win, ctl, tmp)
    print("== paste ==");             test_paste(win, ctl, tmp)
    print("== modes ==");             test_modes(win, ctl, tmp)
    print("== drag out ==");          test_drag_out(win, ctl, tmp)
    print("== hover play ==");        test_hover_play(win, ctl, tmp)
    print("== thumb cache ==");       test_thumb_cache(win, ctl, tmp)
    print("== selection ==");         test_selection_and_collage(win, ctl, tmp)
    print("== resolution ==");        test_resolution(win, ctl)
    print("== dropdowns ==");         test_dropdown(win, ctl)
    print("== escape ==");            test_escape(win, ctl)
    print("== panel order + pins =="); test_panel_order_and_pins(win, ctl, tmp, keep)
    print("== filter ==");           test_filter(win, ctl, tmp)
    print("== browse/view ==");      test_browse_view(win, ctl, tmp)
    print("== compare + columns =="); test_compare_and_columns(win, ctl, tmp)
    print("== inject ==");            test_inject(win, ctl, tmp)
    print("== copy prompt ==");       test_copy_prompt(win, ctl, tmp)
    print("== clip params ==");       test_clip_params(win, ctl, tmp)
    print("== peer history ==");      test_peer_history(win, ctl, tmp)
    print("== muted copies ==");      test_muted(win, ctl, tmp)
    print("== done toast ==");        test_done_toast(win, ctl, tmp)
    print("== split + state ==");     test_split_and_state(win, ctl, keep)
    print("== restore ==");           keep2 = test_restore(tmp)
    print("== startup ==");           test_startup(ctl)
    print("== wiring ==");            test_wiring(win, ctl)
    print("== seed reuse ==");        test_seed(win, ctl)
    print("== preset sampling ==");   test_preset_sampling(win, ctl, tmp)
    print("== section order ==");      test_section_order(win, ctl, tmp)
    print("== preset isolation ==");   test_preset_isolation(win, ctl, tmp)
    print("== tag complete ==");       test_tag_complete(win, ctl, keep)
    print("== live row ==");           test_live_row(win, ctl, tmp)
    print("== preview zoom ==");       test_preview_zoom(win, ctl, tmp)

    real = [w for w in WARNINGS if "Qt Quick Layouts" not in w]
    for w in real:
        print("QML WARNING: " + w)
    check("no QML warnings", not real, len(real))

    print("\n%d checks failed" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
