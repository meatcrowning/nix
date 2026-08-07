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
  7. every control in the left column reaches the submitted job.

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
import time

Q_ARG = None  # bound in build(), once PySide6 is importable

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)       # no way back to his session
os.environ.pop("DISPLAY", None)
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
os.environ.pop("PAINTER_BACKEND_SSH", None)   # never drive top's systemd
os.environ.pop("PAINTER_COMFY_URL", None)

PAINTER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPS = os.path.dirname(PAINTER)
sys.path.insert(0, PAINTER)
sys.path.insert(0, os.path.join(APPS, "pylib"))

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
    ctl.preview = P.LivePreview()
    engine.addImageProvider("livepreview", ctl.preview)
    ctx = engine.rootContext()
    keep = (P.Palette(P.PANEL_THEME), _DESKSTYLE(parent=engine), P.Prefs(),
            ctl, _STUBBAR(), P.SpellCheck())
    for name, obj in (("WalPalette", keep[0]), ("DeskStyle", keep[1]),
                      ("Prefs", keep[2]), ("App", ctl), ("Models", ctl.models),
                      ("Loras", ctl.loras), ("LoraChoices", ctl.choices),
                      ("Gallery", ctl.gallery), ("Titlebar", keep[4]),
                      ("Spell", keep[5]), ("Theme", _THEME[0])):
        ctx.setContextProperty(name, obj)
    engine.warnings.connect(lambda ws: WARNINGS.extend(w.toString() for w in ws))
    engine.load(QUrl.fromLocalFile(os.path.join(PAINTER, "qml/Main.qml")))
    win = engine.rootObjects()[0]
    ctl.rescan()
    spin(400)
    return engine, win, ctl, keep


_DESKSTYLE = None
_STUBBAR = None
_THEME = [None]


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
        if os.path.basename(argv[-2] if len(argv) > 1 else argv[0]) == "clipfile.py" \
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
    # The live-preview provider, as main() installs it: without it the preview
    # pane's Image warns "Invalid image provider" the moment a frame arrives,
    # and a QML warning fails this run.
    ctl.preview = P.LivePreview()
    engine.addImageProvider("livepreview", ctl.preview)
    ctx = engine.rootContext()
    keep = (P.Palette(P.PANEL_THEME), DeskStyle(parent=engine), P.Prefs(),
            ctl, StubTitlebar(), P.SpellCheck())
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
    gen = prop(win, "gen"); gen["positive"] = "one two three"
    win.setProperty("gen", gen)
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
          prop(win, "gen").get("positive") == "", prop(win, "gen").get("positive"))
    key(win, Qt.Key_X, Qt.NoModifier, "x")
    key(win, Qt.Key_Y, Qt.NoModifier, "y")
    check("typing after that still reaches the model",
          edit.property("text") == "xy" and prop(win, "gen").get("positive") == "xy",
          (edit.property("text"), prop(win, "gen").get("positive")))
    key(win, Qt.Key_Backspace)
    check("a plain Backspace deletes one character",
          edit.property("text") == "x", edit.property("text"))
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
          nedit.property("text") == "" and prop(win, "gen").get("negative") == "",
          (nedit.property("text"), prop(win, "gen").get("negative")))
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
        check("...and is elided inside the panel, not spilling out of it",
              b.x() + b.width() <= panel.width() + 0.5
              and b.property("truncated") is True,
              (b.x(), b.width(), panel.width(), b.property("truncated")))
    win.setWidth(was)
    panel.setProperty("collapsed", False)
    spin(120)

    # The splitter is a drag target; the status bar is under it and must not be.
    bar = find(content, "QueueBar")
    split = [it for it in walk(content)
             if it.property("width") == win.property("splitterW")
             and it.height() > 100]
    check("the splitter stops above the status bar",
          bool(split) and split[0].height() <= win.height() - bar.height() + 0.5,
          (split[0].height() if split else None, win.height(), bar.height()))

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
    win.setProperty("showPreview", True)
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
    win.setProperty("showPreview", False)
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
        win.setProperty("view", 0)
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
    win.setProperty("view", 0)
    spin(120)
    narrow_params = gal.isVisible()
    win.setProperty("view", 1)
    spin(120)
    check("below the split floor the gallery is one button away",
          (not narrow_params) and gal.isVisible(), (narrow_params, gal.isVisible()))
    win.setWidth(1280)
    win.setProperty("view", 0)
    spin(120)


def test_resolution(win, ctl):
    """aspect + MP -> one size, in the header, in the readout, in the job."""
    import registry as R

    gen = prop(win, "gen")
    for aw, ah, mp in ((3, 2, 1.0), (21, 9, 2.0), (5, 3, 0.5), (1, 1, 4.0)):
        gen = prop(win, "gen")
        gen["aspectW"], gen["aspectH"], gen["megapixels"] = aw, ah, mp
        win.setProperty("gen", gen)
        win.metaObject().invokeMethod(win, "recomputeDims")
        spin(60)
        g = prop(win, "gen")
        want = R.calc_dims("%d:%d" % (aw, ah), mp, g["multiple"])
        check("%d:%d @ %sMP -> %dx%d" % (aw, ah, mp, want[0], want[1]),
              (g["width"], g["height"]) == want, (g["width"], g["height"]))

    panel = find(win.contentItem(), "ResolutionPanel")
    g = prop(win, "gen")
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
    g = prop(win, "gen")
    g["useInputImage"] = True
    win.setProperty("gen", g)
    spin(120)
    check("with a first frame the aspect is the image's, so the box goes",
          not aspect.isVisible() and res.property("badge") == "from the image",
          res.property("badge"))
    # ...and a LAST frame on its own does the same: the two toggles are
    # independent, and either dropped image is what the size is measured off.
    g = prop(win, "gen")
    g.update({"useInputImage": False, "useLastFrame": True})
    win.setProperty("gen", g)
    spin(120)
    check("a last frame alone also decides the aspect",
          not aspect.isVisible() and res.property("badge") == "from the image",
          res.property("badge"))
    well = find(find(content, "VideoPanel"), "FrameWell",
                pred=lambda it: it.property("emptyText").startswith("drag the frame to end"))
    check("...and its well stands on its own, with no first frame",
          well is not None and well.isVisible(), well and well.property("active"))
    g = prop(win, "gen")
    g.update({"useInputImage": False, "useLastFrame": False})
    win.setProperty("gen", g)
    spin(120)
    check("...and text-to-video gets it back", aspect.isVisible())

    # Seconds -> frames, the same arithmetic the graph uses.
    import registry as R
    panel = find(content, "VideoPanel")
    g = prop(win, "gen")
    g["duration"] = 5.0
    win.setProperty("gen", g)
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
    g = prop(win, "gen")
    g.update({"positive": "a clip", "negative": "ignored", "duration": 3.0,
              "steps": 12, "seed": 99, "randomSeed": False, "count": 1,
              "useInputImage": False})
    win.setProperty("gen", g)
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
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
    g = prop(win, "gen")
    g.update({"useInputImage": True, "useLastFrame": True})
    win.setProperty("gen", g)
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
    spin(200)
    check("a last frame is sent alongside the first",
          sent.get("use_last_frame") is True and sent.get("last_image") == "painter/last.png"
          and sent.get("input_image") == "painter/first.png",
          (sent.get("use_last_frame"), sent.get("last_image"), sent.get("input_image")))

    # A last frame ON ITS OWN is a job, not an error: the node takes either end.
    sent.clear()
    g = prop(win, "gen")
    g.update({"useInputImage": False, "useLastFrame": True})
    win.setProperty("gen", g)
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
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
    win.metaObject().invokeMethod(win, "submit")
    spin(200)
    check("a last frame with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)
    g = prop(win, "gen")
    g["useLastFrame"] = False
    win.setProperty("gen", g)
    spin(60)
    ctl.clearInputImage()

    # An image-to-video job with nothing dropped must not be silently sent as
    # text-to-video: it says so and submits nothing (docs/DESIGN.md §10).
    sent.clear()
    ctl.clearInputImage()
    g = prop(win, "gen")
    g["useInputImage"] = True
    win.setProperty("gen", g)
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
    spin(200)
    check("image-to-video with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)

    ctl.reg.build, ctl.client.submit = orig_build, orig_submit
    ctl._object_info = None
    g = prop(win, "gen")
    g["useInputImage"] = False
    win.setProperty("gen", g)
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
              ("LoraStack", "ParamsPanel", "ResolutionPanel", "TogglePanel", "VideoPanel")}
    check("every control the edit graph would ignore is gone",
          all(not it.isVisible() for it in hidden.values()),
          {k: it.isVisible() for k, it in hidden.items()})

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
    g = prop(win, "gen")
    g.update({"positive": "make it a doll", "negative": "ignored",
              "seed": 4242, "randomSeed": False, "count": 1})
    win.setProperty("gen", g)
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
    spin(200)
    check("edit with no image refuses rather than guessing",
          sent.get("_submitted") is None, sent)

    src = os.path.join(tmp, "to-edit.png")
    with open(src, "wb") as fh:
        fh.write(b"not really a png")
    ctl._input_image = src
    ctl._uploaded = (src, "painter/to-edit.png")   # already uploaded: no network
    sent.clear()
    win.metaObject().invokeMethod(win, "submit")
    spin(250)
    check("an edit job is submitted", sent.get("_submitted") is True, sent)
    check("...as an edit, with the image and the prompt",
          sent.get("edit") is True and sent.get("input_image") == "painter/to-edit.png"
          and sent.get("positive") == "make it a doll",
          {k: sent.get(k) for k in ("edit", "input_image", "positive")})
    check("...and none of the controls it does not show",
          not any(k in sent for k in ("steps", "cfg", "width", "height",
                                      "batch_size", "negative", "toggles")),
          sorted(sent))

    ctl.reg.build, ctl.client.submit = orig_build, orig_submit
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
    win.setProperty("view", 1)
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

    win.setProperty("view", 0)
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
    g = prop(win, "gen")
    check("editing the aspect boxes reaches the model",
          (g["aspectW"], g["aspectH"], g["megapixels"]) == (16, 9, 2.0),
          (g["aspectW"], g["aspectH"], g["megapixels"]))
    check("...and the header badge follows the edit",
          res.property("badge") == "%dx%d" % (g["width"], g["height"]),
          (res.property("badge"), g["width"], g["height"]))

    # A Spin must still follow the MODEL after it has been edited once: the old
    # commit() assigned its own bound `value`, which destroys the binding.
    win.metaObject().invokeMethod(win, "set", Q_ARG("QVariant", "megapixels"),
                                  Q_ARG("QVariant", 1.5))
    spin(120)
    check("a Spin still follows the model after being edited",
          abs(spins[2].property("value") - 1.5) < 1e-6, spins[2].property("value"))

    # The ModelSampling block is bound to gen.modelSampling — with in-place
    # mutation it never appeared when the toggle was flipped.
    tog = find(content, "TogglePanel")
    win.metaObject().invokeMethod(win, "set", Q_ARG("QVariant", "modelSampling"),
                                  Q_ARG("QVariant", False))
    spin(120)
    short = tog.height()
    win.metaObject().invokeMethod(win, "set", Q_ARG("QVariant", "modelSampling"),
                                  Q_ARG("QVariant", True))
    spin(120)
    check("toggling ModelSampling reveals its parameters", tog.height() > short + 40,
          (short, tog.height()))

    # The prompt boxes round-trip without fighting the model.
    box = find_all(content, "PromptBox")[0]
    edit = find(box, "QQuickTextEdit")
    edit.setProperty("text", "typed by hand")
    spin(120)
    check("typing reaches the model", prop(win, "gen")["positive"] == "typed by hand",
          prop(win, "gen")["positive"])


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
                  prop(win, "gen")["sampler_name"] == opts[1]
                  and picker.property("value") == opts[1],
                  (prop(win, "gen")["sampler_name"], picker.property("value"), opts[1]))
            # ...and the binding must SURVIVE the pick.
            win.metaObject().invokeMethod(win, "set", Q_ARG("QVariant", "sampler_name"),
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
    click(win, find(picker, "QQuickRectangle"))
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

    win.setProperty("showSettings", True)
    spin(150)
    QTest.keyClick(win, Qt.Key_Escape)
    spin(150)
    check("Escape closes the settings drawer", win.property("showSettings") is False)


def test_inject(win, ctl, tmp):
    """Left-click an output -> inject all / prompt / params."""
    params = {"positive": "injected positive", "negative": "injected negative",
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
        check("double-clicking it opens it in viewer",
              bool(OPENED) and OPENED[-1][-1] == path, OPENED)
        click(win, cell, dx=cell.width() / 2, dy=cell.height() / 2, button=Qt.RightButton)
        spin(150)
        labels = [i.get("label") for i in (prop(menu, "items") or []) if i.get("label")]
        check("right-clicking one opens the menu", menu.isVisible(), menu.isVisible())
        check("...offering inject all / prompt / params",
              labels[:3] == ["inject all", "inject prompt", "inject params"], labels)
        menu.metaObject().invokeMethod(menu, "close")
        spin(60)

    # The three actions, called the way the menu calls them.
    base = prop(win, "gen")
    base["positive"] = "before"; base["steps"] = 7; base["aspectW"] = 1; base["aspectH"] = 1
    win.setProperty("gen", base)
    spin(60)

    win.metaObject().invokeMethod(win, "injectPrompt", Q_ARG("QVariant", params))
    spin(120)
    g = prop(win, "gen")
    check("inject prompt takes the words", g["positive"] == "injected positive"
          and g["negative"] == "injected negative", (g["positive"], g["negative"]))
    check("...and leaves the numbers alone", g["steps"] == 7, g["steps"])

    win.metaObject().invokeMethod(win, "injectParams", Q_ARG("QVariant", params))
    spin(120)
    g = prop(win, "gen")
    check("inject params takes the numbers",
          (g["steps"], g["cfg"], g["sampler_name"], g["seed"], g["randomSeed"])
          == (44, 3.5, "heun", 99, False),
          (g["steps"], g["cfg"], g["sampler_name"], g["seed"], g["randomSeed"]))
    check("...including the size, as aspect + MP",
          (g["aspectW"], g["aspectH"]) == (19, 13) and (g["width"], g["height"]) == (1216, 832),
          (g["aspectW"], g["aspectH"], g["width"], g["height"]))

    base = prop(win, "gen"); base["positive"] = "before"; base["steps"] = 7
    win.setProperty("gen", base); spin(60)
    win.metaObject().invokeMethod(win, "injectAll", Q_ARG("QVariant", params))
    spin(120)
    g = prop(win, "gen")
    check("inject all takes both", g["positive"] == "injected positive" and g["steps"] == 44,
          (g["positive"], g["steps"]))


def QtBuffer():
    from PySide6.QtCore import QBuffer
    return QBuffer()


def QtIODeviceWriteOnly():
    from PySide6.QtCore import QIODevice
    return QIODevice.OpenModeFlag.WriteOnly


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
    before = win.property("paneLeadW")

    win.setProperty("splitRatio", 0.3)
    spin(120)
    before = win.property("paneLeadW")
    win.setProperty("splitRatio", 0.7)
    spin(120)
    after = win.property("paneLeadW")
    check("the divider moves the panes", after > before + 100, (before, after))
    trail = find(content, "KineticFlickable",
                 pred=lambda it: find(it, "ModelPicker") is not None).parentItem()
    check("...and the trailing pane gives up exactly what the leading one took",
          abs((win.width() - after - win.property("splitterW")) - trail.width()) < 1.5,
          (win.width(), after, trail.width()))

    # Clamps: neither side can be starved.
    win.setProperty("splitRatio", 0.99)
    spin(120)
    check("the handle cannot starve the controls",
          win.width() - win.property("paneLeadW") >= win.property("minTrail"),
          win.width() - win.property("paneLeadW"))
    win.setProperty("splitRatio", 0.01)
    spin(120)
    check("...nor the results", win.property("paneLeadW") >= win.property("minLead"),
          win.property("paneLeadW"))

    # State: everything the window is asked to remember.
    win.setProperty("splitRatio", 0.55)
    win.setProperty("view", 1)
    win.setWidth(1100); win.setHeight(800)
    g = prop(win, "gen"); g["positive"] = "remember me"; g["steps"] = 23
    win.setProperty("gen", g)
    panel = find(content, "ParamsPanel")
    panel.setProperty("collapsed", True)
    spin(200)
    win.metaObject().invokeMethod(win, "saveState")
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
    # NOT un-collapsed here: the restore test reads the prefs file next, and
    # setting it back would (correctly) persist the newer value first.
    win.setProperty("view", 0)
    win.setWidth(1280)
    spin(120)


def test_restore(tmp):
    """A SECOND window, same prefs file: it comes back the way it was left."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    import main as P

    # Same context objects, a fresh engine — as close to a relaunch as one
    # process can get.
    eng, win2, ctl2, keep2 = build_window()
    check("restored: window size", (win2.width(), win2.height()) == (1100, 800),
          (win2.width(), win2.height()))
    check("restored: view", win2.property("view") == 1, win2.property("view"))
    check("restored: split ratio", abs(win2.property("splitRatio") - 0.55) < 1e-6,
          win2.property("splitRatio"))
    g = prop(win2, "gen")
    check("restored: the prompt", g["positive"] == "remember me", g["positive"])
    check("restored: the numbers survive the model's defaults landing",
          g["steps"] == 23, g["steps"])
    panel = find(win2.contentItem(), "ParamsPanel")
    check("restored: the collapsed panel", panel.property("collapsed") is True)
    check("restored: the selected model",
          ctl2.property("selectedName") == "alpha-model.safetensors",
          ctl2.property("selectedName"))
    win2.setProperty("restored", False)     # this window must not re-save
    win2.close()
    return eng, win2, ctl2, keep2


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

    gen = prop(win, "gen")
    gen.update({
        "positive": "a prompt", "negative": "not this",
        "steps": 37, "cfg": 6.25, "denoise": 0.77,
        "sampler_name": "euler_ancestral", "scheduler": "karras",
        "seed": 4242, "randomSeed": False, "batch_size": 3, "count": 1,
        "aspectW": 3, "aspectH": 2, "megapixels": 1.0,
        "negpip": True, "modelSampling": True,
    })
    win.setProperty("gen", gen)
    win.metaObject().invokeMethod(win, "recomputeDims")
    spin(60)
    win.metaObject().invokeMethod(win, "submit")
    spin(200)

    g = prop(win, "gen")
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


def main():
    tmp = tempfile.mkdtemp(prefix="painter-ui-test-")
    os.environ["PAINTER_MODELS"] = fake_models(os.path.join(tmp, "models"))
    os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
    os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
    os.environ["PAINTER_OUT"] = os.path.join(tmp, "out")

    app, engine, win, ctl, keep = build(tmp)
    print("== text boxes ==");        test_text_boxes(win, ctl)
    print("== chrome ==");            test_chrome(win, ctl)
    print("== model panel ==");       test_model_panel(win, ctl)
    print("== panes ==");             test_panes(win)
    print("== live bindings ==");     test_live_bindings(win, ctl)
    print("== video ==");             test_video(win, ctl, tmp)
    print("== modes ==");             test_modes(win, ctl, tmp)
    print("== drag out ==");          test_drag_out(win, ctl, tmp)
    print("== hover play ==");        test_hover_play(win, ctl, tmp)
    print("== resolution ==");        test_resolution(win, ctl)
    print("== dropdowns ==");         test_dropdown(win, ctl)
    print("== escape ==");            test_escape(win, ctl)
    print("== inject ==");            test_inject(win, ctl, tmp)
    print("== muted copies ==");      test_muted(win, ctl, tmp)
    print("== split + state ==");     test_split_and_state(win, ctl, keep)
    print("== restore ==");           keep2 = test_restore(tmp)
    print("== startup ==");           test_startup(ctl)
    print("== wiring ==");            test_wiring(win, ctl)

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
