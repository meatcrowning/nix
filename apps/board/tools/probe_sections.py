import os, sys, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv)
from PySide6.QtCore import QUrl, QPointF
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent
import PySide6.QtQuick
from deskstyle import DeskStyle
import main as brd

engine = QQmlApplicationEngine()
ctx = engine.rootContext()
keep = (brd.Palette(brd.PANEL_THEME), DeskStyle(parent=engine), None, None,
        brd.Settings(), brd.Agents(), brd.Usage())
# minimal stubs
class Tb:
    def setButtons(self, b): pass
    def setFooter(self, t): pass
    def setTitleText(self, o): pass
keep = (brd.Palette(brd.PANEL_THEME), DeskStyle(parent=engine), Tb(),
        brd.Board(path=os.environ.get("BOARD_PROBE", "/tmp/probe/board.md")),
        brd.Settings(), brd.Agents(), brd.Usage())
ctx.setContextProperty("WalPalette", keep[0])
ctx.setContextProperty("DeskStyle", keep[1])
ctx.setContextProperty("Titlebar", keep[2])
ctx.setContextProperty("Board", keep[3])
ctx.setContextProperty("Settings", keep[4])
ctx.setContextProperty("Agents", keep[5])
ctx.setContextProperty("Usage", keep[6])
keep[6].follow(keep[5])
comp = QQmlComponent(engine, QUrl.fromLocalFile(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "qml/theme/Theme.qml")))
theme = comp.create()
theme.setParent(app)
ctx.setContextProperty("Theme", theme)
engine.load(QUrl.fromLocalFile(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "qml/Main.qml")))
roots = engine.rootObjects()
root = roots[0]

def descendants(item):
    out = []
    stack = list(item.childItems())
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(c.childItems())
    return out

for _ in range(60):
    app.processEvents(); time.sleep(0.02)

agrows = [it for it in descendants(root.contentItem())
          if it.property("doingLine") is not None
          and it.property("nameNeeded") is not None]
print("AGENTROWS:", len(agrows))
for it in agrows:
    print("  card parent=%s parentclass=%s%s y=%.0f h=%.0f mapScene=(%.0f,%.0f)"
          % (it.parent() is not None, 
             it.parent().metaObject().className() if it.parent() else None,
             " PARENTED" if it.parent() else " DETACHED",
             it.y(), it.height(),
             it.mapToScene(QPointF(0,0)).x(), it.mapToScene(QPointF(0,0)).y()))
    if it.parent():
        p = it.parent()
        print("     parent(of card) y=%.0f h=%.0f cls=%s" % (p.y(), p.height(), p.metaObject().className()))

# find sectionsCol / sectionsRepeater
for nm in ("sectionsCol", "sectionsRepeater", "page"):
    pass
sc = [it for it in descendants(root.contentItem()) if it.objectName() == "sectionsCol"]
print("sectionsCol found:", len(sc))
rp = [it for it in descendants(root.contentItem()) if it.objectName() == "sectionsRepeater"]
print("sectionsRepeater found:", len(rp))
