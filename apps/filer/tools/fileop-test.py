#!/usr/bin/env python3
"""Offscreen harness for filer's FILE OPERATIONS and, above all, their FAILURES.

`FileOps.run` used to wire `finished` and `errorOccurred` to one handler that
read neither the exit code nor stderr: a denied `rm -rf`, a full disk and a
successful copy were the same event. This harness injects real failures — a
root-owned destination, a chmod 500 directory, a source that does not exist, a
genuine ENOSPC via /dev/full, a binary that is not installed — and asserts that
each one is reported, with the right words, exactly once.

It runs the REAL `FileOps` and (for the transfer half) the REAL qml/Main.qml
under QT_QPA_PLATFORM=offscreen, so the QML call sites are exercised rather than
imitated. Nothing here touches anything outside a fresh temp dir.

The toast is STUBBED — `main.toast` is swapped for a collector — for two
reasons: the assertions need the exact strings, and a test must never post
notifications onto the user's screen. That is also why nothing in here calls
notify-send even indirectly.
"""
import os
import shutil
import stat
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

from PySide6.QtCore import QUrl, QObject, Slot, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent  # noqa: E402

import main as filermain  # noqa: E402

FAILS = []
TOASTS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("  " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


def stub_toast(title, body, urgency=None, replace_id=None, value=None, persist=False):
    TOASTS.append((str(title), str(body), urgency))
    return 1


class StubTitlebar(QObject):
    @Slot("QVariantList")
    def setButtons(self, b): pass
    @Slot(str)
    def setFooter(self, t): pass
    @Slot(bool)
    def setTitleEdit(self, on): pass


def find(root, prop):
    for ch in root.children():
        try:
            if ch.property(prop) is not None:
                return ch
        except RuntimeError:
            pass
        hit = find(ch, prop)
        if hit is not None:
            return hit
    return None


def spin(ms=150):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        time.sleep(0.005)


def settle(ms=4000):
    """Run the loop until no new toast has arrived for a beat — file ops are
    QProcesses, so every assertion here is about something asynchronous."""
    end = time.time() + ms / 1000.0
    quiet = 0
    n = len(TOASTS)
    while time.time() < end and quiet < 30:
        QGuiApplication.processEvents()
        time.sleep(0.01)
        if len(TOASTS) != n:
            n, quiet = len(TOASTS), 0
        else:
            quiet += 1


def wait_for(pred, ms=4000):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QGuiApplication.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def build(app, start_dir, ops):
    """The real Main.qml, offscreen, on the given FileOps."""
    engine = QQmlApplicationEngine()
    ctx = engine.rootContext()
    keep = (ops, filermain.Palette(filermain.PANEL_THEME), filermain.Settings(),
            filermain.DirWatch(), filermain.WinCtl(), filermain.VideoConv(),
            StubTitlebar(), filermain.Picker(None), DeskStyle(parent=engine),
            filermain.Phone())
    for name, obj in (("FileOps", keep[0]), ("WalPalette", keep[1]),
                      ("Settings", keep[2]), ("DirWatch", keep[3]),
                      ("WinCtl", keep[4]), ("VideoConv", keep[5]),
                      ("Titlebar", keep[6]), ("Picker", keep[7]),
                      ("DeskStyle", keep[8]), ("Phone", keep[9])):
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


def run_one(ops, argv, reselect=""):
    """One standalone op; returns the toasts it produced."""
    del TOASTS[:]
    ops.run(argv, reselect)
    settle()
    return list(TOASTS)


def main():
    app = QGuiApplication(sys.argv)
    if app.platformName() != "offscreen":   # a mapped window would be HIS screen
        raise SystemExit("refusing to run on platform %r, not offscreen"
                         % app.platformName())
    filermain.toast = stub_toast          # never notify the user from a test
    tmp = tempfile.mkdtemp(prefix="t_fileop-")
    src = os.path.join(tmp, "src")
    dst = os.path.join(tmp, "dst")
    ro = os.path.join(tmp, "readonly")    # chmod 500: a real denied destination
    os.makedirs(src)
    os.makedirs(dst)
    os.makedirs(ro)
    for n in ("a.txt", "b.txt", "c.txt"):
        open(os.path.join(src, n), "w").write("x")
    os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)

    ops = filermain.FileOps()

    # ---- 1. the label a message will use, per argv ----
    lab = filermain._op_label
    check("cp is called copy", lab(["cp", "-a", "--", "s", "d"]) == "copy")
    check("rm is called delete", lab(["rm", "-rf", "--", "s"]) == "delete")
    check("ln is called link", lab(["ln", "-s", "--", "s", "d"]) == "link")
    check("mkdir is called new folder", lab(["mkdir", "--", "d"]) == "new folder")
    check("gio trash is called trash", lab(["gio", "trash", "--", "s"]) == "trash")
    check("mv within one dir is a rename, not a move",
          lab(["mv", "--", "/a/x", "/a/y"]) == "rename")
    check("mv across dirs is a move",
          lab(["mv", "--", "/a/x", "/b/x"]) == "move")

    # ---- 2. success is silent ----
    t = run_one(ops, ["cp", "-an", "--", os.path.join(src, "a.txt"), dst])
    check("a copy that works reports nothing", t == [], t)
    check("...and actually copied", os.path.exists(os.path.join(dst, "a.txt")))

    # ---- 3. a denied destination is reported, with the reason ----
    t = run_one(ops, ["cp", "-an", "--", os.path.join(src, "a.txt"), os.path.join(ro, "a.txt")])
    check("a denied copy reports exactly one failure", len(t) == 1, t)
    check("...titled 'copy failed'", t and t[0][0] == "copy failed", t)
    check("...carrying cp's own reason", t and "Permission denied" in t[0][1], t)
    check("...as a critical toast", t and t[0][2] == "critical", t)

    # ---- 4. a root-owned destination (nothing under / is ours) ----
    t = run_one(ops, ["cp", "-an", "--", os.path.join(src, "a.txt"), "/filer-denied-test"])
    check("a root-owned destination is reported",
          len(t) == 1 and "Permission denied" in t[0][1], t)
    check("...and nothing was created there", not os.path.exists("/filer-denied-test"))

    # ---- 5. a source that does not exist ----
    t = run_one(ops, ["cp", "-an", "--", os.path.join(src, "nope.txt"), dst])
    check("a missing source is reported",
          len(t) == 1 and "No such file" in t[0][1], t)

    # ---- 6. a full disk, for real: /dev/full returns ENOSPC on write ----
    big = os.path.join(src, "big.bin")
    open(big, "wb").write(os.urandom(200000))
    t = run_one(ops, ["cp", "--", big, "/dev/full"])
    check("a full disk is reported",
          len(t) == 1 and "No space left" in t[0][1], t)

    # ---- 7. a denied delete, and a denied rename ----
    open(os.path.join(dst, "keep.txt"), "w").write("x")
    t = run_one(ops, ["rm", "-rf", "--", "/etc/hostname"])
    check("a denied rm -rf reports 'delete failed'",
          len(t) == 1 and t[0][0] == "delete failed" and "Permission denied" in t[0][1], t)
    check("...and /etc/hostname is still there", os.path.exists("/etc/hostname"))
    t = run_one(ops, ["mkdir", "--", os.path.join(ro, "sub")])
    check("a denied mkdir reports 'new folder failed'",
          len(t) == 1 and t[0][0] == "new folder failed", t)
    t = run_one(ops, ["mv", "--", os.path.join(dst, "keep.txt"), os.path.join(ro, "keep.txt")])
    check("a denied move reports 'move failed'", len(t) == 1 and t[0][0] == "move failed", t)
    check("...and the source survived the failed move",
          os.path.exists(os.path.join(dst, "keep.txt")))

    # ---- 8. "could not be started" is a DIFFERENT sentence from "failed" ----
    t = run_one(ops, ["filer-no-such-binary-xyz", "--", dst])
    check("a missing helper reports 'cannot run <prog>'",
          len(t) == 1 and t[0][0] == "cannot run filer-no-such-binary-xyz", t)
    check("...and says the program is the problem, not the file",
          t and "Permission denied" not in t[0][1] and "filer-no-such-binary-xyz" in t[0][1], t)

    # ---- 9. execDetached: a launch that cannot happen says so ----
    del TOASTS[:]
    ok = ops.execDetached(["filer-no-such-binary-xyz"])
    check("execDetached of a missing binary returns False", ok is False)
    check("...and toasts instead of silently doing nothing",
          len(TOASTS) == 1 and TOASTS[0][0].startswith("cannot run"), TOASTS)
    del TOASTS[:]
    ok = ops.execDetached(["true"])
    check("execDetached of a real binary is silent", ok is True and TOASTS == [], TOASTS)

    # ---- 10. finished() still fires on failure: the view must refresh ----
    seen = []
    ops.finished.connect(lambda r: seen.append(r))
    del TOASTS[:]
    ops.run(["cp", "-an", "--", os.path.join(src, "a.txt"), os.path.join(ro, "z")], "/x")
    settle()
    check("a FAILED op still emits finished(), so the view rebuilds",
          seen == ["/x"], seen)

    # ---- 11. partial failure: 3 of 10, as one honest toast ----
    del TOASTS[:]
    batch = ops.beginBatch("copy")
    for i in range(10):
        target = ro if i < 3 else dst
        ops.run(["cp", "-an", "--", os.path.join(src, "a.txt"),
                 os.path.join(target, "p%d.txt" % i)], "", batch)
    ops.endBatch(batch)
    settle()
    check("a partly-failed batch reports ONCE, not per item", len(TOASTS) == 1, TOASTS)
    check("...and says how many of how many failed",
          TOASTS and TOASTS[0][0] == "copy: 3 of 10 failed", TOASTS)
    check("...and the seven that worked are on disk",
          all(os.path.exists(os.path.join(dst, "p%d.txt" % i)) for i in range(3, 10)))
    del TOASTS[:]
    batch = ops.beginBatch("copy")
    for i in range(4):
        ops.run(["cp", "-an", "--", os.path.join(src, "a.txt"),
                 os.path.join(dst, "q%d.txt" % i)], "", batch)
    ops.endBatch(batch)
    settle()
    check("a batch where everything works is silent", TOASTS == [], TOASTS)

    # ---- 12. the no-clobber default is NOT a failure ----
    open(os.path.join(dst, "nc.txt"), "w").write("OLD")
    t = run_one(ops, ["cp", "-an", "--", os.path.join(src, "a.txt"), os.path.join(dst, "nc.txt")])
    check("cp -an declining to clobber is not reported as a failure", t == [], t)
    check("...and the existing file is untouched",
          open(os.path.join(dst, "nc.txt")).read() == "OLD")
    t = run_one(ops, ["mv", "-n", "--", os.path.join(src, "b.txt"), os.path.join(dst, "nc.txt")])
    check("mv -n declining to clobber is not reported as a failure", t == [], t)
    check("...and the source was NOT consumed", os.path.exists(os.path.join(src, "b.txt")))

    # ---- 13. the real QML: a drop/paste into a denied directory ----
    engine, win, keep = build(app, dst, ops)
    view = find(win, "dropTarget")
    check("Main.qml loads", view is not None)
    win.show()
    spin(250)

    del TOASTS[:]
    view.transferInto([os.path.join(src, "a.txt"), os.path.join(src, "c.txt")], ro, "copy", False)
    settle()
    check("a transfer into a denied dir reports (the QML path, not a stub)",
          len(TOASTS) == 1 and TOASTS[0][0] == "copy: 2 of 2 failed", TOASTS)

    del TOASTS[:]
    view.transferInto([os.path.join(src, "a.txt")], dst, "copy", False)
    check("a transfer that works is still silent",
          wait_for(lambda: os.path.exists(os.path.join(dst, "a.txt"))) and TOASTS == [], TOASTS)

    # a conflict is held for the overwrite confirm — never a failure, never a
    # clobber. (drop-test.py owns the dialog itself; this asserts the seam.)
    del TOASTS[:]
    open(os.path.join(dst, "c.txt"), "w").write("OLD")
    raised = view.transferInto([os.path.join(src, "c.txt")], dst, "copy", False)
    settle(600)
    check("a name already taken raises the confirm, and reports no failure",
          raised is True and TOASTS == [], TOASTS)
    check("...and nothing was written behind it",
          open(os.path.join(dst, "c.txt")).read() == "OLD")

    # ---- 14. both run() arities are reachable FROM QML ----
    # `run` is two overloaded slots: the 2-arg form every single-process call
    # site uses (mkdir, rename, trash, delete) and the 3-arg batch form
    # runPaste uses. A Python-side call proves neither, since PySide resolves
    # those differently — so drive both through a real QML expression.
    del TOASTS[:]
    probe = QQmlComponent(engine)
    probe.setData((
        'import QtQuick\nQtObject {\n'
        '  function two()   { FileOps.run(["mkdir", "--", "%s/qml2"], "%s/qml2") }\n'
        '  function three() { const b = FileOps.beginBatch("copy");\n'
        '                     FileOps.run(["cp", "-an", "--", "%s", "%s/qml3"], "", b);\n'
        '                     FileOps.endBatch(b) }\n'
        '  function bad()   { FileOps.run(["mkdir", "--", "%s/nope"], "") }\n'
        '}\n' % (dst, dst, os.path.join(src, "a.txt"), dst, ro)
    ).encode(), QUrl("qrc:/probe.qml"))
    obj = probe.create(engine.rootContext())
    check("the QML probe builds", obj is not None, probe.errorString())
    obj.two()
    check("QML can call the 2-arg run() (mkdir/rename/trash/delete)",
          wait_for(lambda: os.path.isdir(os.path.join(dst, "qml2"))))
    obj.three()
    check("QML can call the 3-arg batch run() (paste/drop)",
          wait_for(lambda: os.path.exists(os.path.join(dst, "qml3"))))
    settle()
    check("...and neither said anything, because both worked", TOASTS == [], TOASTS)
    del TOASTS[:]
    obj.bad()
    settle()
    check("a 2-arg QML call that fails still reports",
          len(TOASTS) == 1 and TOASTS[0][0] == "new folder failed", TOASTS)

    os.chmod(ro, stat.S_IRWXU)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAILS:
        print("FAILED:", ", ".join(FAILS))
        sys.exit(1)
    print("all file-op checks passed")


QTimer.singleShot(0, lambda: None)
main()
