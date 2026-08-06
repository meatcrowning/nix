#!/usr/bin/env python3
"""Offscreen harness for filer's "send to phone" (KDE Connect) context entry.

Two halves, and the point of both is the rule that decides the empty case:
docs/DESIGN.md 10 — a menu row that would quietly do nothing must not be
offered. So this asserts the MENU as much as the send:

  * `phone.py` itself — that a real `--id-name-only` line parses into id+name
    with the name's spaces intact, that a garbage line, a non-zero exit, a
    missing binary and a hung daemon each yield NO devices (which greys the
    entry) rather than a half-parsed one, and that `sendable()` counts out
    directories and things that are not there.
  * the real `qml/BrowserPane.qml`, loaded offscreen through `Main.qml` — that
    with no device reachable the entry is present, DISABLED and says why; that
    with no sendable file it is disabled and says the OTHER why; that two
    reachable devices produce two enabled rows named after the devices; that the
    count in the label is the sendable count, not the selection's; and that
    triggering one runs exactly one `kdeconnect-cli -d <id> --share <file>` per
    file, inside one begin/endBatch so a partial failure reports once.

**Nothing here runs kdeconnect-cli against a real device.** `Phone.devices` is
stubbed with a scripted answer and `FileOps` is stubbed with a collector: a test
must never put a file on his phone or a toast on his screen. The real binary is
never executed at all; the only thing asked of it is that `notify.tool` can
RESOLVE it, since a name that PATH cannot find is how this feature would go
quiet on `book`.

    apps/filer/tools/phone-test.py        # exit 0 = all checks passed
"""
import json
import os
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"   # hard, never setdefault
os.environ.pop("WAYLAND_DISPLAY", None)  # no way back to his session: with no
os.environ.pop("DISPLAY", None)          # display Qt aborts, it cannot fall back

FILER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FILER)
sys.path.insert(0, os.path.join(os.path.dirname(FILER), "pylib"))
from deskstyle import DeskStyle  # noqa: E402  (pylib; Theme.qml binds to it)

from PySide6.QtCore import QUrl, QObject, Slot  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import (QQmlApplicationEngine, QQmlComponent,  # noqa: E402
                           QQmlExpression)

import main as filermain  # noqa: E402
import phone as filerphone  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


# ---------------------------------------------------------------- stubs

class StubPhone(QObject):
    """`Phone` with a scripted device list. `sendable` is the REAL one — it is
    pure filesystem logic and stubbing it would test nothing."""

    def __init__(self):
        super().__init__()
        self.devs = []
        self._real = filerphone.Phone()

    @Slot(result="QVariantList")
    def devices(self):
        return list(self.devs)

    @Slot(list, result="QVariantList")
    def sendable(self, paths):
        return self._real.sendable(paths)


class StubFileOps(QObject):
    """Collects what QML asked to run, in order, instead of running it."""

    def __init__(self):
        super().__init__()
        self.runs = []       # (argv, reselect, batch)
        self.batches = []    # ("begin"|"end", label-or-token)
        self._n = 0

    @Slot(str, result=str)
    def beginBatch(self, label):
        self._n += 1
        tok = "t%d" % self._n
        self.batches.append(("begin", str(label), tok))
        return tok

    @Slot(str)
    def endBatch(self, tok):
        self.batches.append(("end", str(tok), str(tok)))

    @Slot(list, str)
    @Slot(list, str, str)
    def run(self, argv, reselect, batch=""):
        self.runs.append(([str(a) for a in argv], str(reselect), str(batch)))

    # the rest of the surface BrowserPane touches while merely LOADING
    @Slot(str, result=bool)
    def isDir(self, p):
        return os.path.isdir(p)

    @Slot(str, result="QVariantList")
    def listDir(self, p):
        return filermain.FileOps().listDir(p)

    @Slot(str, result="QVariantList")
    def completePath(self, t):
        return []

    @Slot(str)
    def copyText(self, t):
        pass

    @Slot(list, result=bool)
    def execDetached(self, argv):
        return True

    @Slot(list, result=str)
    def writeOrder(self, paths):
        return ""

    @Slot(result=str)
    def homeDir(self):
        return os.path.expanduser("~")


class StubTitlebar(QObject):
    @Slot("QVariantList")
    def setButtons(self, b): pass
    @Slot(str)
    def setFooter(self, t): pass
    @Slot(bool)
    def setTitleEdit(self, on): pass


def spin(ms=200):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def build(app, start_dir, ops, ph):
    """The real Main.qml, offscreen, on the given FileOps and Phone."""
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (ops, filermain.Palette(filermain.PANEL_THEME), filermain.Settings(),
            filermain.DirWatch(), filermain.WinCtl(), filermain.VideoConv(),
            StubTitlebar(), filermain.Picker(None), DeskStyle(parent=engine), ph,
            filermain.Remote(), filermain.ImgConv())
    for name, obj in (("FileOps", keep[0]), ("WalPalette", keep[1]),
                      ("Settings", keep[2]), ("DirWatch", keep[3]),
                      ("WinCtl", keep[4]), ("VideoConv", keep[5]),
                      ("Titlebar", keep[6]), ("Picker", keep[7]),
                      ("DeskStyle", keep[8]), ("Phone", keep[9]),
                      ("Remote", keep[10]), ("ImgConv", keep[11])):
        ctx.setContextProperty(name, obj)
    ctx.setContextProperty("startDir", start_dir)
    ctx.setContextProperty("startSortField", "name")
    ctx.setContextProperty("startSortAsc", True)
    ctx.setContextProperty("startShowHidden", True)
    ctx.setContextProperty("startGridPanelH", 200)
    ctx.setContextProperty("startSplit", False)
    ctx.setContextProperty("startSplitDir", "")
    ctx.setContextProperty("startSplitRatio", 0.5)
    ctx.setContextProperty("startSplitVertical", True)
    comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(FILER, "qml/theme/Theme.qml")))
    theme = comp.create()
    if theme is None:
        raise SystemExit("Theme.qml failed: " + comp.errorString())
    theme.setParent(app)
    ctx.setContextProperty("Theme", theme)
    engine.load(QUrl.fromLocalFile(os.path.join(FILER, "qml/Main.qml")))
    roots = engine.rootObjects()
    if not roots:
        raise SystemExit("Main.qml failed to load")
    return engine, roots[0], keep + (theme,)


def evaluate(engine, obj, js):
    """Run a JS expression in `obj`'s own QML scope — the way to call a
    BrowserPane function from here, since a QML `function` is not a slot."""
    expr = QQmlExpression(engine.contextForObject(obj), obj, js)
    val = expr.evaluate()
    if expr.hasError():
        raise SystemExit("QML expression %r: %s" % (js, expr.error().toString()))
    # PySide returns the C++ `bool *valueIsUndefined` out-parameter alongside
    # the result, so this is a 2-tuple, not the value.
    return val[0] if isinstance(val, tuple) else val


def items_of(engine, obj, js):
    """A menu-item array, as plain Python, via JSON on the QML side.

    A QJSValue array of objects does not survive `toVariant()` elementwise here,
    and a `trigger` is a JS closure that could not cross anyway — hence the
    round-trip, and hence `fire()` below, which clicks a row in JS so the real
    closure runs rather than a rebuilt one."""
    return json.loads(evaluate(engine, obj, "JSON.stringify(%s)" % js))


def labels(items):
    return [it.get("label", "") for it in (items or [])]


def enabled(items):
    # CtxMenu's contract: `enabled` absent means enabled.
    return [it.get("enabled", True) is not False for it in (items or [])]


# ---------------------------------------------------------------- phone.py

def test_parsing():
    ph = filerphone.Phone()

    class Fake:
        def __init__(self, rc, out):
            self.returncode, self.stdout = rc, out

    real_run = filerphone.subprocess.run
    try:
        line = "05624379b7504dd0905e92bcdb271284 Galaxy S22 Ultra"
        filerphone.subprocess.run = lambda *a, **k: Fake(0, line + "\n")
        devs = ph.devices()
        check("one device parses", devs == [{"id": "05624379b7504dd0905e92bcdb271284",
                                             "name": "Galaxy S22 Ultra"}], devs)

        filerphone.subprocess.run = lambda *a, **k: Fake(0, "a Phone One\nb Phone Two\n")
        check("two devices, order kept",
              [d["name"] for d in ph.devices()] == ["Phone One", "Phone Two"])

        filerphone.subprocess.run = lambda *a, **k: Fake(0, "\n  \nnoname\n")
        check("id with no name is not a device", ph.devices() == [], ph.devices())

        filerphone.subprocess.run = lambda *a, **k: Fake(1, "id Name\n")
        check("non-zero exit yields no devices", ph.devices() == [])

        def boom(*a, **k):
            raise OSError("no such binary")
        filerphone.subprocess.run = boom
        check("missing binary yields no devices", ph.devices() == [])

        def hang(*a, **k):
            raise filerphone.subprocess.TimeoutExpired("kdeconnect-cli", 3)
        filerphone.subprocess.run = hang
        check("a hung daemon yields no devices (does not raise)", ph.devices() == [])
    finally:
        filerphone.subprocess.run = real_run

    check("devices() is bounded by a timeout", filerphone._TIMEOUT > 0)
    check("kdeconnect-cli resolves through notify.tool",
          os.path.isabs(filerphone.tool("kdeconnect-cli")),
          filerphone.tool("kdeconnect-cli"))


def test_sendable(tmp):
    ph = filerphone.Phone()
    f1 = os.path.join(tmp, "a.png")
    f2 = os.path.join(tmp, "b.txt")
    d = os.path.join(tmp, "sub")
    gone = os.path.join(tmp, "gone.png")
    open(f1, "w").close()
    open(f2, "w").close()
    os.mkdir(d)
    check("directories are not sendable", ph.sendable([d]) == [])
    check("a missing path is not sendable", ph.sendable([gone]) == [])
    check("files are sendable, order kept", ph.sendable([f2, f1]) == [f2, f1])
    check("a mixed selection keeps only the files", ph.sendable([f1, d, gone, f2]) == [f1, f2])
    check("an empty selection is empty", ph.sendable([]) == [])


# ---------------------------------------------------------------- the menu

def test_menu(app, tmp):
    files = []
    for n in ("a.png", "b.png", "c.png"):
        p = os.path.join(tmp, n)
        open(p, "w").close()
        files.append(p)
    sub = os.path.join(tmp, "sub")
    if not os.path.isdir(sub):
        os.mkdir(sub)

    ops, ph = StubFileOps(), StubPhone()
    engine, win, keep = build(app, tmp, ops, ph)
    spin(300)
    view = win.property("pane")
    if view is None:
        raise SystemExit("no pane on the window")

    def menu(sel, devs):
        ph.devs = devs
        view.setProperty("selection", sel)
        return items_of(engine, view, "sendToPhoneItems()")

    def fire(i):
        """Click row `i` — in JS, so the real closure runs, not a rebuilt one."""
        evaluate(engine, view, "sendToPhoneItems()[%d].trigger()" % i)

    # --- no device reachable: greyed, and it SAYS SO (docs/DESIGN.md 10)
    items = menu([files[0]], [])
    check("no device: exactly one row", len(items) == 1, labels(items))
    check("no device: the row is DISABLED", enabled(items) == [False], items)
    check("no device: the row says why",
          "no device reachable" in labels(items)[0], labels(items))
    check("no device: no trigger to fire",
          evaluate(engine, view, "typeof sendToPhoneItems()[0].trigger") == "undefined")

    dev1 = [{"id": "abc123", "name": "Galaxy S22 Ultra"}]
    dev2 = dev1 + [{"id": "def456", "name": "motorola razr 2023"}]

    # --- nothing sendable: also greyed, with the OTHER reason
    items = menu([sub], dev1)
    check("dir-only selection: DISABLED", enabled(items) == [False], items)
    check("dir-only selection: says directories cannot be sent",
          "directories cannot be sent" in labels(items)[0], labels(items))

    # --- one device: one enabled row, named after the device
    items = menu([files[0]], dev1)
    check("one device: one row", len(items) == 1, labels(items))
    check("one device: enabled", enabled(items) == [True])
    check("one device: named after the device",
          labels(items)[0] == "send to Galaxy S22 Ultra", labels(items))
    check("one file: no count in the label", "(" not in labels(items)[0], labels(items))

    # --- two devices: one row EACH, so nothing is chosen silently
    items = menu([files[0]], dev2)
    check("two devices: two rows", len(items) == 2, labels(items))
    check("two devices: both enabled", enabled(items) == [True, True])
    check("two devices: both named",
          labels(items) == ["send to Galaxy S22 Ultra", "send to motorola razr 2023"],
          labels(items))

    # --- the count is the SENDABLE count, not the selection's
    items = menu(files, dev1)
    check("three files: count in the label",
          labels(items)[0] == "send to Galaxy S22 Ultra (3)", labels(items))
    items = menu(files + [sub], dev1)
    check("a folder in the selection is counted OUT of the label",
          labels(items)[0] == "send to Galaxy S22 Ultra (3)", labels(items))

    # --- the send itself
    del ops.runs[:]
    del ops.batches[:]
    menu(files, dev1)
    fire(0)
    spin(200)
    check("send: one process per file", len(ops.runs) == 3, ops.runs)
    check("send: argv is kdeconnect-cli -d <id> --share <file>",
          [r[0] for r in ops.runs] ==
          [["kdeconnect-cli", "-d", "abc123", "--share", p] for p in files],
          ops.runs)
    check("send: batched, so N failures report once",
          [b[0] for b in ops.batches] == ["begin", "end"], ops.batches)
    check("send: the batch is labelled for the toast",
          ops.batches[0][1] == "send to phone", ops.batches)
    check("send: every run carries the batch token",
          {r[2] for r in ops.runs} == {ops.batches[0][2]}, ops.runs)
    check("send: endBatch closes the batch it opened",
          ops.batches[1][1] == ops.batches[0][2], ops.batches)
    check("send: nothing is reselected", {r[1] for r in ops.runs} == {""}, ops.runs)

    # --- a folder in the selection is not handed to kdeconnect-cli
    del ops.runs[:]
    menu([files[0], sub], dev1)
    fire(0)
    spin(200)
    check("send: the folder is not sent",
          [r[0][-1] for r in ops.runs] == [files[0]], ops.runs)

    # --- the second device sends to the SECOND id
    del ops.runs[:]
    menu([files[1]], dev2)
    fire(1)
    spin(200)
    check("send: the row picked decides the device",
          ops.runs and ops.runs[0][0][2] == "def456", ops.runs)

    # --- the entry is IN the file context menu, in the non-destructive group
    view.setProperty("selection", [files[0]])
    ph.devs = dev1
    full = items_of(engine, view, "entryMenuItems({path: '%s', isDir: false, kind: 'image'})"
                    % files[0])
    labs = labels(full)
    check("the entry is in the file context menu",
          "send to Galaxy S22 Ultra" in labs, labs)
    sep = [i for i, it in enumerate(full) if it.get("separator") is True]
    check("it sits before the first separator, with open/open with",
          sep and labs.index("send to Galaxy S22 Ultra") < sep[0], labs)
    check("it is nowhere near the destructive tail",
          labs.index("send to Galaxy S22 Ultra") < labs.index("trash"), labs)

    # --- and the label a failure toast would carry
    check("a failed send is called 'send to phone', not 'kdeconnect-cli'",
          filermain._op_label(["kdeconnect-cli", "-d", "x", "--share", "/f"])
          == "send to phone")

    return engine, win, keep


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    tmp = tempfile.mkdtemp(prefix="t_phone-")
    # never rewrite where his own filer reopens
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "cfg")
    try:
        test_parsing()
        test_sendable(tmp)
        keep = test_menu(app, tmp)   # noqa: F841 — outlive the checks
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("%d FAILED: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("phone: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
