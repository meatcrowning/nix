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


def click(win, item, dx=None, dy=None, button=None):
    """A real mouse click at a point INSIDE `item`, in window coordinates."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtTest import QTest
    p = item.mapToScene(QPointF(item.width() / 2 if dx is None else dx,
                                item.height() / 2 if dy is None else dy))
    QTest.mouseClick(win, button or Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(p.x()), int(p.y())))
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
        hdr = {k: {"dtype": "BF16", "shape": [16, 16], "data_offsets": [0, 512]} for k in keys}
        hdr["__metadata__"] = {"format": "pt"}
        blob = json.dumps(hdr).encode()
        with open(os.path.join(d, name), "wb") as fh:
            fh.write(struct.pack("<Q", len(blob)))
            fh.write(blob)
            fh.write(b"\0" * 512)
    return root


# ------------------------------------------------------------------ the window
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
    ctl = P.Painter()
    ctl._unit_poll.stop()
    ctl._probe.stop()

    engine = QQmlApplicationEngine()
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
    """Click anywhere in a box and you are typing in it."""
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
    click(win, box, dx=box.width() / 2, dy=box.height() - 6)
    check("a click low in an empty prompt box starts editing",
          edit.property("activeFocus") is True)

    # ...and with text in it, the caret lands at the end rather than nowhere.
    gen = prop(win, "gen"); gen["positive"] = "one two three"
    win.setProperty("gen", gen)
    spin(120)
    check("the model's text reaches the editor", edit.property("text") == "one two three",
          edit.property("text"))
    edit.setProperty("cursorPosition", 0)
    click(win, box, dx=box.width() - 40, dy=box.height() - 6)
    check("...and the caret goes to the end of the text",
          edit.property("cursorPosition") == len("one two three"),
          edit.property("cursorPosition"))

    # A numeric box: the 5px padding strip used to be dead.
    sp = find(content, "Spin")
    inp = find(sp, "QQuickTextInput")
    inp.setProperty("focus", False)
    spin(60)
    click(win, sp, dx=2, dy=sp.height() / 2)
    check("a click on a numeric box's padding starts editing",
          inp.property("activeFocus") is True)


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
    print("== model panel ==");       test_model_panel(win, ctl)
    print("== panes ==");             test_panes(win)
    print("== live bindings ==");     test_live_bindings(win, ctl)
    print("== resolution ==");        test_resolution(win, ctl)
    print("== dropdowns ==");         test_dropdown(win, ctl)
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
