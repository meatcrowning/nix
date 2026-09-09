#!/usr/bin/env python3
"""Native QQC/Kirigami roles with a real KDE config, offscreen only."""
import os
import tempfile
from pathlib import Path
assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"
assert not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY")
os.environ["QT_QUICK_CONTROLS_STYLE"] = "org.kde.desktop"
ROOT = Path(__file__).resolve().parents[3]
with tempfile.TemporaryDirectory(prefix="native-controls-test-") as temporary:
    os.environ["XDG_CONFIG_HOME"] = temporary
    os.environ["XDG_CONFIG_DIRS"] = temporary
    os.environ["XDG_CACHE_HOME"] = temporary + "/cache"
    Path(temporary, "kdeglobals").write_text(
        "[Colors:Window]\nBackgroundNormal=53,28,25\nForegroundNormal=255,255,255\n"
        "[Colors:View]\nBackgroundNormal=224,201,196\nForegroundNormal=32,21,20\n"
        "[Colors:Button]\nBackgroundNormal=80,53,47\nForegroundNormal=255,250,250\n")
    from PySide6.QtCore import QObject, QUrl, Property
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQuickWidgets import QQuickWidget
    from PySide6.QtQml import QQmlComponent
    app = QApplication(["native-controls-test"])
    assert app.platformName() == "offscreen"
    view = QQuickWidget()
    class DeskStyle(QObject):
        plasma = Property(bool, lambda self: True, constant=True)
    desk = DeskStyle()
    view.engine().rootContext().setContextProperty("DeskStyle", desk)
    component = QQmlComponent(view.engine())
    qml = """
import QtQuick
import QtQuick.Controls
import org.kde.kirigami as Kirigami
Item {
    width: 300; height: 160
    NativeContentContext {}
    Label { objectName: "content"; text: "content" }
    ToolBar {
        y: 50; width: 300
        Kirigami.Theme.colorSet: Kirigami.Theme.Window
        Kirigami.Theme.inherit: false
        Label { objectName: "chrome"; text: "chrome" }
    }
}
"""
    qml = 'import "file://' + str(ROOT / "apps/qmlcommon") + '"\n' + qml
    component.setData(qml.encode(), QUrl())
    root = component.create()
    assert root is not None, component.errorString()
    view.setContent(QUrl(), component, root)
    app.processEvents()
    assert root.findChild(QObject, "content").property("color").name() == "#201514"
    assert root.findChild(QObject, "chrome").property("color").name() == "#ffffff"
    window_component = QQmlComponent(view.engine())
    window_qml = qml.replace("Item {", "Window {", 1)
    window_component.setData(window_qml.encode(), QUrl())
    window = window_component.create()
    assert window is not None, window_component.errorString()
    app.processEvents()
    assert window.findChild(QObject, "content").property("color").name() == "#201514"
    assert window.findChild(QObject, "chrome").property("color").name() == "#ffffff"
    for name in ("board", "editor", "filer", "reader", "painter", "player", "oracle"):
        menu_component = QQmlComponent(view.engine(), QUrl.fromLocalFile(
            str(ROOT / "apps" / name / "qml/+plasma/CtxMenu.qml")))
        menu = menu_component.create()
        assert menu is not None, menu_component.errorString()
        menu.deleteLater()
    for name in ("painter", "player", "oracle", "board", "style"):
        text = (ROOT / "apps" / name / "qml/Root.qml").read_text()
        assert "NativeContentContext {}" in text, name
    for path in (ROOT / "apps").rglob("*.qml"):
        assert "import QtQuick.Controls.Basic" not in path.read_text(), path
    for path in (ROOT / "apps").glob("*/main.py"):
        if "class Palette(QObject)" in path.read_text():
            assert "kdeshell.pin_controls_style()" in path.read_text(), path
    print("ok - native content labels use View; toolbar labels use Window")
    print("ok - all apps select the native style; no shared QML forces Basic")
